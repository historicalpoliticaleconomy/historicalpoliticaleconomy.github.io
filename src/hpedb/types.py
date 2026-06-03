from typing import TypedDict


class ArticleRecord(TypedDict):
    doi: str
    journal: str
    title: str | None
    year: int | None
    month: int | None
    volume: str | None
    issue: str | None
    pages: str | None
    abstract: str | None


class AuthorRecord(TypedDict):
    sequence: int
    given: str | None
    family: str | None


class ClassificationRecord(TypedDict):
    doi: str
    is_hpe: bool
    period_start: int | None
    period_end: int | None
    regions: str       # JSON-encoded list[str]
    backend: str
    model: str
    classified_at: str  # ISO-8601
