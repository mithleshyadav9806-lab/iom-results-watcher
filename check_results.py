"""
Checks the IOM Exam Results page for new entries and sends a free push
notification (via ntfy.sh) when a new result appears.

State (the last-seen result title) is stored in state.json in this repo.
The GitHub Actions workflow commits the updated state.json back to the repo
after every run, so the check is stateful across runs.
"""

import json
import os
import sys
import requests
from bs4 import BeautifulSoup

URL = "https://iom.edu.np/examination/exam-results/"
STATE_FILE = "state.json"

# Set this to your own topic name (see README) via the NTFY_TOPIC env var,
# or just hardcode a random, hard-to-guess topic string here.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()


def fetch_results():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(URL, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # Each result is an <h3>-ish heading with a link, followed by a date.
    for heading in soup.find_all(["h3", "h2"]):
        link = heading.find("a")
        if link and link.get("href") and "drive.google.com" in link.get("href", ""):
            title = link.get_text(strip=True)
            href = link["href"]
            results.append({"title": title, "url": href})

    return results


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_titles": []}


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
    if not results:
        print("Warning: no results parsed from page. Site structure may have changed.")
        sys.exit(0)

    state = load_state()
    known_titles = set(state.get("last_titles", []))
    current_titles = [r["title"] for r in results]

    new_items = [r for r in results if r["title"] not in known_titles]

    if not known_titles:
        # First ever run: just record state, don't spam a notification
        # for every existing result.
        print("First run: initializing state with current results, no notification sent.")
    elif new_items:
        print(f"Found {len(new_items)} new result(s).")
        notify(new_items)
    else:
        print("No new results.")

    state["last_titles"] = current_titles
    save_state(state)


if __name__ == "__main__":
    main()
