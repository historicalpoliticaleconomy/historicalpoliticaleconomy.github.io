import argparse
import sqlite3
import time
from typing import Any

import requests
from tqdm import tqdm

from hpedb.db import init_db

_SS_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
_BATCH_SIZE = 500
_RATE_LIMIT_PAUSE = 60
_MAX_RETRIES = 3


def _fetch_batch_chunk(
    chunk: list[str], session: requests.Session
) -> dict[str, str]:
    """POST one batch of ≤500 DOIs; return {doi: abstract} for those found."""
    for attempt in range(_MAX_RETRIES):
        resp = session.post(
            _SS_BATCH_URL,
            params={"fields": "abstract"},
            json={"ids": [f"DOI:{doi}" for doi in chunk]},
            timeout=30,
        )
        if resp.status_code == 200:
            results: dict[str, str] = {}
            items: list[dict[str, Any] | None] = resp.json()
            for doi, item in zip(chunk, items):
                if item is not None:
                    abstract: str | None = item.get("abstract") or None
                    if abstract is not None:
                        results[doi] = abstract
            return results
        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < _MAX_RETRIES - 1:
            time.sleep(_RATE_LIMIT_PAUSE * (2 ** attempt))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RuntimeError(
                f"Semantic Scholar API returned {resp.status_code} after {_MAX_RETRIES} attempts"
            )
        raise RuntimeError(f"Semantic Scholar API returned {resp.status_code}")
    raise RuntimeError(f"Semantic Scholar API: exhausted {_MAX_RETRIES} retries")


def supplement_abstracts(conn: sqlite3.Connection) -> tuple[int, int]:
    dois: list[str] = [
        row[0]
        for row in conn.execute(
            "SELECT doi FROM articles WHERE abstract IS NULL"
        ).fetchall()
    ]

    chunks = [dois[i : i + _BATCH_SIZE] for i in range(0, len(dois), _BATCH_SIZE)]
    found = 0

    with requests.Session() as session:
        for chunk in tqdm(chunks, unit="batch"):
            batch = _fetch_batch_chunk(chunk, session)
            for doi, abstract in batch.items():
                conn.execute(
                    "UPDATE articles SET abstract = ? WHERE doi = ?",
                    (abstract, doi),
                )
            conn.commit()
            found += len(batch)

    return found, len(dois)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supplement missing abstracts from Semantic Scholar."
    )
    parser.add_argument(
        "--db",
        default="articles.db",
        metavar="PATH",
        help="Path to the SQLite database file (default: articles.db)",
    )
    args = parser.parse_args()

    conn = init_db(args.db)
    print("Fetching missing abstracts from Semantic Scholar...")
    found, total = supplement_abstracts(conn)
    conn.close()
    print(f"\nDone. Found abstracts for {found}/{total} articles.")
