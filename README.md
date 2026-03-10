# RIP.ie Death Notice Scraper

## Overview

This project collects all death notice listing data from RIP.ie going back to January 2019
and saves it to a CSV file. On subsequent runs it only fetches records newer than the last
saved date, making it efficient for keeping the dataset up to date.

---

## Tools Used

### Python
The scraper is written in Python 3 and requires only one third-party package:

    pip install requests

The `requests` library handles all HTTP communication with the RIP.ie API.

### requests
A widely-used Python library for making HTTP requests. It is used here to send POST
requests to the RIP.ie GraphQL API and receive JSON responses.

### GraphQL
GraphQL is a query language for APIs developed by Facebook. Unlike traditional REST APIs
which have many endpoints each returning a fixed set of data, GraphQL has a single endpoint
and the caller specifies exactly which fields they want returned. RIP.ie uses GraphQL as
the internal API between its frontend and backend.

---

## How the Scraper Works

### Discovery of the API

RIP.ie is built with Next.js, a React-based web framework that renders pages on the server
and embeds the resulting data in the HTML inside a `<script id="__NEXT_DATA__">` tag. This
confirmed that the site's data is served dynamically from a backend rather than being static.

Initial attempts to filter the listing by date range using URL query parameters (e.g.
`?dateFrom=2019-01-01`) failed — the server ignored these parameters and always returned
the default 30-day window. To retrieve historical data going back to 2019, a different
approach was needed.

By inspecting the JavaScript bundle files loaded by the browser (listed in the page's HTML
as `<script src="/_next/static/chunks/...">` tags), two key findings emerged:

1. One bundle (`2448-...js`) contained GraphQL query strings in plain text, including the
   query `searchDeathNoticesForList` along with the exact fields it returns.

2. The main app bundle (`pages/_app-...js`) contained a reference to the GraphQL endpoint:
   `https://rip.ie/api/graphql`

A third bundle (`1500-...js`) revealed the structure of the `ListInput` type used to pass
filters to the API, showing that date ranges are passed as `a.createdAt` filters with
`gte` (greater than or equal) and `lte` (less than or equal) operators, in
`YYYY-MM-DD HH:MM:SS` format.

### The API Endpoint

All data is fetched from:

    https://rip.ie/api/graphql

This is the same endpoint RIP.ie's own website JavaScript uses. It is publicly accessible
and requires no API key or authentication.

### Querying Strategy

The scraper works month by month from January 2019 to the present. For each month it sends
a GraphQL POST request with a date range filter, collects all records across paginated
pages (40 records per page), and moves to the next month. The `nextPage` boolean field in
the response is used to detect when all pages for a month have been retrieved (the `count`
field returned by the API is unreliable and always returns 0).

### Incremental Updates

On each run the scraper reads the existing CSV to build a set of all previously collected
record IDs and finds the most recent `created_at` date. It then re-scrapes from the start
of that month (to catch any records published late) through to the current date, skipping
any IDs already in the CSV. This means the second and all subsequent runs are fast and
only collect genuinely new records.

---

## Output File

The scraper writes to `rip_death_notices.csv` by default. A custom path can be specified
with the `--output` flag.

### Columns

| Column                       | Description                                                        | Example                                      |
|------------------------------|--------------------------------------------------------------------|----------------------------------------------|
| `id`                         | Unique numeric ID for the death notice on RIP.ie                   | 359918                                       |
| `firstname`                  | First name(s) of the deceased, including nicknames if listed       | Patrick Joseph (Pat)                         |
| `surname`                    | Surname of the deceased                                            | O'Neill                                      |
| `nee`                        | Maiden name, if listed                                             | Murphy                                       |
| `county_id`                  | Internal numeric ID for the county                                 | 28                                           |
| `county`                     | County name                                                        | Tyrone                                       |
| `town_id`                    | Internal numeric ID for the town                                   | 844                                          |
| `town`                       | Town name                                                          | Dungannon                                    |
| `created_at`                 | Date and time the notice was published, in ISO 8601 format (UTC)   | 2019-01-01T23:52:39.000+00:00                |
| `funeral_arrangements_later` | Boolean indicating funeral details were not yet confirmed          | False                                        |
| `arrangements_change`        | Indicates if funeral arrangements were subsequently changed        | NONE                                         |
| `notice_url`                 | Direct URL to the full notice on RIP.ie                            | https://www.rip.ie/death-notice/359918       |

### Notes on the data

- `firstname` may include nicknames in parentheses, religious titles (Fr., Sr.), and
  multiple given names as they appear on the published notice.
- `nee` is only populated where a maiden name was provided on the notice; otherwise blank.
- `town` and `town_id` may be blank where no town was specified on the notice.
- `created_at` reflects the publication timestamp, not necessarily the date of death.
- `arrangements_change` values include `NONE`, `TimeChange`, `DateChange`,
  `TimeAndDateChange`, and `ChurchCemeteryChange`.

---

## Usage

    # Full scrape from 2019 to today (first run)
    python3 scraper.py

    # Incremental update (subsequent runs)
    python3 scraper.py

    # Override start date
    python3 scraper.py --from-date 2023-01-01

    # Custom output file
    python3 scraper.py --output my_data.csv

The initial full scrape takes approximately 20–30 minutes. Subsequent incremental runs
complete in seconds to a few minutes depending on how much new data has been published.
