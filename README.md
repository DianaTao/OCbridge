# Semantic Scholar Scraper

Scrapes Semantic Scholar for papers matching a query, grabs author data, visits each author's profile to pull their citation count, and dumps everything into CSV + JSON files. One command, no manual steps.

## Setup

Python 3.10+ required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python main.py
```

Output goes into `output/`:

- `papers.csv` / `papers.json` — 50 papers with title, URL, authors
- `authors.csv` / `authors.json` — unique authors with profile URLs and citation counts
- `paper_authors.csv` / `paper_authors.json` — which author belongs to which paper, in what order

Everything is configurable in `config.py` (query string, result limit, delays, headless mode, etc.).

## Approach

### Why Playwright?

Semantic Scholar is a JavaScript-heavy SPA. The search results don't exist in the raw HTML — they're rendered client-side. So we need a real browser. Playwright launches headless Chromium with a few tweaks to avoid bot detection: a real-looking user-agent, a normal viewport size, and the `navigator.webdriver` flag removed.

The cookie consent banner that appears on first visit is also dismissed automatically.

### Pagination

I initially tried clicking the "next page" button, but that turned out to be fragile — the CSS class names on Semantic Scholar change, and the click-then-wait-for-content-change approach was unreliable. Instead, the scraper just navigates directly to each page URL using the `&page=N` parameter. Much simpler, much more reliable.

There's a 2-second pause between pages to be polite and avoid rate limits.

### Extracting paper + author data

Each search result page is scraped with a single `page.evaluate()` call that runs JavaScript in the browser. The script finds all links pointing to `/paper/` URLs, walks up the DOM to find the surrounding paper card, then pulls out author names and profile links from within that card.

The selectors have several fallbacks (different class naming conventions Semantic Scholar has used), so it's reasonably resilient to minor markup changes. If no author links are found, it falls back to splitting the author text by commas.

### Output format

Since the paper-author relationship is many-to-many (authors appear on multiple papers, papers have multiple authors) and order matters, I went with three normalized tables rather than one big denormalized file. This makes it straightforward to join and query the data however you want.

## Getting to exactly 50 papers

The assignment says "first 4 pages" and "first 50 papers." Semantic Scholar shows about 10 results per page, so 4 pages only gives ~40. I prioritized hitting exactly 50 unique papers, which usually takes 5 pages.

The scraper:
1. Loads pages one at a time, deduplicating by paper URL as it goes.
2. Stops as soon as it hits 50 unique papers.
3. If two pages in a row come back empty (blocked, broken, etc.), it stops early.
4. If it can't reach 50 after `MAX_SEARCH_PAGES` (default 10), it raises an error instead of writing partial output.

## Citation count

I'm pulling the number labeled "Citations" from each author's Semantic Scholar profile page. Not h-index, not "Highly Influential Citations" — just the plain "Citations" count.

The scraper visits each author's profile URL (like `/author/D.-Patterson/1701130`), waits for the page to load, then runs a JS snippet that looks for text matching patterns like "11,693 Citations". It handles comma-separated numbers and shorthand like "1.2k". If the JS extraction misses it, there's a Python regex fallback on the page body text.

If an author doesn't have a profile link, or the profile gets blocked by a CAPTCHA, `citation_count` is stored as null. No rows are dropped.

### Dealing with CAPTCHAs

Semantic Scholar starts throwing human-verification pages if you hit author profiles too fast. The scraper handles this by:

- Waiting 2 seconds between each author (configurable via `AUTHOR_DELAY_SECONDS`)
- Detecting CAPTCHAs by checking for "Human Verification" in the page title
- On CAPTCHA: waiting 30s, retrying; if blocked again, waiting 60s, retrying once more; then giving up and recording null

This gets through most of the authors. A handful at the tail end might still get blocked depending on the day.

## Output schemas

**papers.csv** — `paper_id`, `paper_title`, `paper_url`, `authors` (JSON list of names)

**authors.csv** — `author_id`, `author_name`, `author_profile_url` (nullable), `citation_count` (nullable)

**paper_authors.csv** — `paper_id`, `author_id`, `author_order` (1-based)

### How IDs are generated

Both IDs are deterministic — the same input always produces the same ID, so re-runs are comparable. They use Semantic Scholar's own full identifiers rather than truncated or custom IDs.

**paper_id**: The full 40-character hex hash from the Semantic Scholar paper URL. For example, a paper URL ending in `/39b07ceec72bfee5a6a4626a44de3c2e8828e268` gives `paper_id` = `39b07ceec72bfee5a6a4626a44de3c2e8828e268`. If the URL doesn't contain that hash format, a full SHA-1 hash of the URL is used as a fallback (prefixed with `p_`).

**author_id**: The numeric ID from the author's Semantic Scholar profile URL. A URL like `/author/D.-Patterson/1701130` gives `author_id` = `1701130`. If the author has no profile link, a full SHA-1 hash of the author name is used as a fallback (prefixed with `a_`).

## Limitations

- **Markup changes can break things.** The extraction uses fallback selectors, but a big Semantic Scholar redesign would need code updates.
- **CAPTCHAs.** The retry logic helps, but running too often from the same IP will still get some profiles blocked.
- **Truncated author lists.** Some papers show "...+5 authors" with a collapsed list. The scraper only grabs the visible ones — expanding every one would mean extra clicks and significantly slower runs.
- **No caching.** Every run starts from scratch. If you interrupt it halfway through author enrichment, you lose everything.
- **Sequential.** Author profiles are visited one at a time. Parallel would be faster but would hit rate limits harder.

## What I'd do differently in production

- Use the [Semantic Scholar API](https://api.semanticscholar.org/) for search results instead of scraping — it returns clean JSON, handles pagination properly, and won't break when the frontend changes. Keep browser automation only for things the API doesn't expose.
- Cache author citation counts so repeated runs don't re-scrape everything.
- Add proxy rotation to spread requests across IPs.
- Snapshot sample HTML pages and write unit tests against them so selector breakage gets caught early.
- Add a CLI so you can pass the query, limit, and output dir as arguments instead of editing `config.py`.
- Dockerize the whole thing so the browser version is pinned and it runs the same everywhere.
