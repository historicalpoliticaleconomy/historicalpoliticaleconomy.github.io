import json
import sqlite3
import tempfile
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
from hpedb.overrides import apply_overrides
from hpedb.types import ArticleRecord, ClassificationRecord

_URL = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/TEST"

_ARTICLE: ArticleRecord = {
    "doi": "10.1017/test001", "journal": "APSR",
    "title": "Colonial Institutions and Development", "year": 2020,
    "month": None, "volume": None, "issue": None, "pages": None, "abstract": None,
}

def _cls(doi: str) -> ClassificationRecord:
    return ClassificationRecord(
        doi=doi, is_hpe=True,
        period_start=1800, period_end=1900,
        regions='["Western Europe"]', countries='["Germany"]',
        backend="claude", model="claude-haiku-4-5-20251001",
        classified_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = init_db(str(tmp_path / "test.db"))
    init_classifications(c)
    yield c
    c.close()


def _write_overrides(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "overrides.json"
    p.write_text(json.dumps(data))
    return str(p)


# ── Corrections ───────────────────────────────────────────────────────────────

def test_correction_updates_regions(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": _ARTICLE["doi"], "regions": ["Eastern Europe"]}
    ], "additions": []})
    corr, adds = apply_overrides(conn, path)
    assert corr == 1 and adds == 0
    row = conn.execute("SELECT regions FROM classifications WHERE doi = ?", (_ARTICLE["doi"],)).fetchone()
    assert json.loads(row[0]) == ["Eastern Europe"]


def test_correction_skips_unknown_doi(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": "10.9999/unknown", "regions": ["Eastern Europe"]}
    ], "additions": []})
    corr, adds = apply_overrides(conn, path)
    assert corr == 0


def test_correction_only_writes_present_fields(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": _ARTICLE["doi"], "period_end": 1850}
    ], "additions": []})
    apply_overrides(conn, path)
    row = conn.execute(
        "SELECT regions, period_start, period_end FROM classifications WHERE doi = ?",
        (_ARTICLE["doi"],)
    ).fetchone()
    assert json.loads(row[0]) == ["Western Europe"]  # unchanged
    assert row[1] == 1800                              # unchanged
    assert row[2] == 1850                              # updated


def test_correction_is_hpe_false(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": _ARTICLE["doi"], "is_hpe": False}
    ], "additions": []})
    apply_overrides(conn, path)
    row = conn.execute("SELECT is_hpe FROM classifications WHERE doi = ?", (_ARTICLE["doi"],)).fetchone()
    assert row[0] == 0


def test_correction_idempotent(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": _ARTICLE["doi"], "regions": ["Northern Europe"]}
    ], "additions": []})
    apply_overrides(conn, path)
    apply_overrides(conn, path)
    row = conn.execute("SELECT regions FROM classifications WHERE doi = ?", (_ARTICLE["doi"],)).fetchone()
    assert json.loads(row[0]) == ["Northern Europe"]


# ── Additions ─────────────────────────────────────────────────────────────────

def test_addition_inserts_new_article(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [{
        "doi": "10.1017/new001", "title": "New Paper", "journal": "QJE", "year": 2022,
        "is_hpe": True, "replication_url": _URL,
        "regions": ["Western Europe"], "countries": ["France"],
        "period_start": 1750, "period_end": 1850,
    }]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 1
    row = conn.execute("SELECT title FROM articles WHERE doi = ?", ("10.1017/new001",)).fetchone()
    assert row[0] == "New Paper"
    url_row = conn.execute("SELECT replication_url FROM classifications WHERE doi = ?", ("10.1017/new001",)).fetchone()
    assert url_row[0] == _URL


def test_addition_existing_doi_overwrites(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [{
        "doi": _ARTICLE["doi"], "title": "Different Title", "journal": "QJE", "year": 2099,
        "is_hpe": True, "replication_url": _URL,
        "regions": ["Eastern Europe"], "countries": ["Poland"],
        "period_start": 1, "period_end": 2,
    }]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 1
    row = conn.execute(
        "SELECT title, regions, period_start FROM articles a JOIN classifications c ON a.doi = c.doi WHERE a.doi = ?",
        (_ARTICLE["doi"],)
    ).fetchone()
    assert row[0] == "Different Title"
    assert json.loads(row[1]) == ["Eastern Europe"]
    assert row[2] == 1


def test_addition_missing_required_field_skipped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [{
        "doi": "10.1017/incomplete", "title": "Missing Fields",
        # journal, year, is_hpe, etc. missing
    }]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 0
    assert conn.execute("SELECT 1 FROM articles WHERE doi = ?", ("10.1017/incomplete",)).fetchone() is None


def test_addition_unknown_journal_succeeds(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Unknown journal strings are accepted — journal is free-text with no FK constraint."""
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [{
        "doi": "10.1017/new999", "title": "Obscure Journal Paper",
        "journal": "Journal of Very Obscure Historical Studies",
        "year": 2021,
        "is_hpe": True, "replication_url": _URL,
        "regions": ["Western Europe"], "countries": ["France"],
        "period_start": 1750, "period_end": 1850,
    }]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 1
    row = conn.execute("SELECT journal FROM articles WHERE doi = ?", ("10.1017/new999",)).fetchone()
    assert row[0] == "Journal of Very Obscure Historical Studies"


def test_correction_for_doi_only_in_additions_is_skipped(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A correction for a paper that is in additions (but not yet in the DB) is silently skipped;
    the addition still succeeds."""
    path = _write_overrides(tmp_path, {
        "corrections": [
            {"doi": "10.1017/brand-new", "regions": ["Northern Europe"]}
        ],
        "additions": [{
            "doi": "10.1017/brand-new", "title": "Brand New Paper",
            "journal": "QJE", "year": 2022,
            "is_hpe": True, "replication_url": _URL,
            "regions": ["Western Europe"], "countries": ["France"],
            "period_start": 1750, "period_end": 1850,
        }],
    })
    corr, adds = apply_overrides(conn, path)
    # Correction is skipped (DOI not in DB at correction-apply time)
    assert corr == 0
    # Addition succeeds
    assert adds == 1
    row = conn.execute(
        "SELECT regions FROM classifications WHERE doi = ?", ("10.1017/brand-new",)
    ).fetchone()
    # regions come from the addition, not the skipped correction
    assert json.loads(row[0]) == ["Western Europe"]


# ── Uncovered branches ────────────────────────────────────────────────────────

def test_correction_missing_doi_is_skipped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [{"regions": ["Eastern Europe"]}], "additions": []})
    corr, adds = apply_overrides(conn, path)
    assert corr == 0


def test_correction_no_correctable_fields_is_noop(conn: sqlite3.Connection, tmp_path: Path) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {"corrections": [
        {"doi": _ARTICLE["doi"], "note": "No correctable field here"}
    ], "additions": []})
    corr, adds = apply_overrides(conn, path)
    assert corr == 0


def test_verbose_output_does_not_crash(conn: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    upsert_article(conn, _ARTICLE)
    upsert_classification(conn, _cls(_ARTICLE["doi"]))
    path = _write_overrides(tmp_path, {
        "corrections": [{"doi": _ARTICLE["doi"], "period_end": 1850}],
        "additions": [{
            "doi": "10.1017/verbose001", "title": "Verbose Paper", "journal": "QJE", "year": 2020,
            "is_hpe": True, "replication_url": _URL,
            "regions": ["Western Europe"], "countries": ["France"],
            "period_start": 1800, "period_end": 1900,
        }],
    })
    corr, adds = apply_overrides(conn, path, verbose=True)
    captured = capsys.readouterr()
    assert corr == 1 and adds == 1
    assert _ARTICLE["doi"] in captured.out
    assert "10.1017/verbose001" in captured.out


def test_addition_missing_doi_is_skipped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [
        {"title": "No DOI Paper", "journal": "QJE", "year": 2020,
         "is_hpe": True, "replication_url": _URL,
         "regions": ["Western Europe"], "countries": [], "period_start": 1800, "period_end": 1900}
    ]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 0


def test_addition_authors_not_list_does_not_crash(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"corrections": [], "additions": [{
        "doi": "10.1017/badauthors", "title": "Bad Authors Paper", "journal": "QJE", "year": 2020,
        "is_hpe": True, "replication_url": _URL,
        "regions": ["Western Europe"], "countries": [],
        "period_start": 1800, "period_end": 1900,
        "authors": "Smith, John",   # string, not a list
    }]})
    corr, adds = apply_overrides(conn, path)
    assert adds == 1   # addition still succeeds; authors field silently ignored
    assert conn.execute("SELECT 1 FROM articles WHERE doi = ?", ("10.1017/badauthors",)).fetchone() is not None
