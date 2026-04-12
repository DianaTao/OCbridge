import logging
import re
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from config import AUTHOR_DELAY_SECONDS
from scraper.models import Author
from scraper.utils import parse_count


logger = logging.getLogger(__name__)

_CAPTCHA_COOLDOWN_SECONDS = 30
_MAX_RETRIES = 2


CITATION_EXTRACTION_SCRIPT = """
() => {
  const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
  const candidates = Array.from(document.querySelectorAll('body *'))
    .map((el) => clean(el.innerText))
    .filter((text) => text && /citations/i.test(text) && /\\d/.test(text));

  for (const text of candidates) {
    const patterns = [
      /([\\d,.]+\\s*[kKmM]?)\\s+Citations\\b/,
      /Citations\\s*([\\d,.]+\\s*[kKmM]?)/,
      /([\\d,.]+\\s*[kKmM]?)\\s+Citation\\b/,
      /Citation\\s*([\\d,.]+\\s*[kKmM]?)/
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return match[1];
    }
  }
  return null;
}
"""


def enrich_authors(page: Page, authors: list[Author]) -> None:
    linked_authors = [author for author in authors if author.author_profile_url]
    logger.info("Enriching %s linked authors out of %s total authors", len(linked_authors), len(authors))

    for index, author in enumerate(linked_authors, start=1):
        logger.info("Enriching author %s/%s: %s", index, len(linked_authors), author.author_name)
        author.citation_count = _scrape_with_retry(page, author.author_profile_url)
        time.sleep(AUTHOR_DELAY_SECONDS)


def _scrape_with_retry(page: Page, url: Optional[str]) -> Optional[int]:
    for attempt in range(1, _MAX_RETRIES + 1):
        result, hit_captcha = _scrape_author_citations(page, url)
        if not hit_captcha:
            return result
        cooldown = _CAPTCHA_COOLDOWN_SECONDS * attempt
        logger.info(
            "CAPTCHA detected; cooling down %ss before retry %s/%s for %s",
            cooldown, attempt, _MAX_RETRIES, url,
        )
        time.sleep(cooldown)

    logger.warning("Exhausted %s retries for %s due to CAPTCHA", _MAX_RETRIES, url)
    return None


def _scrape_author_citations(
    page: Page, author_profile_url: Optional[str]
) -> tuple[Optional[int], bool]:
    """Returns (citation_count, hit_captcha)."""
    if not author_profile_url:
        return None, False

    try:
        page.goto(author_profile_url, wait_until="networkidle")

        if _is_captcha_page(page):
            return None, True

        raw_count = page.evaluate(CITATION_EXTRACTION_SCRIPT)
        if raw_count:
            return parse_count(raw_count), False

        body_text = page.locator("body").inner_text(timeout=5_000)
        return _parse_citations_from_text(body_text), False
    except Exception as error:
        logger.warning("Failed to extract citations from %s: %s", author_profile_url, error)
        return None, False


def _is_captcha_page(page: Page) -> bool:
    try:
        title = page.title()
        if "Human Verification" in title:
            return True
        body = page.locator("body").inner_text(timeout=3_000)
        return "Complete the security check" in body
    except Exception:
        return False


def _parse_citations_from_text(text: str) -> Optional[int]:
    compact = re.sub(r"\s+", " ", text)
    patterns = [
        r"([\d,.]+\s*[kKmM]?)\s+Citations\b",
        r"Citations\s*([\d,.]+\s*[kKmM]?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return parse_count(match.group(1))
    return None
