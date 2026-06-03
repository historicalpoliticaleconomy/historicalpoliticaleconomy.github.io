import argparse
import sqlite3
import time
from typing import Any

import requests

from hpedb.db import init_classifications, init_db, update_replication_url

_DATAVERSE_BASE = "https://dataverse.harvard.edu/api/search"

# Harvard Dataverse collection aliases per journal (None = global search)
_DATAVERSE_SUBTREE: dict[str, str | None] = {
    "APSR": "the_review",
    "AJPS": "ajps",
    "QJE":  "qje",
    "JOP":  None,
    "JPE":  None,
}

_RATE_LIMIT_PAUSE = 1.0


def _lookup_dataverse(doi: str, subtree: str | None, session: requests.Session) -> str | None:
    params: dict[str, Any] = {"q": doi, "type": "dataset", "per_page": "5"}
    if subtree is not None:
        params["subtree"] = subtree
    try:
        resp = session.get(_DATAVERSE_BASE, params=params, timeout=15)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    items: list[dict[str, Any]] = resp.json().get("data", {}).get("items", [])
    return str(items[0]["url"]) if len(items) == 1 and "url" in items[0] else None


def enrich_replication_urls(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    fresh: bool = False,
) -> tuple[int, int]:
    where = (
        "c.is_hpe = 1"
        if fresh
        else "c.is_hpe = 1 AND c.replication_url IS NULL"
    )
    rows: list[tuple[str, str]] = [
        (str(r[0]), str(r[1]))
        for r in conn.execute(
            f"SELECT a.doi, a.journal FROM articles a JOIN classifications c ON c.doi = a.doi WHERE {where}"
        ).fetchall()
    ]

    found = 0
    with requests.Session() as session:
        for doi, journal in rows:
            if journal not in _DATAVERSE_SUBTREE:
                time.sleep(_RATE_LIMIT_PAUSE)
                continue
            url = _lookup_dataverse(doi, _DATAVERSE_SUBTREE[journal], session)
            if url is not None:
                found += 1
                if dry_run:
                    print(f"  [{doi}] {url}")
                else:
                    update_replication_url(conn, doi, url)
            time.sleep(_RATE_LIMIT_PAUSE)

    return found, len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich HPE classifications with replication dataset URLs."
    )
    parser.add_argument("--db",      default="articles.db", metavar="PATH")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print found URLs without writing to DB")
    parser.add_argument("--fresh",   action="store_true",
                        help="Re-lookup all HPE articles, not just those missing a URL")
    args = parser.parse_args()

    conn = init_db(args.db)
    init_classifications(conn)
    print("Enriching replication URLs from Harvard Dataverse...")
    found, total = enrich_replication_urls(conn, dry_run=args.dry_run, fresh=args.fresh)
    conn.close()
    print(f"\nDone. Found replication URLs for {found}/{total} HPE articles.")
    if total > found:
        print(
            f"  Note: AER (openICPSR) and Econometrica (Zenodo) links require manual lookup."
        )
