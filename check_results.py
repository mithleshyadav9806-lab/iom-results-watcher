"""
Checks the IOM Exam Results page for new entries and sends a free push
notification (via ntfy.sh) when a genuinely new result appears -- plus a
second, distinct notification if that result looks like it might be for
BSc MLT 4th year specifically.

State (last-seen titles + newest BS date processed) is stored in
state.json in this repo. The GitHub Actions workflow commits the updated
state.json back to the repo after every run.
"""

import io
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

URL = "https://iom.edu.np/examination/exam-results/"
STATE_FILE = "state.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

# ---------------------------------------------------------------------
# Nepali BS date parsing (same as before)
# ---------------------------------------------------------------------
NEPALI_DIGITS = "०१२३४५६७८९"
NEPALI_MONTHS = [
    "बैशाख", "जेठ", "असार", "साउन", "भदौ", "असोज",
    "कार्तिक", "मंसिर", "पुष", "माघ", "फागुन", "चैत",
]
DATE_RE = re.compile(
    r"([०-९]{1,2})\s+(" + "|".join(NEPALI_MONTHS) + r")\s+([०-९]{4})"
)


def nepali_to_int(s):
    return int("".join(str(NEPALI_DIGITS.index(ch)) for ch in s))


def parse_bs_date_near(node):
    date_node = node.find_next(string=DATE_RE)
    if not date_node:
        return None
    m = DATE_RE.search(date_node)
    if not m:
        return None
    day = nepali_to_int(m.group(1))
    month = NEPALI_MONTHS.index(m.group(2)) + 1
    year = nepali_to_int(m.group(3))
    return year * 400 + month * 32 + day


# ---------------------------------------------------------------------
# BSc MLT 4th year matching
# ---------------------------------------------------------------------
def normalize(text):
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


PROGRAM_TOKENS = ["BSCMLT", "BMLT", "MEDICALLABORATORYTECHNOLOGY", "MLT"]
YEAR_TOKENS = ["4THYEAR", "4YEAR", "IVYEAR", "FOURTHYEAR", "4THYR", "4YR"]
AMBIGUOUS_TITLE_WORDS = ["various", "multiple"]


def matches_program(text):
    norm = normalize(text)
    has_program = any(tok in norm for tok in PROGRAM_TOKENS)
    has_year = any(tok in norm for tok in YEAR_TOKENS)
    return has_program and has_year


def title_is_ambiguous(title):
    t = title.lower()
    return any(word in t for word in AMBIGUOUS_TITLE_WORDS)


# ---------------------------------------------------------------------
# Google Drive PDF download + text extraction (with OCR fallback)
# ---------------------------------------------------------------------
def gdrive_file_id(view_url):
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", view_url)
    return m.group(1) if m else None


def download_drive_pdf(view_url):
    file_id = gdrive_file_id(view_url)
    if not file_id:
        return None

    session = requests.Session()
    direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        resp = session.get(direct_url, timeout=60)
    except requests.exceptions.RequestException as e:
        print(f"  PDF download failed: {e}")
        return None

    if resp.headers.get("Content-Type", "").startswith("text/html"):
        m = re.search(r'confirm=([0-9A-Za-z_-]+)', resp.text)
        if m:
            try:
                resp = session.get(direct_url, params={"confirm": m.group(1)}, timeout=60)
            except requests.exceptions.RequestException as e:
                print(f"  PDF download (confirm step) failed: {e}")
                return None
        else:
            print("  Could not get PDF bytes (unexpected Drive response).")
            return None

    if not resp.content.startswith(b"%PDF"):
        print("  Downloaded content doesn't look like a PDF, skipping.")
        return None

    return resp.content


def extract_pdf_text(pdf_bytes):
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        print(f"  pdfplumber extraction failed: {e}")

    if len(text.strip()) >= 30:
        return text

    print("  Little/no text layer found, falling back to OCR...")
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes)
        ocr_text = "\n".join(pytesseract.image_to_string(img) for img in images)
        return ocr_text
    except Exception as e:
        print(f"  OCR fallback failed: {e}")
        return text


def check_if_yours(item):
    """Returns True/False/None (None = couldn't determine)."""
    if matches_program(item["title"]):
        return True
    if not title_is_ambiguous(item["title"]):
        return False

    print(f"  Title is ambiguous, downloading PDF to check: {item['title']}")
    pdf_bytes = download_drive_pdf(item["url"])
    if not pdf_bytes:
        return None
    text = extract_pdf_text(pdf_bytes)
    if not text or not text.strip():
        return None
    return matches_program(text)


# ---------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------
def fetch_results():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(URL, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Site unreachable this run ({e}). Skipping, will retry next run.")
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for heading in soup.find_all(["h3", "h2"]):
        link = heading.find("a")
        if link and link.get("href") and "drive.google.com" in link.get("href", ""):
            title = link.get_text(strip=True)
            href = link["href"]
            date_key = parse_bs_date_near(heading)
            results.append({"title": title, "url": href, "date_key": date_key})

    return results


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_titles": [], "max_date_key": None}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def notify(new_items, personal=False):
    if not new_items:
        return
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set, skipping notification. Items:")
        for item in new_items:
            print(" -", item["title"])
        return

    lines = [f"{item['title']}\n{item['url']}" for item in new_items]
    message = "\n\n".join(lines)

    if personal:
        title = (
            "\U0001F3AF Possibly YOUR result (BSc MLT 4th Year)!"
            if len(new_items) == 1
            else f"\U0001F3AF {len(new_items)} results that might be yours (BSc MLT 4th Year)"
        )
        tags = "warning,dart"
    else:
        title = "New IOM Exam Result" if len(new_items) == 1 else f"{len(new_items)} New IOM Exam Results"
        tags = "loudspeaker"

    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": tags},
            timeout=15,
        )
        print(f"Notification sent via ntfy.sh (personal={personal})")
    except Exception as e:
        print(f"Failed to send notification: {e}")


def main():
    results = fetch_results()
    if results is None:
        sys.exit(0)
    if not results:
        print("Warning: no results parsed from page. Site structure may have changed.")
        sys.exit(0)

    state = load_state()
    known_titles = set(state.get("last_titles", []))
    max_known_date = state.get("max_date_key")
    current_titles = [r["title"] for r in results]

    unseen = [r for r in results if r["title"] not in known_titles]

    if not known_titles:
        dated = [r["date_key"] for r in results if r["date_key"] is not None]
        state["max_date_key"] = max(dated) if dated else None
        print("First run: initializing state with current results, no notification sent.")
    else:
        new_items = [
            r for r in unseen
            if r["date_key"] is None
            or max_known_date is None
            or r["date_key"] > max_known_date
        ]

        if new_items:
            print(f"Found {len(new_items)} new result(s).")
            notify(new_items, personal=False)

            personal_matches = []
            for item in new_items:
                yours = check_if_yours(item)
                if yours:
                    personal_matches.append(item)
                elif yours is None:
                    print(f"  Couldn't determine for: {item['title']} "
                          f"(check it manually just in case)")

            if personal_matches:
                notify(personal_matches, personal=True)

            dated = [r["date_key"] for r in new_items if r["date_key"] is not None]
            if dated:
                candidates = dated + ([max_known_date] if max_known_date is not None else [])
                state["max_date_key"] = max(candidates)
        elif unseen:
            print(f"{len(unseen)} previously-unseen item(s) found, but older than "
                  f"the newest date already processed -- treating as backfill, "
                  f"no notification sent.")
        else:
            print("No new results.")

    state["last_titles"] = current_titles
    save_state(state)


if __name__ == "__main__":
    main()
