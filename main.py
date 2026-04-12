import logging

from playwright.sync_api import sync_playwright

from config import HEADLESS, OUTPUT_DIR, QUERY, RESULT_LIMIT, TIMEOUT_MS
from scraper.author_scraper import enrich_authors
from scraper.search_scraper import scrape_papers
from scraper.utils import build_author_index
from scraper.writer import write_outputs


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _dismiss_cookie_banner(page) -> None:
    try:
        accept_btn = page.locator("button:has-text('ACCEPT & CONTINUE')").first
        if accept_btn.is_visible(timeout=5_000):
            accept_btn.click(timeout=5_000)
            page.wait_for_timeout(1_000)
    except Exception:
        pass


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        try:
            papers = scrape_papers(page, QUERY, RESULT_LIMIT,
                                   on_first_load=_dismiss_cookie_banner)
            authors, paper_authors = build_author_index(papers)
            enrich_authors(page, authors)
            write_outputs(OUTPUT_DIR, papers, authors, paper_authors)
        finally:
            context.close()
            browser.close()

    logger.info(
        "Finished: %s papers, %s authors, %s paper-author links written to %s",
        len(papers),
        len(authors),
        len(paper_authors),
        OUTPUT_DIR,
    )


if __name__ == "__main__":
    main()
