import csv
import json
from pathlib import Path

from scraper.models import Author, Paper, PaperAuthorLink


def write_outputs(
    output_dir: Path,
    papers: list[Paper],
    authors: list[Author],
    paper_authors: list[PaperAuthorLink],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_papers(output_dir / "papers.csv", papers)
    _write_authors(output_dir / "authors.csv", authors)
    _write_paper_authors(output_dir / "paper_authors.csv", paper_authors)
    _write_json(output_dir / "papers.json", papers)
    _write_json(output_dir / "authors.json", authors)
    _write_json(output_dir / "paper_authors.json", paper_authors)


def _write_papers(path: Path, papers: list[Paper]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["paper_id", "paper_title", "paper_url", "authors"])
        writer.writeheader()
        for paper in papers:
            writer.writerow(
                {
                    "paper_id": paper.paper_id,
                    "paper_title": paper.paper_title,
                    "paper_url": paper.paper_url,
                    "authors": json.dumps([author.author_name for author in paper.authors], ensure_ascii=False),
                }
            )


def _write_authors(path: Path, authors: list[Author]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["author_id", "author_name", "author_profile_url", "citation_count"],
        )
        writer.writeheader()
        for author in authors:
            writer.writerow(
                {
                    "author_id": author.author_id,
                    "author_name": author.author_name,
                    "author_profile_url": author.author_profile_url or "",
                    "citation_count": "" if author.citation_count is None else author.citation_count,
                }
            )


def _write_paper_authors(path: Path, paper_authors: list[PaperAuthorLink]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["paper_id", "author_id", "author_order"])
        writer.writeheader()
        for link in paper_authors:
            writer.writerow(
                {
                    "paper_id": link.paper_id,
                    "author_id": link.author_id,
                    "author_order": link.author_order,
                }
            )


def _write_json(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump([_to_json(row) for row in rows], file, indent=2, ensure_ascii=False)
        file.write("\n")


def _to_json(row: object) -> dict[str, object]:
    if isinstance(row, Paper):
        return {
            "paper_id": row.paper_id,
            "paper_title": row.paper_title,
            "paper_url": row.paper_url,
            "authors": [
                {
                    "author_id": author.author_id,
                    "author_name": author.author_name,
                    "author_profile_url": author.author_profile_url,
                }
                for author in row.authors
            ],
        }
    return row.__dict__
