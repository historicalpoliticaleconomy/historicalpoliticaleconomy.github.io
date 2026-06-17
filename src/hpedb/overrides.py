import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite3

from hpedb.db import (
    init_classifications,
    init_db,
    update_replication_url,
    upsert_article,
    upsert_authors,
    upsert_classification,
)
from hpedb.types import ArticleRecord, AuthorRecord, ClassificationRecord

# Correctable columns, split by the table they live in. Corrections to existing
# records touch classifications, articles, and the authors table independently.
_CLASS_CORRECTION_FIELDS = frozenset(
    {
        "is_hpe",
        "period_start",
        "period_end",
        "regions",
        "countries",
        "replication_url",
    }
)
_ARTICLE_CORRECTION_FIELDS = frozenset({"title", "year", "abstract"})


def _update_row(
    conn: sqlite3.Connection, table: str, updates: dict[str, Any], doi: str
) -> None:
    """UPDATE `table` SET col = ? ... WHERE doi = ?. `table` is a trusted literal."""
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE {table} SET {sets} WHERE doi = ?",
        list(updates.values()) + [doi],
    )


# Minimal gate: a dataset may be posted online with no associated journal/paper, so
# everything except a stable identifier, a title, and a data link is optional and
# defaulted below (journal -> placeholder; is_hpe -> True; regions/countries -> []).
_REQUIRED_ARTICLE = frozenset({"doi", "title"})
_REQUIRED_CLASS = frozenset({"replication_url"})

# articles.journal is NOT NULL; stand in for additions that carry no journal.
_MISSING_JOURNAL = "Unpublished"


def apply_overrides(
    conn: sqlite3.Connection,
    overrides_path: str,
    verbose: bool = False,
) -> tuple[int, int]:
    data: dict[str, Any] = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
    corrections_applied = 0
    additions_applied = 0

    # ── Corrections ────────────────────────────────────────────────────────────
    for corr in data.get("corrections", []):
        doi = corr.get("doi")
        if not doi:
            print("  Warning: correction entry missing 'doi', skipping")
            continue
        if not conn.execute(
            "SELECT 1 FROM classifications WHERE doi = ?", (doi,)
        ).fetchone():
            print(f"  Warning: {doi} not in database, skipping correction")
            continue

        class_updates = {k: v for k, v in corr.items() if k in _CLASS_CORRECTION_FIELDS}
        for lf in ("regions", "countries"):
            if lf in class_updates and isinstance(class_updates[lf], list):
                class_updates[lf] = json.dumps(class_updates[lf])
        if "is_hpe" in class_updates:
            class_updates["is_hpe"] = int(bool(class_updates["is_hpe"]))

        article_updates = {
            k: v for k, v in corr.items() if k in _ARTICLE_CORRECTION_FIELDS
        }

        # A full author list replaces the existing one; an empty list is not a correction.
        new_authors = corr.get("authors")
        replace_authors = isinstance(new_authors, list) and bool(new_authors)

        if not (class_updates or article_updates or replace_authors):
            continue

        if class_updates:
            _update_row(conn, "classifications", class_updates, doi)
        if article_updates:
            _update_row(conn, "articles", article_updates, doi)
        if replace_authors:
            upsert_authors(
                conn,
                doi,
                [
                    AuthorRecord(
                        sequence=i,
                        given=a.get("given"),
                        family=a.get("family"),
                    )
                    for i, a in enumerate(new_authors)
                ],
            )

        corrections_applied += 1
        if verbose:
            print(f"  Corrected: {doi}")

    # ── Additions ──────────────────────────────────────────────────────────────
    for add in data.get("additions", []):
        doi = add.get("doi")
        if not doi:
            print("  Error: addition entry missing 'doi', skipping")
            continue

        missing_fields = (_REQUIRED_ARTICLE | _REQUIRED_CLASS) - set(add.keys())
        if missing_fields:
            print(
                f"  Error: {doi} missing required fields: {sorted(missing_fields)}, skipping"
            )
            continue

        upsert_article(
            conn,
            ArticleRecord(
                doi=doi,
                journal=add.get("journal") or _MISSING_JOURNAL,
                title=add.get("title"),
                year=add.get("year"),
                month=None,
                volume=None,
                issue=None,
                pages=None,
                abstract=add.get("abstract"),
            ),
        )

        if "authors" in add and isinstance(add["authors"], list):
            upsert_authors(
                conn,
                doi,
                [
                    AuthorRecord(
                        sequence=i,
                        given=a.get("given"),
                        family=a.get("family"),
                    )
                    for i, a in enumerate(add["authors"])
                ],
            )

        upsert_classification(
            conn,
            ClassificationRecord(
                doi=doi,
                is_hpe=bool(add.get("is_hpe", True)),
                period_start=add.get("period_start"),
                period_end=add.get("period_end"),
                regions=json.dumps(add.get("regions", [])),
                countries=json.dumps(add.get("countries", [])),
                backend="manual",
                model="override",
                classified_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
        # upsert_classification uses INSERT OR REPLACE and doesn't include replication_url;
        # set it explicitly after so it's always applied correctly.
        update_replication_url(conn, doi, add["replication_url"])

        additions_applied += 1
        if verbose:
            print(f"  Added: {doi}")

    conn.commit()
    return corrections_applied, additions_applied


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply manual corrections and additions from an overrides JSON file."
    )
    parser.add_argument("overrides", metavar="PATH", help="Path to overrides.json")
    parser.add_argument("--db", default="articles.db", metavar="PATH")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    conn = init_db(args.db)
    init_classifications(conn)
    corr, adds = apply_overrides(conn, args.overrides, verbose=args.verbose)
    conn.close()
    print(f"Applied {corr} correction(s), {adds} addition(s).")
