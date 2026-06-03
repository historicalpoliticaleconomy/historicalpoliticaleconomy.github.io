import sqlite3

from hpedb.types import ArticleRecord, AuthorRecord, ClassificationRecord

CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    doi TEXT PRIMARY KEY,
    journal TEXT NOT NULL,
    title TEXT,
    year INTEGER,
    month INTEGER,
    volume TEXT,
    issue TEXT,
    pages TEXT,
    abstract TEXT
)
"""

CREATE_AUTHORS = """
CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT NOT NULL REFERENCES articles(doi) ON DELETE CASCADE,
    sequence INTEGER,
    given TEXT,
    family TEXT
)
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(CREATE_ARTICLES)
    conn.execute(CREATE_AUTHORS)
    conn.commit()
    return conn


def wipe_db(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS authors")
    conn.execute("DROP TABLE IF EXISTS articles")
    conn.execute(CREATE_ARTICLES)
    conn.execute(CREATE_AUTHORS)
    conn.commit()


def upsert_article(conn: sqlite3.Connection, record: ArticleRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO articles
            (doi, journal, title, year, month, volume, issue, pages, abstract)
        VALUES
            (:doi, :journal, :title, :year, :month, :volume, :issue, :pages, :abstract)
        """,
        record,
    )
    conn.commit()


_CREATE_CLASSIFICATIONS = """
CREATE TABLE IF NOT EXISTS classifications (
    doi             TEXT PRIMARY KEY REFERENCES articles(doi) ON DELETE CASCADE,
    is_hpe          INTEGER NOT NULL,
    period_start    INTEGER,
    period_end      INTEGER,
    regions         TEXT NOT NULL,
    backend         TEXT NOT NULL,
    model           TEXT NOT NULL,
    classified_at   TEXT NOT NULL,
    replication_url TEXT
)
"""


def init_classifications(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_CLASSIFICATIONS)
    # Migration: add replication_url to pre-existing tables
    cols = {row[1] for row in conn.execute("PRAGMA table_info(classifications)").fetchall()}
    if "replication_url" not in cols:
        conn.execute("ALTER TABLE classifications ADD COLUMN replication_url TEXT")
    conn.commit()


def upsert_classification(
    conn: sqlite3.Connection, record: ClassificationRecord
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO classifications
            (doi, is_hpe, period_start, period_end, regions, backend, model, classified_at)
        VALUES
            (:doi, :is_hpe, :period_start, :period_end, :regions, :backend, :model, :classified_at)
        """,
        {**record, "is_hpe": int(record["is_hpe"])},
    )
    conn.commit()


def update_replication_url(conn: sqlite3.Connection, doi: str, url: str) -> None:
    conn.execute(
        "UPDATE classifications SET replication_url = ? WHERE doi = ?",
        (url, doi),
    )
    conn.commit()


def get_unclassified_dois(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT doi FROM articles WHERE doi NOT IN (SELECT doi FROM classifications)"
        ).fetchall()
    ]


def upsert_authors(
    conn: sqlite3.Connection, doi: str, authors: list[AuthorRecord]
) -> None:
    conn.execute("DELETE FROM authors WHERE doi = ?", (doi,))
    conn.executemany(
        "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
        [(doi, a["sequence"], a.get("given"), a.get("family")) for a in authors],
    )
    conn.commit()
