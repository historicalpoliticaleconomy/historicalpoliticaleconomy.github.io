import argparse
import datetime
import time

from hpedb.db import init_db, wipe_db, upsert_article, upsert_authors
from hpedb.fetch import JOURNALS, make_client, fetch_journal


def main() -> None:
    current_year = datetime.date.today().year

    parser = argparse.ArgumentParser(
        description="Fetch political science journal article metadata into SQLite."
    )
    parser.add_argument(
        "--from-year",
        type=int,
        required=True,
        metavar="YEAR",
        help="Earliest publication year to include (inclusive)",
    )
    parser.add_argument(
        "--to-year",
        type=int,
        default=current_year,
        metavar="YEAR",
        help=f"Latest publication year to include (inclusive, default: {current_year})",
    )
    parser.add_argument(
        "--db",
        default="articles.db",
        metavar="PATH",
        help="Path to the SQLite database file (default: articles.db)",
    )
    parser.add_argument(
        "--mailto",
        required=True,
        metavar="EMAIL",
        help="Email address for Crossref polite pool access",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Wipe the database before fetching (default: upsert into existing DB)",
    )
    args = parser.parse_args()

    conn = init_db(args.db)
    if args.fresh:
        print("--fresh: wiping existing data.")
        wipe_db(conn)

    cr = make_client(args.mailto)

    for abbrev, issn in JOURNALS.items():
        print(f"\nFetching {abbrev} ({args.from_year}–{args.to_year})...")
        rows = fetch_journal(cr, abbrev, issn, args.from_year, args.to_year)
        for article, authors in rows:
            upsert_article(conn, article)
            upsert_authors(conn, article["doi"], authors)
        print(f"  {abbrev}: {len(rows)} articles stored.")
        time.sleep(1)

    conn.close()
    print("\nDone.")
