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
