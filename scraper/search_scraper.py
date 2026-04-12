import logging
import time
from typing import Any, Callable, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from config import MAX_SEARCH_PAGES
from scraper.models import AuthorOnPaper, Paper
from scraper.utils import normalize_url, paper_id_from_url, search_url


logger = logging.getLogger(__name__)


PAPER_EXTRACTION_SCRIPT = """
() => {
  const paperHref = (href) => href && href.includes('/paper/');
  const authorHref = (href) => href && href.includes('/author/');
  const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
  const absolutize = (href) => href ? new URL(href, window.location.origin).href : null;
  const cardFor = (anchor) => {
    const selectors = [
      '[data-test-id*="paper"]',
      '[class*="paper-card"]',
      '[class*="paper-row"]',
      '[class*="result"]',
      'article',
      'li'
    ];
    for (const selector of selectors) {
      const el = anchor.closest(selector);
      if (el) return el;
    }
    return anchor.parentElement;
  };
  const authorContainerFor = (card) => {
    const selectors = [
      '.cl-paper-authors',
      '[class*="paper-authors"]',
      '[data-test-id*="authors"]',
      '[data-test-id*="author"]',
      '[class*="author-list"]',
      '[class*="authors"]',
      '[class*="author"]'
    ];
    for (const selector of selectors) {
      const el = card.querySelector(selector);
      if (!el || !clean(el.innerText)) continue;
      if (el.matches('a[href*="/author/"]') && el.parentElement) return el.parentElement;
      return el;
    }
    return card;
  };
  const authorNamesFromText = (text) => {
    return clean(text)
      .replace(/\\+\\s*\\d+\\s*authors?/ig, '')
      .replace(/show all authors/ig, '')
      .split(/,|;| and /i)
      .map(clean)
      .filter((name) => name && name.length <= 100 && !/^(pdf|save|cite|abstract|tldr)$/i.test(name));
  };

  const rows = [];
  const seenPaperUrls = new Set();
  const anchors = Array.from(document.querySelectorAll('a[href*="/paper/"]'));

  for (const anchor of anchors) {
    const title = clean(anchor.innerText || anchor.getAttribute('aria-label'));
    if (!title || title.length < 5) continue;

    const href = anchor.getAttribute('href');
    if (!paperHref(href)) continue;
    const paperUrl = absolutize(href);
    if (seenPaperUrls.has(paperUrl)) continue;
    seenPaperUrls.add(paperUrl);

    const card = cardFor(anchor);
    const authorContainer = authorContainerFor(card);
    const linkedAuthors = Array.from(authorContainer.querySelectorAll('a[href*="/author/"]'))
      .map((authorAnchor) => ({
        author_name: clean(authorAnchor.innerText || authorAnchor.getAttribute('aria-label')),
        author_profile_url: absolutize(authorAnchor.getAttribute('href'))
      }))
      .filter((author) => author.author_name);

    let authors = linkedAuthors;
    if (authors.length === 0) {
      authors = authorNamesFromText(authorContainer.innerText)
        .filter((name) => name !== title)
        .map((name) => ({ author_name: name, author_profile_url: null }));
    }

    rows.push({ paper_title: title, paper_url: paperUrl, authors });
  }

  return rows;
}
"""


def scrape_papers(
    page: Page,
    query: str,
    limit: int,
    on_first_load: Optional[Callable] = None,
) -> list[Paper]:
    papers: list[Paper] = []
    seen_urls: set[str] = set()
    consecutive_empty = 0

    for page_number in range(1, MAX_SEARCH_PAGES + 1):
        url = search_url(query, page_number)
        logger.info("Loading search page %s: %s", page_number, url)
        _goto_with_retry(page, url)

        if page_number == 1 and on_first_load:
            on_first_load(page)

        _wait_for_results(page)

        extracted = page.evaluate(PAPER_EXTRACTION_SCRIPT)
        added = _append_extracted_papers(papers, seen_urls, extracted, limit)
        logger.info(
            "Search page %s yielded %s candidates; added %s; total papers: %s",
            page_number,
            len(extracted),
            added,
            len(papers),
        )

        if len(papers) >= limit:
            return papers[:limit]

        if added == 0:
            consecutive_empty += 1
            logger.warning(
                "Search page %s added 0 new papers (attempt %s); page title: %s",
                page_number,
                consecutive_empty,
                page.title(),
            )
            if consecutive_empty >= 2:
                logger.error("Two consecutive empty pages; stopping pagination")
                break
        else:
            consecutive_empty = 0

        if page_number < MAX_SEARCH_PAGES:
            time.sleep(2)

    logger.warning(
        "Collected %s unique papers, fewer than requested limit %s after %s search pages",
        len(papers),
        limit,
        MAX_SEARCH_PAGES,
    )
    if not papers:
        raise RuntimeError(
            "No Semantic Scholar papers were collected. The page may have been blocked, throttled, "
            "or changed its result markup."
        )
    raise RuntimeError(
        f"Expected exactly {limit} unique papers, but collected {len(papers)}. "
        "No output files were written; increase MAX_SEARCH_PAGES or inspect pagination/blocking."
    )


def _append_extracted_papers(
    papers: list[Paper],
    seen_urls: set[str],
    extracted: list[dict[str, Any]],
    limit: int,
) -> int:
    added = 0
    for row in extracted:
        if len(papers) >= limit:
            break

        paper_url = normalize_url(row.get("paper_url"))
        title = (row.get("paper_title") or "").strip()
        if not paper_url or not title or paper_url in seen_urls:
            continue

        seen_urls.add(paper_url)
        raw_authors = row.get("authors") or []
        authors = [
            AuthorOnPaper(
                author_name=(author.get("author_name") or "").strip(),
                author_profile_url=normalize_url(author.get("author_profile_url")),
            )
            for author in raw_authors
            if (author.get("author_name") or "").strip()
        ]

        deduped_authors: list[AuthorOnPaper] = []
        seen_author_keys: set[str] = set()
        for author in authors:
            key = f"{author.author_name}|{author.author_profile_url or ''}"
            if key in seen_author_keys:
                continue
            seen_author_keys.add(key)
            deduped_authors.append(author)

        papers.append(
            Paper(
                paper_id=paper_id_from_url(paper_url),
                paper_title=title,
                paper_url=paper_url,
                authors=deduped_authors,
            )
        )
        added += 1

    return added


def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="networkidle")
            return
        except PlaywrightTimeoutError as error:
            last_error = error
            logger.warning("Timed out loading %s on attempt %s/%s", url, attempt, attempts)
    if last_error:
        raise last_error


def _wait_for_results(page: Page) -> None:
    try:
        page.wait_for_selector('a[href*="/paper/"]', timeout=20_000)
    except PlaywrightTimeoutError:
        if _is_human_verification_page(page):
            raise RuntimeError("Semantic Scholar served a human verification page for search results.")
        logger.warning("No paper links became visible on %s", page.url)



def _is_human_verification_page(page: Page) -> bool:
    try:
        title = page.title()
        body = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return False
    return "Human Verification" in title or "Complete the security check" in body
