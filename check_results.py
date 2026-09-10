"""
Checks the IOM Exam Results page for new entries and sends a free push
notification (via ntfy.sh) when a genuinely new result appears.

State (last-seen titles + the newest BS date processed so far) is stored
in state.json in this repo. The GitHub Actions workflow commits the
updated state.json back to the repo after every run, so the check is
stateful across runs.

Each result shows a Nepali BS date next to the title (e.g. "२९ साउन
२०८३, शुक्रबार"). We parse that and use it to tell a truly new result
apart from an older result that simply scrolled onto page 1 for the
first time (the page is paginated, 10 results per page).
"""

import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

URL = "https://iom.edu.np/examination/exam-results/"
STATE_FILE = "state.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

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
    """Find the next Nepali BS date text after this node.
    Returns a sortable int key (not a real calendar value), or None."""
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


def notify(new_items):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set, skipping notification. New items found:")
        for item in new_items:
            print(" -", item["title"])
        return

    lines = [f"{item['title']}\n{item['url']}" for item in new_items]
    message = "\n\n".join(lines)
    title = "New IOM Exam Result" if len(new_items) == 1 else f"{len(new_items)} New IOM Exam Results"

    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "loudspeaker",
            },
            timeout=15,
        )
        print("Notification sent via ntfy.sh")
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
        # First ever run: just record state, don't spam a notification
        # for every existing result.
        dated = [r["date_key"] for r in results if r["date_key"] is not None]
        state["max_date_key"] = max(dated) if dated else None
        print("First run: initializing state with current results, no notification sent.")
    else:
        # Only notify for unseen items that are actually newer than the
        # newest date we've already processed. An unseen item with an
        # older (or unparseable) date is backfill -- e.g. an older result
        # that just scrolled onto page 1 -- not a genuinely new posting.
        # Unparseable dates notify anyway: better to over-notify once than
        # silently miss a real new result.
        new_items = [
            r for r in unseen
            if r["date_key"] is None
            or max_known_date is None
            or r["date_key"] > max_known_date
        ]

        if new_items:
            print(f"Found {len(new_items)} new result(s).")
            notify(new_items)
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
