"""
End-to-end tests that exercise the full pipeline through the CLI entry points.
Run with: pytest -m e2e
Skip with: pytest -m "not e2e"
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from hpedb.cli import main as cli_main
from hpedb.supplement import main as supplement_main

# Well-known stable DOIs (Crossref normalises DOIs to lowercase)
KNOWN_JOP_DOI = "10.1086/706765"
KNOWN_APSR_DOI = "10.1017/s0003055420000234"

_MAILTO = "hmm2198@columbia.edu"


def _cli_argv(db_path: str, from_year: int = 2020, to_year: int = 2020) -> list[str]:
    return [
        "hpedb",
        "--from-year", str(from_year),
        "--to-year", str(to_year),
        "--mailto", _MAILTO,
        "--db", db_path,
    ]


@pytest.mark.e2e
def test_fetch_pipeline(tmp_path: Path) -> None:
    """hpedb CLI fetches all three journals and stores well-formed articles."""
    db_path = str(tmp_path / "fetch.db")
    with patch("sys.argv", _cli_argv(db_path)):
        cli_main()

    conn = sqlite3.connect(db_path)

    counts = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT journal, COUNT(*) FROM articles GROUP BY journal"
        ).fetchall()
    }
    jop_doi = conn.execute(
        "SELECT doi, title, year FROM articles WHERE doi=?", (KNOWN_JOP_DOI,)
    ).fetchone()
    apsr_doi = conn.execute(
        "SELECT doi, title FROM articles WHERE doi=?", (KNOWN_APSR_DOI,)
    ).fetchone()
    jop_abstract_count = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE journal='JOP' AND abstract IS NOT NULL"
    ).fetchone()[0]
    author_count = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]

    conn.close()

    # All three journals populated
    assert counts.get("JOP", 0) > 50
    assert counts.get("APSR", 0) > 50
    assert counts.get("AJPS", 0) > 50

    # Known anchor articles are present with required fields
    assert jop_doi is not None, f"{KNOWN_JOP_DOI} not found"
    assert jop_doi[2] == 2020
    assert jop_doi[1] is not None

    assert apsr_doi is not None, f"{KNOWN_APSR_DOI} not found"
    assert apsr_doi[1] is not None

    # JOP deposits no abstracts with Crossref — validates supplement is needed
    assert jop_abstract_count == 0

    # Authors table is populated
    assert author_count > 0


@pytest.mark.e2e
def test_supplement_pipeline(tmp_path: Path) -> None:
    """hpedb then hpedb-supplement fills JOP abstracts via Semantic Scholar."""
    db_path = str(tmp_path / "supplement.db")

    with patch("sys.argv", _cli_argv(db_path)):
        cli_main()

    with patch("sys.argv", ["hpedb-supplement", "--db", db_path]):
        supplement_main()

    conn = sqlite3.connect(db_path)
    jop_with_abstract = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE journal='JOP' AND abstract IS NOT NULL"
    ).fetchone()[0]
    apsr_with_abstract = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE journal='APSR' AND abstract IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    assert jop_with_abstract > 0, "Semantic Scholar should have provided JOP abstracts"
    # APSR already had abstracts from Crossref; supplement should not have overwritten them
    assert apsr_with_abstract > 0
