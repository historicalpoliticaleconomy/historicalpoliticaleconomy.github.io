import json
import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

from hpedb.classify import (
    _user_message,
    classify_articles,
    parse_classification_response,
)
from hpedb.db import init_classifications, init_db, upsert_article, upsert_classification
from hpedb.types import ArticleRecord, ClassificationRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ARTICLE: ArticleRecord = {
    "doi": "10.1086/test001", "journal": "JOP",
    "title": "Party Careers in the UK, 1801–1918", "year": 2023,
    "month": 1, "volume": "85", "issue": "1", "pages": "1-20",
    "abstract": "We document the emergence of party hierarchies in 19th-century Britain.",
}

_ARTICLE_NO_ABSTRACT: ArticleRecord = {
    "doi": "10.1086/test002", "journal": "JOP",
    "title": "Contemporary Voting Behavior", "year": 2023,
    "month": 2, "volume": "85", "issue": "2", "pages": "21-40",
    "abstract": None,
}


def _make_record(doi: str, is_hpe: bool = False) -> ClassificationRecord:
    return ClassificationRecord(
        doi=doi, is_hpe=is_hpe, period_start=None, period_end=None,
        regions="[]", backend="openai", model="gpt-4o-mini",
        classified_at="2026-01-01T00:00:00+00:00",
    )


def _conn_fixture(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = init_db(str(tmp_path / "test.db"))
    init_classifications(c)
    upsert_article(c, _ARTICLE)
    upsert_article(c, _ARTICLE_NO_ABSTRACT)
    yield c
    c.close()


import pytest
@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    yield from _conn_fixture(tmp_path)


# ---------------------------------------------------------------------------
# parse_classification_response
# ---------------------------------------------------------------------------

def test_parse_valid_hpe_response() -> None:
    raw = json.dumps({"is_hpe": True, "period_start": 1801, "period_end": 1918,
                      "regions": ["Western Europe"]})
    rec = parse_classification_response(raw, "10.1086/test001", "openai", "gpt-4o-mini")
    assert rec["is_hpe"] is True
    assert rec["period_start"] == 1801
    assert rec["period_end"] == 1918
    assert json.loads(rec["regions"]) == ["Western Europe"]


def test_parse_non_hpe_response() -> None:
    raw = json.dumps({"is_hpe": False, "period_start": None, "period_end": None, "regions": []})
    rec = parse_classification_response(raw, "10.1086/test002", "openai", "gpt-4o-mini")
    assert rec["is_hpe"] is False
    assert rec["period_start"] is None
    assert json.loads(rec["regions"]) == []


def test_parse_missing_keys_uses_defaults() -> None:
    rec = parse_classification_response("{}", "10.1086/x", "claude", "claude-haiku-4-5-20251001")
    assert rec["is_hpe"] is False
    assert json.loads(rec["regions"]) == []


def test_parse_markdown_fenced_json() -> None:
    raw = '```json\n{"is_hpe": true, "period_start": 1800, "period_end": 1900, "regions": ["Western Europe"]}\n```'
    rec = parse_classification_response(raw, "10.1086/x", "claude", "claude-haiku-4-5-20251001")
    assert rec["is_hpe"] is True
    assert rec["period_start"] == 1800
    assert json.loads(rec["regions"]) == ["Western Europe"]


def test_parse_markdown_fenced_json_with_trailing_text() -> None:
    raw = '```json\n{"is_hpe": false, "period_start": null, "period_end": null, "regions": []}\n```\n\n**Reasoning:** This article is not HPE.'
    rec = parse_classification_response(raw, "10.1086/x", "claude", "claude-haiku-4-5-20251001")
    assert rec["is_hpe"] is False


def test_parse_invalid_json_returns_none() -> None:
    assert parse_classification_response("not json", "10.1086/x", "openai", "gpt-4o-mini") is None


def test_parse_non_object_json_returns_none() -> None:
    assert parse_classification_response("[1,2,3]", "10.1086/x", "openai", "gpt-4o-mini") is None


def test_parse_invalid_regions_filtered() -> None:
    raw = json.dumps({"is_hpe": True, "period_start": 1800, "period_end": 1900,
                      "regions": ["Western Europe", "NotARegion", "Global/Comparative"]})
    rec = parse_classification_response(raw, "10.1086/x", "openai", "gpt-4o-mini")
    assert json.loads(rec["regions"]) == ["Western Europe", "Global/Comparative"]


def test_parse_non_integer_period_becomes_none() -> None:
    raw = json.dumps({"is_hpe": True, "period_start": "1800", "period_end": None, "regions": []})
    rec = parse_classification_response(raw, "10.1086/x", "openai", "gpt-4o-mini")
    assert rec["period_start"] is None


def test_parse_null_regions_field() -> None:
    raw = json.dumps({"is_hpe": False, "period_start": None, "period_end": None, "regions": None})
    rec = parse_classification_response(raw, "10.1086/x", "openai", "gpt-4o-mini")
    assert json.loads(rec["regions"]) == []


def test_parse_non_list_regions_field() -> None:
    raw = json.dumps({"is_hpe": True, "period_start": None, "period_end": None,
                      "regions": "Western Europe"})
    rec = parse_classification_response(raw, "10.1086/x", "openai", "gpt-4o-mini")
    assert json.loads(rec["regions"]) == []


# ---------------------------------------------------------------------------
# _user_message
# ---------------------------------------------------------------------------

def test_user_message_with_abstract() -> None:
    msg = _user_message("Some Title", "The abstract.")
    assert "Some Title" in msg
    assert "The abstract." in msg


def test_user_message_without_abstract() -> None:
    msg = _user_message("Some Title", None)
    assert "Some Title" in msg
    assert "No abstract" in msg


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def test_upsert_classification_stores(conn: sqlite3.Connection) -> None:
    upsert_classification(conn, _make_record("10.1086/test001", is_hpe=True))
    row = conn.execute(
        "SELECT is_hpe FROM classifications WHERE doi=?", ("10.1086/test001",)
    ).fetchone()
    assert row[0] == 1


def test_upsert_classification_overwrites(conn: sqlite3.Connection) -> None:
    upsert_classification(conn, _make_record("10.1086/test001", is_hpe=True))
    upsert_classification(conn, _make_record("10.1086/test001", is_hpe=False))
    row = conn.execute(
        "SELECT is_hpe FROM classifications WHERE doi=?", ("10.1086/test001",)
    ).fetchone()
    assert row[0] == 0


def test_get_unclassified_dois_returns_unclassified(conn: sqlite3.Connection) -> None:
    from hpedb.db import get_unclassified_dois
    assert set(get_unclassified_dois(conn)) == {"10.1086/test001", "10.1086/test002"}


def test_get_unclassified_dois_excludes_classified(conn: sqlite3.Connection) -> None:
    from hpedb.db import get_unclassified_dois
    upsert_classification(conn, _make_record("10.1086/test001"))
    assert get_unclassified_dois(conn) == ["10.1086/test002"]


# ---------------------------------------------------------------------------
# classify_articles — batch path mocked at the runner level
# ---------------------------------------------------------------------------

def _stub_run(articles: Any, model: Any, api_key: Any) -> list[ClassificationRecord]:
    return [_make_record(doi) for doi, _, _ in articles]


def test_classify_articles_skips_classified(conn: sqlite3.Connection) -> None:
    upsert_classification(conn, _make_record("10.1086/test001", is_hpe=True))
    with patch("hpedb.classify._run_openai_batch", side_effect=_stub_run):
        n = classify_articles(conn, "openai", "gpt-4o-mini")
    assert n == 1  # only test002 was unclassified


def test_classify_articles_fresh_reclassifies_all(conn: sqlite3.Connection) -> None:
    upsert_classification(conn, _make_record("10.1086/test001", is_hpe=True))
    with patch("hpedb.classify._run_openai_batch", side_effect=_stub_run):
        n = classify_articles(conn, "openai", "gpt-4o-mini", fresh=True)
    assert n == 2


def test_classify_articles_routes_to_claude(conn: sqlite3.Connection) -> None:
    with patch("hpedb.classify._run_claude_batch", side_effect=_stub_run) as mock:
        classify_articles(conn, "claude", "claude-haiku-4-5-20251001")
    mock.assert_called_once()


def test_classify_articles_nothing_to_do(conn: sqlite3.Connection) -> None:
    upsert_classification(conn, _make_record("10.1086/test001"))
    upsert_classification(conn, _make_record("10.1086/test002"))
    with patch("hpedb.classify._run_openai_batch", side_effect=_stub_run) as mock:
        n = classify_articles(conn, "openai", "gpt-4o-mini")
    assert n == 0
    mock.assert_not_called()
