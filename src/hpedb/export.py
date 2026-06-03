import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from hpedb.db import init_classifications, init_db


def export_hpe_articles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    articles = conn.execute("""
        SELECT a.doi, a.title, a.journal, a.year, a.abstract,
               c.period_start, c.period_end, c.regions, c.replication_url
        FROM articles a
        JOIN classifications c ON c.doi = a.doi
        WHERE c.is_hpe = 1
        ORDER BY a.year DESC, a.title
    """).fetchall()

    if not articles:
        return []

    dois = [str(row[0]) for row in articles]
    authors_by_doi: dict[str, list[str]] = {doi: [] for doi in dois}
    for row in conn.execute(
        f"SELECT doi, given, family FROM authors"
        f" WHERE doi IN ({','.join('?' * len(dois))})"
        f" ORDER BY doi, sequence",
        dois,
    ).fetchall():
        doi, given, family = str(row[0]), row[1], row[2]
        if family and given:
            authors_by_doi[doi].append(f"{family}, {given[0]}.")
        elif family:
            authors_by_doi[doi].append(str(family))

    return [
        {
            "doi":             str(row[0]),
            "title":           row[1],
            "journal":         row[2],
            "year":            row[3],
            "abstract":        row[4],
            "period_start":    row[5],
            "period_end":      row[6],
            "regions":         json.loads(row[7] or "[]"),
            "replication_url": row[8],
            "authors":         "; ".join(authors_by_doi[str(row[0])]),
        }
        for row in articles
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export HPE dataset entries to JSON for the website."
    )
    parser.add_argument("--db",  default="articles.db", metavar="PATH")
    parser.add_argument("--out", default="docs/data.json", metavar="PATH")
    args = parser.parse_args()

    conn = init_db(args.db)
    init_classifications(conn)
    entries = export_hpe_articles(conn)
    conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    print(f"Exported {len(entries)} HPE entries to {out}.")
