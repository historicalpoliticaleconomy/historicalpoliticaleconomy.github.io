import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from hpedb.db import init_classifications, init_db, upsert_article, upsert_authors, wipe_db
from hpedb.types import ArticleRecord, AuthorRecord

SAMPLE_ARTICLE: ArticleRecord = {
    "doi": "10.1086/123456",
    "journal": "JOP",
    "title": "Test Article",
    "year": 2022,
    "month": 3,
    "volume": "84",
    "issue": "1",
    "pages": "1-20",
    "abstract": "An abstract.",
}


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db = str(tmp_path / "test.db")
    c = init_db(db)
    yield c
    c.close()


def test_init_creates_tables(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "articles" in tables
    assert "authors" in tables


def test_upsert_article_insert(conn: sqlite3.Connection) -> None:
    upsert_article(conn, SAMPLE_ARTICLE)
    row = conn.execute(
        "SELECT doi, title, year FROM articles WHERE doi=?", (SAMPLE_ARTICLE["doi"],)
    ).fetchone()
    assert row == ("10.1086/123456", "Test Article", 2022)


def test_upsert_article_update(conn: sqlite3.Connection) -> None:
    upsert_article(conn, SAMPLE_ARTICLE)
    updated: ArticleRecord = {**SAMPLE_ARTICLE, "title": "Updated Title"}
    upsert_article(conn, updated)
    count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 1
    title = conn.execute(
        "SELECT title FROM articles WHERE doi=?", (SAMPLE_ARTICLE["doi"],)
    ).fetchone()[0]
    assert title == "Updated Title"


def test_upsert_authors_replaces(conn: sqlite3.Connection) -> None:
    upsert_article(conn, SAMPLE_ARTICLE)
    doi = SAMPLE_ARTICLE["doi"]
    assert doi is not None

    first: list[AuthorRecord] = [{"sequence": 0, "given": "Alice", "family": "Smith"}]
    second: list[AuthorRecord] = [
        {"sequence": 0, "given": "Bob", "family": "Jones"},
        {"sequence": 1, "given": "Carol", "family": "Lee"},
    ]
    upsert_authors(conn, doi, first)
    upsert_authors(conn, doi, second)

    rows = conn.execute(
        "SELECT given, family FROM authors WHERE doi=? ORDER BY sequence", (doi,)
    ).fetchall()
    assert rows == [("Bob", "Jones"), ("Carol", "Lee")]


def test_foreign_key_constraint_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
            ("10.1086/nonexistent", 0, "Jane", "Doe"),
        )


def test_on_delete_cascade(conn: sqlite3.Connection) -> None:
    doi = SAMPLE_ARTICLE["doi"]
    upsert_article(conn, SAMPLE_ARTICLE)
    upsert_authors(conn, doi, [{"sequence": 0, "given": "A", "family": "B"}])

    conn.execute("DELETE FROM articles WHERE doi = ?", (doi,))
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM authors WHERE doi = ?", (doi,)).fetchone()[0] == 0


def test_upsert_authors_empty_list_clears_authors(conn: sqlite3.Connection) -> None:
    doi = SAMPLE_ARTICLE["doi"]
    upsert_article(conn, SAMPLE_ARTICLE)
    upsert_authors(conn, doi, [{"sequence": 0, "given": "A", "family": "B"}])

    upsert_authors(conn, doi, [])

    assert conn.execute("SELECT COUNT(*) FROM authors WHERE doi = ?", (doi,)).fetchone()[0] == 0


# ── Schema migration paths ────────────────────────────────────────────────────

_CREATE_CLASSIFICATIONS_NO_EXTRA_COLS = """
CREATE TABLE classifications (
    doi           TEXT PRIMARY KEY REFERENCES articles(doi) ON DELETE CASCADE,
    is_hpe        INTEGER NOT NULL,
    period_start  INTEGER,
    period_end    INTEGER,
    regions       TEXT NOT NULL,
    backend       TEXT NOT NULL,
    model         TEXT NOT NULL,
    classified_at TEXT NOT NULL
)
"""


def test_init_classifications_adds_replication_url_to_old_schema(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(_CREATE_CLASSIFICATIONS_NO_EXTRA_COLS)
    conn.commit()

    init_classifications(conn)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(classifications)").fetchall()}
    assert "replication_url" in cols
    assert "countries" in cols
    conn.close()


def test_init_classifications_idempotent_on_current_schema(conn: sqlite3.Connection) -> None:
    init_classifications(conn)
    init_classifications(conn)  # calling twice must not raise
    cols = {row[1] for row in conn.execute("PRAGMA table_info(classifications)").fetchall()}
    assert "replication_url" in cols
    assert "countries" in cols


def test_wipe_db(conn: sqlite3.Connection) -> None:
    author: AuthorRecord = {"sequence": 0, "given": "A", "family": "B"}
    doi = SAMPLE_ARTICLE["doi"]
    assert doi is not None

    upsert_article(conn, SAMPLE_ARTICLE)
    upsert_authors(conn, doi, [author])

    wipe_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0] == 0

    upsert_article(conn, SAMPLE_ARTICLE)
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
