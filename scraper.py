"""
RIP.ie Death Notice Scraper
============================
Collects death notice listing data (name, date, county, town) from the
RIP.ie GraphQL API, going back to January 2019.

On re-runs it skips any record ID already in the CSV, so only new data
is appended.

Requirements:
    pip install requests

Usage:
    python scraper.py                          # 2019-01-01 to today (or last saved date to today)
    python scraper.py --from-date 2023-01-01   # override start date
    python scraper.py --output custom.csv      # custom output file
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests:  pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
GQL_URL = "https://rip.ie/api/graphql"
DEFAULT_OUTPUT = Path("rip_death_notices.csv")
DEFAULT_START = date(2019, 1, 1)
PAGE_DELAY_S = 0.5      # seconds between pages within a month
MONTH_DELAY_S = 1.0     # seconds between months
FLUSH_EVERY = 500       # write to disk every N new records

FIELDNAMES = [
    "id", "firstname", "surname", "nee",
    "county_id", "county", "town_id", "town",
    "created_at",
    "funeral_arrangements_later", "arrangements_change",
    "notice_url",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.rip.ie/death-notice/s/all",
    "Origin": "https://www.rip.ie",
}

GQL_QUERY = """
query searchDeathNoticesForListTable($list: ListInput!, $isTiledView: Boolean!) {
    searchDeathNoticesForList(query: $list, isTiledView: $isTiledView) {
      count
      perPage
      page
      nextPage
      records {
        id
        firstname
        surname
        nee
        createdAt
        funeralArrangementsLater
        arrangementsChange
        county { id name }
        town   { id name }
      }
    }
  }
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── GraphQL fetching ──────────────────────────────────────────────────────────

def gql_page(session: requests.Session, date_from: date, date_to: date,
             page_num: int) -> tuple[list[dict], bool]:
    """
    Fetch one page of results for the given date range.
    Returns (records, has_next_page).
    """
    variables = {
        "list": {
            "filters": [
                {"field": "a.createdAt", "operator": "gte",
                 "value": date_from.strftime("%Y-%m-%d 00:00:00")},
                {"field": "a.createdAt", "operator": "lte",
                 "value": date_to.strftime("%Y-%m-%d 23:59:59")},
            ],
            "orders": [{"field": "a.createdAtCastToDate", "type": "ASC"}],
            "page": page_num,
            "searchFields": [],
        },
        "isTiledView": False,
    }
    try:
        r = session.post(
            GQL_URL,
            json={"query": GQL_QUERY, "variables": variables},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        log.warning(f"Request error (page {page_num}): {e}")
        return [], False

    if "errors" in data:
        log.warning(f"GraphQL error: {data['errors'][0].get('message', data['errors'])}")
        return [], False

    result = data["data"]["searchDeathNoticesForList"]
    return result["records"], result["nextPage"]


# ── Data helpers ──────────────────────────────────────────────────────────────

def to_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "firstname": r.get("firstname") or "",
        "surname": r.get("surname") or "",
        "nee": r.get("nee") or "",
        "county_id": r["county"]["id"] if r.get("county") else "",
        "county": r["county"]["name"] if r.get("county") else "",
        "town_id": r["town"]["id"] if r.get("town") else "",
        "town": r["town"]["name"] if r.get("town") else "",
        "created_at": r.get("createdAt") or "",
        "funeral_arrangements_later": r.get("funeralArrangementsLater", False),
        "arrangements_change": r.get("arrangementsChange") or "NONE",
        "notice_url": f"https://www.rip.ie/death-notice/{r['id']}",
    }


# ── State / CSV helpers ───────────────────────────────────────────────────────

def load_state(output: Path) -> tuple[set[int], date]:
    """Return (existing_id_set, max_created_at_date)."""
    if not output.exists():
        return set(), DEFAULT_START

    ids: set[int] = set()
    max_date = DEFAULT_START

    with open(output, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ids.add(int(row["id"]))
            except (ValueError, KeyError):
                continue
            try:
                d = datetime.fromisoformat(row["created_at"]).date()
                if d > max_date:
                    max_date = d
            except (ValueError, KeyError):
                pass

    return ids, max_date


def append_to_csv(records: list[dict], output: Path) -> None:
    if not records:
        return
    write_header = not output.exists()
    with open(output, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            w.writeheader()
        w.writerows(records)


# ── Date helpers ──────────────────────────────────────────────────────────────

def months_iter(from_date: date, to_date: date):
    cur = date(from_date.year, from_date.month, 1)
    end = date(to_date.year, to_date.month, 1)
    while cur <= end:
        yield cur
        cur = (
            date(cur.year + 1, 1, 1)
            if cur.month == 12
            else date(cur.year, cur.month + 1, 1)
        )


def month_end(d: date) -> date:
    nxt = (
        date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    )
    return nxt - timedelta(days=1)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scrape RIP.ie death notice listing data to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--from-date", metavar="YYYY-MM-DD",
        help="Override start date (default: 2019-01-01 or last saved date)",
    )
    ap.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help=f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    args = ap.parse_args()

    output = Path(args.output)

    # ── Load existing state ───────────────────────────────────────────────────
    existing_ids, last_date = load_state(output)

    if output.exists():
        log.info(f"Existing data: {len(existing_ids):,} records, last date: {last_date}")
        # Re-scrape from the last saved month to catch records added late
        start = date(last_date.year, last_date.month, 1)
    else:
        start = DEFAULT_START
        log.info("No existing CSV — starting from 2019-01-01")

    if args.from_date:
        start = date.fromisoformat(args.from_date)
        log.info(f"Start date overridden to: {start}")

    today = date.today()
    month_list = list(months_iter(start, today))
    log.info(f"Months to process: {len(month_list)}  ({month_list[0]} → {month_list[-1]})")

    # ── Session setup ─────────────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Scrape ────────────────────────────────────────────────────────────────
    buffer: list[dict] = []
    total_new = 0

    def flush():
        nonlocal buffer
        if buffer:
            append_to_csv(buffer, output)
            buffer = []

    try:
        for i, month_start in enumerate(month_list, 1):
            m_end = month_end(month_start)
            label = month_start.strftime("%B %Y")
            month_new = 0
            page_num = 1

            while True:
                records, has_next = gql_page(session, month_start, m_end, page_num)

                for r in records:
                    rid = int(r["id"])
                    if rid not in existing_ids:
                        buffer.append(to_row(r))
                        existing_ids.add(rid)
                        month_new += 1

                if not has_next:
                    break
                page_num += 1
                time.sleep(PAGE_DELAY_S)

            total_new += month_new
            if month_new:
                log.info(
                    f"[{i:>4}/{len(month_list)}] {label:<15} "
                    f"+{month_new:>4} new  (total: {total_new:,})"
                )
            else:
                log.info(f"[{i:>4}/{len(month_list)}] {label:<15}  0 new")

            if len(buffer) >= FLUSH_EVERY:
                flush()
                log.info(f"  → flushed to {output}")

            time.sleep(MONTH_DELAY_S)

    except KeyboardInterrupt:
        log.info("Interrupted — saving progress...")
    finally:
        flush()

    log.info(f"\nDone. Added {total_new:,} new records → {output}")
    if total_new == 0 and output.exists():
        log.info("(Data is already up to date)")


if __name__ == "__main__":
    main()
