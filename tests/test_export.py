import json
import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from hpedb.db import (
    init_classifications,
    init_db,
    update_replication_url,
    upsert_article,
    upsert_classification,
)
from hpedb.export import export_hpe_articles
from hpedb.types import ArticleRecord, ClassificationRecord

_HPE: ArticleRecord = {
    "doi": "10.1017/hpe001", "journal": "APSR",
    "title": "State Formation in Europe", "year": 2020,
    "month": 3, "volume": "114", "issue": "2", "pages": "1-20",
    "abstract": "We study state formation.",
}

_NON_HPE: ArticleRecord = {
    "doi": "10.1017/nothpe001", "journal": "APSR",
    "title": "Contemporary Voting Behavior", "year": 2021,
    "month": 1, "volume": "115", "issue": "1", "pages": "1-10",
    "abstract": "We study contemporary voting.",
}


def _cls(doi: str, is_hpe: bool) -> ClassificationRecord:
    return ClassificationRecord(
        doi=doi, is_hpe=is_hpe,
        period_start=1800 if is_hpe else None,
        period_end=1900 if is_hpe else None,
        regions='["Western Europe"]' if is_hpe else "[]",
        backend="claude", model="claude-haiku-4-5-20251001",
        classified_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = init_db(str(tmp_path / "test.db"))
    init_classifications(c)
    yield c
    c.close()


def test_export_empty_db(conn: sqlite3.Connection) -> None:
    assert export_hpe_articles(conn) == []


def test_export_hpe_only(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_article(conn, _NON_HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    upsert_classification(conn, _cls(_NON_HPE["doi"], False))
    entries = export_hpe_articles(conn)
    assert len(entries) == 1
    assert entries[0]["doi"] == _HPE["doi"]


def test_export_regions_parsed_as_list(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    entries = export_hpe_articles(conn)
    assert isinstance(entries[0]["regions"], list)
    assert entries[0]["regions"] == ["Western Europe"]


def test_export_replication_url_null_when_not_set(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    entries = export_hpe_articles(conn)
    assert entries[0]["replication_url"] is None


def test_export_replication_url_present_when_set(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/TEST"
    update_replication_url(conn, _HPE["doi"], url)
    entries = export_hpe_articles(conn)
    assert entries[0]["replication_url"] == url


def test_export_authors_formatted(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    conn.execute(
        "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
        (_HPE["doi"], 0, "John", "Smith"),
    )
    conn.execute(
        "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
        (_HPE["doi"], 1, "Alice", "Jones"),
    )
    conn.commit()
    entries = export_hpe_articles(conn)
    assert entries[0]["authors"] == "Smith, J.; Jones, A."


def test_export_author_family_only(conn: sqlite3.Connection) -> None:
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    conn.execute(
        "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
        (_HPE["doi"], 0, None, "Aristotle"),
    )
    conn.commit()
    entries = export_hpe_articles(conn)
    assert entries[0]["authors"] == "Aristotle"


def test_export_output_is_valid_json(conn: sqlite3.Connection, tmp_path: Path) -> None:
    from hpedb.export import main
    import sys
    upsert_article(conn, _HPE)
    upsert_classification(conn, _cls(_HPE["doi"], True))
    conn.close()

    db_path = str(tmp_path / "test.db")
    out_path = str(tmp_path / "out.json")

    # Re-open since conn is closed by fixture; use a fresh db
    c = init_db(db_path)
    init_classifications(c)
    upsert_article(c, _HPE)
    upsert_classification(c, _cls(_HPE["doi"], True))
    c.close()

    old_argv = sys.argv
    try:
        sys.argv = ["hpedb-export", "--db", db_path, "--out", out_path]
        main()
    finally:
        sys.argv = old_argv

    data = json.loads(Path(out_path).read_text())
    assert isinstance(data, list)
    assert len(data) == 1
