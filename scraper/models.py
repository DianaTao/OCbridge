from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthorOnPaper:
    author_name: str
    author_profile_url: Optional[str] = None
    author_id: Optional[str] = None


@dataclass
class Paper:
    paper_id: str
    paper_title: str
    paper_url: str
    authors: list[AuthorOnPaper] = field(default_factory=list)


@dataclass
class Author:
    author_id: str
    author_name: str
    author_profile_url: Optional[str] = None
    citation_count: Optional[int] = None


@dataclass
class PaperAuthorLink:
    paper_id: str
    author_id: str
    author_order: int
