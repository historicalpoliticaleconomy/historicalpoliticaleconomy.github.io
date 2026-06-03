import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from hpedb.db import (
    init_classifications,
    init_db,
    upsert_article,
    upsert_classification,
)
from hpedb.enrich import enrich_replication_urls
from hpedb.types import ArticleRecord, ClassificationRecord

_APSR_ARTICLE: ArticleRecord = {
    "doi": "10.1017/test001", "journal": "APSR",
    "title": "Colonial Institutions and State Capacity", "year": 2019,
    "month": 5, "volume": "113", "issue": "3", "pages": "1-30", "abstract": "...",
}

_AER_ARTICLE: ArticleRecord = {
    "doi": "10.1257/aer.test001", "journal": "AER",
    "title": "Slavery and Economic Development", "year": 2020,
    "month": 6, "volume": "110", "issue": "6", "pages": "1-40", "abstract": "...",
}


def _hpe_cls(doi: str) -> ClassificationRecord:
    return ClassificationRecord(
        doi=doi, is_hpe=True, period_start=1800, period_end=1900,
        regions='["Western Europe"]', backend="claude",
        model="claude-haiku-4-5-20251001", classified_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = init_db(str(tmp_path / "test.db"))
    init_classifications(c)
    upsert_article(c, _APSR_ARTICLE)
    upsert_classification(c, _hpe_cls(_APSR_ARTICLE["doi"]))
    yield c
    c.close()


def _mock_dataverse(items: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": {"items": items}}
    return resp


@pytest.fixture
def mock_session() -> Generator[MagicMock, None, None]:
    with patch("hpedb.enrich.requests.Session") as MockSession, \
         patch("hpedb.enrich.time.sleep"):
        session = MagicMock()
        MockSession.return_value.__enter__.return_value = session
        yield session


def test_enrich_found_one_result(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XYZ"
    mock_session.get.return_value = _mock_dataverse([{"url": url}])
    found, total = enrich_replication_urls(conn)
    assert found == 1
    assert total == 1
    row = conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_APSR_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == url


def test_enrich_no_results(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_dataverse([])
    found, total = enrich_replication_urls(conn)
    assert found == 0
    assert total == 1


def test_enrich_multiple_results_skipped(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_dataverse([{"url": "a"}, {"url": "b"}])
    found, total = enrich_replication_urls(conn)
    assert found == 0
    row = conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_APSR_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] is None


def test_enrich_dry_run_does_not_write(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XYZ"
    mock_session.get.return_value = _mock_dataverse([{"url": url}])
    found, _ = enrich_replication_urls(conn, dry_run=True)
    assert found == 1
    row = conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_APSR_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] is None


def test_enrich_skips_non_dataverse_journals(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    upsert_article(conn, _AER_ARTICLE)
    upsert_classification(conn, _hpe_cls(_AER_ARTICLE["doi"]))
    mock_session.get.return_value = _mock_dataverse([{"url": "some_url"}])
    found, total = enrich_replication_urls(conn)
    assert total == 2
    # AER is not in _DATAVERSE_SUBTREE so only 1 GET was attempted (for APSR)
    assert mock_session.get.call_count == 1
    assert found == 1


def test_enrich_skips_already_enriched(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    existing_url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/ALREADY"
    conn.execute(
        "UPDATE classifications SET replication_url = ? WHERE doi = ?",
        (existing_url, _APSR_ARTICLE["doi"]),
    )
    conn.commit()
    mock_session.get.return_value = _mock_dataverse([{"url": "new_url"}])
    found, total = enrich_replication_urls(conn)
    # Nothing queued because replication_url is already set
    assert total == 0
    assert found == 0
    assert mock_session.get.call_count == 0


def test_enrich_fresh_re_enriches(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    existing_url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/OLD"
    conn.execute(
        "UPDATE classifications SET replication_url = ? WHERE doi = ?",
        (existing_url, _APSR_ARTICLE["doi"]),
    )
    conn.commit()
    new_url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/NEW"
    mock_session.get.return_value = _mock_dataverse([{"url": new_url}])
    found, total = enrich_replication_urls(conn, fresh=True)
    assert total == 1
    assert found == 1
    row = conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_APSR_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == new_url


def test_enrich_api_error_skipped(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    error_resp = MagicMock()
    error_resp.status_code = 500
    mock_session.get.return_value = error_resp
    found, total = enrich_replication_urls(conn)
    assert found == 0
    assert total == 1
