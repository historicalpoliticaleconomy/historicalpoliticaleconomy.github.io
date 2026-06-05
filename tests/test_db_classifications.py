"""
Validation tests against the committed articles.db.

These tests check that well-known papers are classified correctly. They are
expected to fail until the database is reclassified with:

    poetry run hpedb-classify --backend claude --fresh

Individual tests are skipped if the paper is not present in the database
(e.g. because of a different --from-year fetch range).

Run only these tests with:  pytest -m db
Exclude them with:          pytest -m "not db"
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from hpedb.db import init_classifications

DB_PATH = Path(__file__).parent.parent / "articles.db"


def _classification(doi: str) -> dict[str, Any] | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    init_classifications(conn)  # applies any pending schema migrations
    row = conn.execute(
        "SELECT is_hpe, regions, countries, period_start, period_end "
        "FROM classifications WHERE doi = ?",
        (doi,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "is_hpe":       bool(row[0]),
        "regions":      json.loads(row[1] or "[]"),
        "countries":    json.loads(row[2] or "[]"),
        "period_start": row[3],
        "period_end":   row[4],
    }


def _require(doi: str) -> dict[str, Any]:
    c = _classification(doi)
    if c is None:
        pytest.skip(f"{doi} not in database")
    return c


# ── Definite HPE — direct historical study ───────────────────────────────────

@pytest.mark.db
def test_merchant_towns_is_hpe() -> None:
    # Blaydes & Paik (2022), AER — Norman Conquest of England to Great Reform Act
    assert _require("10.1257/aer.20200885")["is_hpe"] is True

@pytest.mark.db
def test_merchant_towns_region_and_country() -> None:
    c = _require("10.1257/aer.20200885")
    assert "Northern Europe" in c["regions"]   # UK is UN M.49 Northern Europe
    assert "United Kingdom" in c["countries"]
    assert len(c["regions"]) == 1
    assert len(c["countries"]) == 1

@pytest.mark.db
def test_merchant_towns_period() -> None:
    c = _require("10.1257/aer.20200885")
    assert c["period_start"] is not None and int(str(c["period_start"])) <= 1066
    assert c["period_end"] is not None and int(str(c["period_end"])) >= 1832

@pytest.mark.db
def test_protestant_reformation_is_hpe() -> None:
    # Cantoni, Dittmar & Yuchtman (2018), QJE — religious competition in the Reformation
    assert _require("10.1093/qje/qjy011")["is_hpe"] is True

@pytest.mark.db
def test_protestant_reformation_region_and_country() -> None:
    c = _require("10.1093/qje/qjy011")
    assert "Western Europe" in c["regions"]
    assert "Germany" in c["countries"]

@pytest.mark.db
def test_great_reform_act_is_hpe() -> None:
    # Aidt & Franck (2015), Econometrica — Great Reform Act of 1832
    assert _require("10.3982/ecta11484")["is_hpe"] is True

@pytest.mark.db
def test_great_reform_act_region_and_country() -> None:
    c = _require("10.3982/ecta11484")
    assert "Northern Europe" in c["regions"]   # UK is UN M.49 Northern Europe
    assert "United Kingdom" in c["countries"]


# ── Definite HPE — persistence papers ────────────────────────────────────────

@pytest.mark.db
def test_women_and_plough_is_hpe() -> None:
    # Alesina, Giuliano & Nunn (2013), QJE — historical plough use and gender roles
    assert _require("10.1093/qje/qjt005")["is_hpe"] is True

@pytest.mark.db
def test_the_mission_is_hpe() -> None:
    # Valencia (2019), QJE — Jesuit missions and human capital persistence in South America
    assert _require("10.1093/qje/qjy024")["is_hpe"] is True

@pytest.mark.db
def test_the_mission_region() -> None:
    c = _require("10.1093/qje/qjy024")
    assert "South America" in c["regions"]

@pytest.mark.db
def test_jim_crow_is_hpe() -> None:
    # Shertzer et al. (2024), QJE — Jim Crow laws and Black economic progress after slavery
    assert _require("10.1093/qje/qjae023")["is_hpe"] is True

@pytest.mark.db
def test_jim_crow_region_and_country() -> None:
    c = _require("10.1093/qje/qjae023")
    assert "Northern America" in c["regions"]
    assert "United States" in c["countries"]
    assert len(c["regions"]) == 1
    assert len(c["countries"]) == 1


# ── Definite NOT HPE ─────────────────────────────────────────────────────────

@pytest.mark.db
def test_democracy_by_mistake_not_hpe() -> None:
    # Treisman (2020), APSR — uses historical cases to argue autocrats generally
    # miscalculate; the historical specificity is illustrative, not load-bearing.
    assert _require("10.1017/s0003055420000180")["is_hpe"] is False

@pytest.mark.db
def test_emissions_passthrough_not_hpe() -> None:
    # Fabra & Reguant (2014), AER — electricity market emissions pass-through
    assert _require("10.1257/aer.104.9.2872")["is_hpe"] is False

@pytest.mark.db
def test_randomizing_religion_not_hpe() -> None:
    # Clingingsmith, Khwaja & Kremer (2020), QJE — RCT (hajj lottery), not historical analysis
    assert _require("10.1093/qje/qjaa023")["is_hpe"] is False

@pytest.mark.db
def test_school_admissions_mechanism_not_hpe() -> None:
    # Pathak & Sonmez (2013), AER — mechanism design for school admissions
    assert _require("10.1257/aer.103.1.80")["is_hpe"] is False

@pytest.mark.db
def test_monetary_transmission_not_hpe() -> None:
    # Lenel (2013), AER — lemons markets and aggregate shock transmission
    assert _require("10.1257/aer.103.4.1463")["is_hpe"] is False
