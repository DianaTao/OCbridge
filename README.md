# Semantic Scholar Paper & Author Scraper

An end-to-end automated pipeline that searches Semantic Scholar for papers matching a query, collects structured paper and author data, visits author profile pages to extract citation counts, and outputs everything in CSV and JSON.

## Setup

Requires Python 3.10+.

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

A single command runs the full pipeline. Outputs are written to `output/`:

| File | Format | Description |
| --- | --- | --- |
| `papers.csv` / `papers.json` | Flat | 50 papers with title, URL, and authors |
| `authors.csv` / `authors.json` | Flat | Unique authors with profile URL and citation count |
| `paper_authors.csv` / `paper_authors.json` | Join table | Paper-to-author relationships with display order |

All configuration lives in `config.py` (query, result limit, delays, headless mode, etc.).

## Approach & Key Design Choices

### Browser automation with Playwright

Semantic Scholar renders search results dynamically with JavaScript, so a real browser is required. The scraper uses Playwright to launch headless Chromium with anti-detection measures:

- A realistic user-agent string, viewport size, and locale
- The `navigator.webdriver` property is removed via an init script
- The `AutomationControlled` Blink feature is disabled
- A cookie consent banner is dismissed on first page load

### URL-based pagination (not button clicks)

Rather than locating and clicking a "next page" button (which is fragile and breaks when Semantic Scholar updates their CSS classes), the scraper constructs each search page URL directly using the `&page=N` query parameter. This is far more robust and avoids the need for DOM-dependent pagination selectors.

Each page is loaded with `wait_until="networkidle"` to ensure the SPA has fully rendered before extraction, and a 2-second delay is added between pages to avoid rate-limiting.

### JavaScript-based extraction

Paper and author data are extracted from the rendered DOM using a single `page.evaluate()` call that runs a JavaScript function in the browser context. The script:

1. Finds all `<a>` elements linking to `/paper/` URLs
2. Walks up the DOM to find the enclosing paper card
3. Within each card, locates the author container and extracts linked author names and profile URLs
4. Falls back to text-based author name splitting when no author links are present

This approach is more resilient than CSS-selector-only extraction because it uses multiple fallback selectors for both paper cards and author containers.

### Normalized relational output

Paper-author relationships are many-to-many (an author can appear on multiple papers; a paper has multiple authors) and author order matters. The output uses three normalized tables instead of a single denormalized file.

## How Exactly 50 Results Are Ensured

1. The scraper loads search result pages sequentially, starting at page 1.
2. On each page, all paper cards are extracted. Duplicate paper URLs (which can appear across pages) are skipped using a seen-URL set.
3. As soon as 50 unique papers are collected, the list is truncated to exactly 50 and returned.
4. If a page yields 0 new papers, a counter tracks consecutive empty pages. After 2 consecutive empty pages, pagination stops (guards against infinite loops on blocked/empty responses).
5. If fewer than 50 unique papers are collected after exhausting `MAX_SEARCH_PAGES` (default 10), the run raises a `RuntimeError` instead of writing partial output.

The assignment mentions both "first 4 pages" and "first 50 papers." This implementation prioritizes exactly 50 papers: Semantic Scholar shows ~10 results per page, so typically 5 pages are needed. The scraper continues past page 4 if necessary.

## Citation Count: Assumptions & Extraction

- **Which metric**: Only the count explicitly labeled "Citations" on a Semantic Scholar author profile page is used. Related metrics (h-index, paper count, influential citations) are ignored.
- **Where it is extracted**: The scraper visits each author's Semantic Scholar profile URL (e.g., `/author/Name/12345`) and runs a JavaScript extraction script that scans all DOM elements for text matching patterns like `11,693 Citations` or `Citations 11,693`, including shorthand suffixes like `1.2k`.
- **Fallback**: If the JS extraction returns nothing, a Python-side regex scan of the page body text is attempted.
- **Null handling**: If an author has no profile link, or if their profile is blocked by a CAPTCHA, `citation_count` is stored as `null` (JSON) / blank (CSV). Rows are never dropped.

### CAPTCHA handling for author profiles

Semantic Scholar rate-limits rapid author profile visits with human-verification pages. The scraper handles this with:

- A configurable base delay between author requests (`AUTHOR_DELAY_SECONDS`, default 2 seconds)
- Automatic CAPTCHA detection (checks for "Human Verification" in the page title or "Complete the security check" in the body)
- Retry with exponential cooldown: on CAPTCHA, the scraper waits 30 seconds and retries, then 60 seconds on the second attempt, before marking the author's citations as null

## Output Schemas

### `papers.csv`

| Column | Description |
| --- | --- |
| `paper_id` | Deterministic ID derived from the Semantic Scholar paper URL |
| `paper_title` | Paper title as rendered in search results |
| `paper_url` | Normalized Semantic Scholar paper URL |
| `authors` | JSON-encoded list of author names in display order |

### `authors.csv`

| Column | Description |
| --- | --- |
| `author_id` | Semantic Scholar numeric author ID when available; otherwise a deterministic hash |
| `author_name` | Author name as rendered in search results |
| `author_profile_url` | Normalized Semantic Scholar author URL, or blank if no profile link exists |
| `citation_count` | Integer citation count from the "Citations" label on the profile page, or blank if unavailable |

### `paper_authors.csv`

| Column | Description |
| --- | --- |
| `paper_id` | References `paper_id` in `papers.csv` |
| `author_id` | References `author_id` in `authors.csv` |
| `author_order` | 1-based author position as displayed on the paper card |

## Known Limitations

- **DOM fragility**: The JavaScript extraction scripts use multiple fallback selectors, but a major Semantic Scholar redesign could still break extraction.
- **CAPTCHA/rate-limiting**: Despite retry and cooldown logic, aggressive rate-limiting can still block some author profile visits. Running too frequently from the same IP increases this risk.
- **Truncated author lists**: Some paper cards show only a subset of authors with a "+N authors" expander. The scraper extracts only the visible authors; expanding every collapsed list would require additional clicks and slow the pipeline significantly.
- **No persistent caching**: Each run starts fresh. If a run is interrupted mid-way through author enrichment, previous results are lost.
- **Single-threaded**: Author profiles are visited sequentially. Parallel requests would be faster but would also trigger rate-limiting sooner.

## Production Improvements

- **Semantic Scholar API**: For the search step, use the free [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/) instead of browser scraping. The API returns structured JSON, supports pagination natively, and is not affected by DOM changes. Browser automation would only be needed for data not available via the API.
- **Persistent cache**: Cache author citation counts (keyed by author ID + date) to avoid re-scraping on subsequent runs and to resume interrupted runs.
- **Proxy rotation**: Rotate IP addresses to distribute requests and reduce CAPTCHA triggers.
- **Saved HTML fixtures + tests**: Snapshot sample pages and write unit tests for the extraction scripts so DOM changes are caught early.
- **CLI interface**: Accept query, result limit, output directory, and headless mode as command-line arguments instead of editing `config.py`.
- **Docker**: Provide a Dockerfile that pins the Python version, Playwright version, and browser binaries for fully reproducible builds.
