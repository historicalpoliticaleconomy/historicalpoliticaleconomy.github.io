from typing import Any

from habanero import Crossref

from hpedb.types import ArticleRecord, AuthorRecord

JOURNALS: dict[str, str] = {
    "JOP": "0022-3816",
    "APSR": "0003-0554",
    "AJPS": "0092-5853",
}

SELECT_FIELDS: list[str] = [
    "DOI",
    "title",
    "author",
    "abstract",
    "published",
    "volume",
    "issue",
    "page",
]


def make_client(mailto: str) -> Crossref:
    return Crossref(
        mailto=mailto,
        ua_string="hpedb/0.1 (https://github.com/hmrm/hpedb)",
    )


def parse_item(
    item: dict[str, Any], journal: str
) -> tuple[ArticleRecord, list[AuthorRecord]]:
    pub: dict[str, Any] | None = item.get("published")
    date_parts_container: list[list[int]] | None = pub.get("date-parts") if pub is not None else None
    date_parts: list[int] = date_parts_container[0] if date_parts_container else []
    year: int | None = date_parts[0] if date_parts else None
    month: int | None = date_parts[1] if len(date_parts) > 1 else None

    title_list: list[str] | None = item.get("title")
    title: str | None = title_list[0] if title_list else None

    abstract: str | None = item.get("abstract") or None

    record: ArticleRecord = {
        "doi": item["DOI"].lower(),
        "journal": journal,
        "title": title,
        "year": year,
        "month": month,
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("page"),
        "abstract": abstract,
    }

    raw_authors: list[dict[str, Any]] | None = item.get("author")
    authors: list[AuthorRecord] = [
        {
            "sequence": i,
            "given": a.get("given"),
            "family": a.get("family"),
        }
        for i, a in enumerate(raw_authors or [])
    ]

    return record, authors


def fetch_journal(
    cr: Crossref,
    abbrev: str,
    issn: str,
    from_year: int,
    to_year: int,
) -> list[tuple[ArticleRecord, list[AuthorRecord]]]:
    pages: list[dict[str, Any]] = cr.works(
        filter={
            "issn": issn,
            "from_pub_date": f"{from_year}-01-01",
            "until_pub_date": f"{to_year}-12-31",
            "type": "journal-article",
        },
        cursor="*",
        cursor_max=10000,
        select=SELECT_FIELDS,
        progress_bar=True,
    )

    results: list[tuple[ArticleRecord, list[AuthorRecord]]] = []
    for page in pages:
        for item in page["message"]["items"]:
            if item.get("DOI") and item.get("author"):
                results.append(parse_item(item, abbrev))
    return results
