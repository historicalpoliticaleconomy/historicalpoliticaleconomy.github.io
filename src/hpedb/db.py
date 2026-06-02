import sqlite3

from hpedb.types import ArticleRecord, AuthorRecord

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


def upsert_authors(
    conn: sqlite3.Connection, doi: str, authors: list[AuthorRecord]
) -> None:
    conn.execute("DELETE FROM authors WHERE doi = ?", (doi,))
    conn.executemany(
        "INSERT INTO authors (doi, sequence, given, family) VALUES (?, ?, ?, ?)",
        [(doi, a["sequence"], a.get("given"), a.get("family")) for a in authors],
    )
    conn.commit()
