from typing import Any, cast
from unittest.mock import MagicMock

from habanero import Crossref

from hpedb.fetch import fetch_journal, parse_item

FULL_ITEM: dict[str, Any] = {
    "DOI": "10.1086/999999",
    "title": ["Democracy and Representation"],
    "abstract": "This paper examines...",
    "published": {"date-parts": [[2021, 6]]},
    "volume": "83",
    "issue": "2",
    "page": "500-520",
    "author": [
        {"given": "Jane", "family": "Doe", "sequence": "first"},
        {"given": "John", "family": "Smith", "sequence": "additional"},
    ],
}


def test_parse_item_full() -> None:
    article, authors = parse_item(FULL_ITEM, "JOP")
    assert article["doi"] == "10.1086/999999"
    assert article["title"] == "Democracy and Representation"
    assert article["year"] == 2021
    assert article["month"] == 6
    assert article["volume"] == "83"
    assert article["issue"] == "2"
    assert article["pages"] == "500-520"
    assert article["abstract"] == "This paper examines..."
    assert article["journal"] == "JOP"
    assert len(authors) == 2
    assert authors[0] == {"sequence": 0, "given": "Jane", "family": "Doe"}
    assert authors[1] == {"sequence": 1, "given": "John", "family": "Smith"}


def test_parse_item_missing_abstract() -> None:
    item = {**FULL_ITEM}
    del item["abstract"]
    article, _ = parse_item(item, "JOP")
    assert article["abstract"] is None


def test_parse_item_empty_abstract() -> None:
    item: dict[str, Any] = {**FULL_ITEM, "abstract": ""}
    article, _ = parse_item(item, "JOP")
    assert article["abstract"] is None


def test_parse_item_missing_authors() -> None:
    item = {**FULL_ITEM}
    del item["author"]
    _, authors = parse_item(item, "APSR")
    assert authors == []


def test_parse_item_year_only_date() -> None:
    item: dict[str, Any] = {**FULL_ITEM, "published": {"date-parts": [[2020]]}}
    article, _ = parse_item(item, "JOP")
    assert article["year"] == 2020
    assert article["month"] is None


def test_parse_item_normalizes_doi_to_lowercase() -> None:
    item: dict[str, Any] = {**FULL_ITEM, "DOI": "10.1017/S0003055420000234"}
    article, _ = parse_item(item, "APSR")
    assert article["doi"] == "10.1017/s0003055420000234"


def test_parse_item_missing_published() -> None:
    item = {**FULL_ITEM}
    del item["published"]
    article, _ = parse_item(item, "JOP")
    assert article["year"] is None
    assert article["month"] is None


def test_parse_item_empty_date_parts() -> None:
    item: dict[str, Any] = {**FULL_ITEM, "published": {"date-parts": [[]]}}
    article, _ = parse_item(item, "JOP")
    assert article["year"] is None
    assert article["month"] is None


def test_fetch_journal_skips_items_without_doi() -> None:
    item: dict[str, Any] = {k: v for k, v in FULL_ITEM.items() if k != "DOI"}
    mock_cr = MagicMock()
    mock_cr.works.return_value = [{"message": {"items": [item]}}]
    results = fetch_journal(cast(Crossref, mock_cr), "JOP", "0022-3816", 2021, 2022)
    assert results == []


def test_fetch_journal_skips_items_without_authors() -> None:
    item: dict[str, Any] = {k: v for k, v in FULL_ITEM.items() if k != "author"}
    mock_cr = MagicMock()
    mock_cr.works.return_value = [{"message": {"items": [item]}}]
    results = fetch_journal(cast(Crossref, mock_cr), "JOP", "0022-3816", 2021, 2022)
    assert results == []


def test_fetch_journal_returns_parsed_items() -> None:
    mock_cr = MagicMock()
    mock_cr.works.return_value = [{"message": {"items": [FULL_ITEM]}}]
    results = fetch_journal(cast(Crossref, mock_cr), "JOP", "0022-3816", 2021, 2022)
    assert len(results) == 1
    article, authors = results[0]
    assert article["doi"] == FULL_ITEM["DOI"].lower()
    assert len(authors) == 2


def test_fetch_journal_calls_works_with_correct_filters() -> None:
    mock_cr = MagicMock()
    mock_cr.works.return_value = [{"message": {"items": []}}]

    fetch_journal(cast(Crossref, mock_cr), "JOP", "0022-3816", 2021, 2022)

    mock_cr.works.assert_called_once()
    call_kwargs = mock_cr.works.call_args.kwargs
    assert call_kwargs["filter"]["issn"] == "0022-3816"
    assert call_kwargs["filter"]["from_pub_date"] == "2021-01-01"
    assert call_kwargs["filter"]["until_pub_date"] == "2022-12-31"
    assert call_kwargs["filter"]["type"] == "journal-article"
    assert call_kwargs["cursor"] == "*"
