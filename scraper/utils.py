import hashlib
import logging
import re
from typing import Iterable, Optional
from urllib.parse import parse_qs, quote, urldefrag, urljoin, urlparse, urlunparse

from config import BASE_URL
from scraper.models import Author, Paper, PaperAuthorLink


logger = logging.getLogger(__name__)


def search_url(query: str, page_number: int = 1) -> str:
    url = f"{BASE_URL}/search?q={quote(query)}&sort=relevance"
    if page_number > 1:
        url += f"&page={page_number}"
    return url


def normalize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    absolute = urljoin(BASE_URL, url)
    absolute, _fragment = urldefrag(absolute)
    parsed = urlparse(absolute)
    path = re.sub(r"/+$", "", parsed.path)
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def deterministic_id(prefix: str, value: str, length: int = 12) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def paper_id_from_url(paper_url: str) -> str:
    parsed = urlparse(paper_url)
    last_segment = parsed.path.rstrip("/").split("/")[-1]
    if re.fullmatch(r"[a-f0-9]{40}", last_segment):
        return f"p_{last_segment[:12]}"
    return deterministic_id("p", paper_url)


def author_id_from(name: str, profile_url: Optional[str]) -> str:
    if profile_url:
        parsed = urlparse(profile_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "author":
            possible_id = parts[-1]
            if possible_id:
                return f"a_{possible_id}"
        query_id = parse_qs(parsed.query).get("authorId", [None])[0]
        if query_id:
            return f"a_{query_id}"
    return deterministic_id("a", f"{name}|{profile_url or ''}")


def parse_count(value: str) -> Optional[int]:
    cleaned = value.strip().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def unique_in_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_author_index(papers: list[Paper]) -> tuple[list[Author], list[PaperAuthorLink]]:
    authors_by_key: dict[str, Author] = {}
    links: list[PaperAuthorLink] = []

    for paper in papers:
        for index, paper_author in enumerate(paper.authors, start=1):
            profile_url = normalize_url(paper_author.author_profile_url)
            author_id = author_id_from(paper_author.author_name, profile_url)
            key = profile_url or author_id

            if key not in authors_by_key:
                authors_by_key[key] = Author(
                    author_id=author_id,
                    author_name=paper_author.author_name,
                    author_profile_url=profile_url,
                )

            paper_author.author_id = authors_by_key[key].author_id
            links.append(
                PaperAuthorLink(
                    paper_id=paper.paper_id,
                    author_id=authors_by_key[key].author_id,
                    author_order=index,
                )
            )

    return list(authors_by_key.values()), links
