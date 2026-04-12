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

  // Strategy 1: find a leaf-level element whose text is exactly "Citations"
  // (the label), then grab the adjacent sibling that holds the number.
  const allEls = Array.from(document.querySelectorAll('body *'));
  for (const el of allEls) {
    const ownText = clean(el.innerText);
    if (/^Citations$/i.test(ownText) && !el.querySelector('*')) {
      // Check siblings and parent's children for the numeric value
      const parent = el.parentElement;
      if (!parent) continue;
      const siblings = Array.from(parent.children);
      for (const sib of siblings) {
        if (sib === el) continue;
        const sibText = clean(sib.innerText);
        if (/^[\\d,.]+\\s*[kKmM]?$/.test(sibText)) return sibText;
      }
      // Also check parent text in case label and value are in one container
      const parentText = clean(parent.innerText);
      const m = parentText.match(/Citations\\s+([\\d,.]+\\s*[kKmM]?)/i)
             || parentText.match(/([\\d,.]+\\s*[kKmM]?)\\s+Citations/i);
      if (m) return m[1];
    }
  }

  // Strategy 2: find an element whose own text (not children) is exactly
  // "Citations" with a number, being careful to exclude "Highly Influential
  // Citations" and "h-index".
  for (const el of allEls) {
    const text = clean(el.innerText);
    if (/highly influential/i.test(text)) continue;
    if (/h-index/i.test(text)) continue;
    const m = text.match(/^Citations\\s+([\\d,.]+\\s*[kKmM]?)$/i)
           || text.match(/^([\\d,.]+\\s*[kKmM]?)\\s+Citations$/i);
    if (m) return m[1];
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
    # Match "Citations 67,167" but NOT "Highly Influential Citations 4,303"
    # and NOT "h-index 93 Citations" (which would grab 93).
    patterns = [
        r"(?<!Influential\s)Citations\s+([\d,.]+\s*[kKmM]?)",
        r"(?<!index\s)([\d,.]+\s*[kKmM]?)\s+Citations(?!\s+\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return parse_count(match.group(1))
    return None
