import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from hpedb.db import init_classifications, init_db, upsert_article, upsert_classification
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

_ECONOMETRICA_ARTICLE: ArticleRecord = {
    "doi": "10.3982/ecta.test001", "journal": "Econometrica",
    "title": "Taxing Identity: Theory and Evidence", "year": 2021,
    "month": 3, "volume": "89", "issue": "2", "pages": "1-30", "abstract": "...",
}

_JOP_ARTICLE: ArticleRecord = {
    "doi": "10.1086/700105", "journal": "JOP",
    "title": "Elite Coalitions, Limited Government, and Fiscal Capacity Development: Evidence from Bourbon Mexico",
    "year": 2019, "month": 5, "volume": "81", "issue": "2", "pages": "1-20", "abstract": "...",
}

_UNKNOWN_JOURNAL_ARTICLE: ArticleRecord = {
    "doi": "10.9999/unknown.test001", "journal": "UNKNOWN",
    "title": "Some Article", "year": 2020,
    "month": 1, "volume": "1", "issue": "1", "pages": "1-10", "abstract": "...",
}


def _hpe_cls(doi: str) -> ClassificationRecord:
    return ClassificationRecord(
        doi=doi, is_hpe=True, period_start=1800, period_end=1900,
        regions='["Western Europe"]', backend="claude",
        model="claude-haiku-4-5-20251001", classified_at="2026-01-01T00:00:00+00:00",
    )


def _make_conn(tmp_path: Path, articles: list[ArticleRecord]) -> sqlite3.Connection:
    c = init_db(str(tmp_path / "test.db"))
    init_classifications(c)
    for a in articles:
        upsert_article(c, a)
        upsert_classification(c, _hpe_cls(a["doi"]))
    return c


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = _make_conn(tmp_path, [_APSR_ARTICLE])
    yield c
    c.close()


@pytest.fixture
def aer_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = _make_conn(tmp_path, [_AER_ARTICLE])
    yield c
    c.close()


@pytest.fixture
def econometrica_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = _make_conn(tmp_path, [_ECONOMETRICA_ARTICLE])
    yield c
    c.close()


@pytest.fixture
def jop_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = _make_conn(tmp_path, [_JOP_ARTICLE])
    yield c
    c.close()


def _mock_dataverse(items: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": {"items": items}}
    return resp


def _mock_crossref(refs: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"message": {"reference": refs}}
    return resp


def _crossref_ref(repo_doi: str, title: str = "Replication Data") -> dict[str, Any]:
    return {"unstructured": f'{title}. https://doi.org/{repo_doi}.'}


def _mock_zenodo(hits: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"hits": {"hits": hits, "total": len(hits)}}
    return resp


def _mock_es_page(has_data: bool, url: str = "https://www.econometricsociety.org/publications/econometrica/2021/03/01/test") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.url = url
    resp.text = '<a href="data-supplement.zip">Data Supplement</a>' if has_data else "<p>No data.</p>"
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


def _first_call_params(mock_session: MagicMock) -> dict[str, str]:
    first = mock_session.get.call_args_list[0]
    return first[1]["params"] if first[1] else first[0][1]


def _last_call_params(mock_session: MagicMock) -> dict[str, str]:
    last = mock_session.get.call_args
    return last[1]["params"] if last[1] else last[0][1]


def test_enrich_query_uses_publication_id_field(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_dataverse([])
    enrich_replication_urls(conn)
    assert _first_call_params(mock_session)["q"] == f'publicationIDNumber:"{_APSR_ARTICLE["doi"]}"'


def test_enrich_query_includes_subtree_for_known_journals(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_dataverse([])
    enrich_replication_urls(conn)
    assert _first_call_params(mock_session)["subtree"] == "the_review"  # APSR maps to "the_review"


def test_enrich_fulltext_fallback_when_field_query_empty(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XYZ"
    # First call (publicationIDNumber) returns nothing; second (full-text fallback) returns a hit
    mock_session.get.side_effect = [_mock_dataverse([]), _mock_dataverse([{"url": url}])]
    found, total = enrich_replication_urls(conn)
    assert found == 1
    assert mock_session.get.call_count == 2
    fallback_params = _last_call_params(mock_session)
    assert fallback_params["q"] == f'"{_APSR_ARTICLE["doi"]}"'
    assert fallback_params["subtree"] == "the_review"


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


def test_enrich_skips_unconfigured_journals(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    upsert_article(conn, _UNKNOWN_JOURNAL_ARTICLE)
    upsert_classification(conn, _hpe_cls(_UNKNOWN_JOURNAL_ARTICLE["doi"]))
    mock_session.get.return_value = _mock_dataverse([{"url": "some_url"}])
    found, total = enrich_replication_urls(conn)
    assert total == 2
    # UNKNOWN journal has no source configured; only 1 GET attempted (for APSR)
    assert mock_session.get.call_count == 1
    assert found == 1


def test_enrich_aer_found(aer_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    icpsr_doi = "10.3886/E199265V1"
    mock_session.get.return_value = _mock_crossref([_crossref_ref(icpsr_doi)])
    found, total = enrich_replication_urls(aer_conn)
    assert total == 1
    assert found == 1
    row = aer_conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_AER_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == f"https://doi.org/{icpsr_doi}"


def test_enrich_crossref_hits_correct_endpoint(aer_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_crossref([])
    enrich_replication_urls(aer_conn)
    url_called = mock_session.get.call_args[0][0]
    assert url_called == f"https://api.crossref.org/works/{_AER_ARTICLE['doi']}"


def test_enrich_crossref_disambiguates_by_title(aer_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    own_doi   = "10.3886/E199265V1"
    other_doi = "10.3886/E161342V1"
    refs = [
        _crossref_ref(own_doi,   "Replication Data for: Slavery and Economic Development"),
        _crossref_ref(other_doi, "Replication Data for: Boomtowns: Local Shocks"),
    ]
    mock_session.get.return_value = _mock_crossref(refs)
    found, _ = enrich_replication_urls(aer_conn)
    assert found == 1
    row = aer_conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_AER_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == f"https://doi.org/{own_doi}"


def test_enrich_crossref_no_deposit_returns_nothing(aer_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.return_value = _mock_crossref([])
    found, _ = enrich_replication_urls(aer_conn)
    assert found == 0


def test_enrich_crossref_fallback_used_for_dataverse_journal(
    conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    dvn_doi = "10.7910/DVN/ABCDEF"
    # Dataverse finds nothing; Crossref fallback finds a DVN DOI in references
    mock_session.get.side_effect = [
        _mock_dataverse([]),                      # step 1: publicationIDNumber
        _mock_dataverse([]),                      # step 2: full-text DOI
        _mock_dataverse([]),                      # step 3: title
        _mock_crossref([_crossref_ref(dvn_doi)]), # Crossref fallback
    ]
    found, _ = enrich_replication_urls(conn)
    assert found == 1
    row = conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_APSR_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == f"https://doi.org/{dvn_doi}"


def test_enrich_econometrica_found(econometrica_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://zenodo.org/records/1234567"
    mock_session.get.return_value = _mock_zenodo([{
        "links": {"html": url},
        "metadata": {"title": "Replication: Taxing Identity"},
    }])
    found, total = enrich_replication_urls(econometrica_conn)
    assert total == 1
    assert found == 1
    row = econometrica_conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_ECONOMETRICA_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == url


def test_enrich_zenodo_field_query_uses_related_identifier(
    econometrica_conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    mock_session.get.side_effect = [
        _mock_zenodo([]),       # field query: no hits
        _mock_zenodo([]),       # full-text fallback: no hits
        _mock_es_page(False),   # ES page fallback: no data link
        _mock_crossref([]),     # Crossref fallback: no refs
    ]
    enrich_replication_urls(econometrica_conn)
    first_params = mock_session.get.call_args_list[0][1]["params"]
    assert first_params["q"] == f'related.identifier:"{_ECONOMETRICA_ARTICLE["doi"]}"'
    assert first_params["communities"] == "es-replication-repository"


def test_enrich_zenodo_fulltext_fallback(
    econometrica_conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    url = "https://zenodo.org/records/9999999"
    mock_session.get.side_effect = [
        _mock_zenodo([]),  # field query: no hits
        _mock_zenodo([{"links": {"html": url}, "metadata": {"title": "T"}}]),  # full-text: one hit
        # ES page never reached because Zenodo succeeded
    ]
    found, total = enrich_replication_urls(econometrica_conn)
    assert found == 1
    assert mock_session.get.call_count == 2
    fallback_params = mock_session.get.call_args_list[1][1]["params"]
    assert fallback_params["q"] == f'"{_ECONOMETRICA_ARTICLE["doi"]}"'


def test_enrich_es_page_fallback_found(econometrica_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    es_url = "https://www.econometricsociety.org/publications/econometrica/2021/03/01/test"
    mock_session.get.side_effect = [
        _mock_zenodo([]),           # Zenodo field query: no hits
        _mock_zenodo([]),           # Zenodo full-text fallback: no hits
        _mock_es_page(True, es_url),  # ES page: zip link found
    ]
    found, total = enrich_replication_urls(econometrica_conn)
    assert found == 1
    row = econometrica_conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_ECONOMETRICA_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == es_url


def test_enrich_es_page_fallback_no_data(econometrica_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    mock_session.get.side_effect = [
        _mock_zenodo([]),
        _mock_zenodo([]),
        _mock_es_page(False),
        _mock_crossref([]),  # Crossref fallback also finds nothing
    ]
    found, total = enrich_replication_urls(econometrica_conn)
    assert found == 0


def test_enrich_es_page_not_tried_when_zenodo_found(
    econometrica_conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    zenodo_url = "https://zenodo.org/records/1234567"
    mock_session.get.return_value = _mock_zenodo([{
        "links": {"html": zenodo_url},
        "metadata": {"title": "T"},
    }])
    found, _ = enrich_replication_urls(econometrica_conn)
    assert found == 1
    assert mock_session.get.call_count == 1  # only Zenodo field query, ES never reached


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


def test_enrich_title_fallback_found(jop_conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/ABCDEF"
    # JOP has subtree=None so step 2 (DOI full-text) is skipped; step 1 empty → step 3 (title)
    mock_session.get.side_effect = [
        _mock_dataverse([]),               # step 1: publicationIDNumber query, no hits
        _mock_dataverse([{"url": url}]),   # step 3: title query, one hit
    ]
    found, total = enrich_replication_urls(jop_conn)
    assert found == 1
    assert mock_session.get.call_count == 2
    row = jop_conn.execute(
        "SELECT replication_url FROM classifications WHERE doi = ?",
        (_JOP_ARTICLE["doi"],),
    ).fetchone()
    assert row[0] == url


def test_enrich_title_fallback_query_uses_article_title(
    jop_conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    mock_session.get.side_effect = [
        _mock_dataverse([]),  # step 1: publicationIDNumber
        _mock_dataverse([]),  # step 3: title (step 2 skipped — JOP has subtree=None)
        _mock_crossref([]),   # Crossref fallback
    ]
    enrich_replication_urls(jop_conn)
    title_params = mock_session.get.call_args_list[1][1]["params"]
    assert title_params["q"] == f'"{_JOP_ARTICLE["title"]}"'


def test_enrich_title_fallback_not_tried_when_doi_found(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XYZ"
    # APSR step 1 returns a hit — title fallback should never be reached
    mock_session.get.return_value = _mock_dataverse([{"url": url}])
    found, _ = enrich_replication_urls(conn)
    assert found == 1
    assert mock_session.get.call_count == 1


def test_enrich_title_fallback_not_tried_when_doi_ambiguous(
    jop_conn: sqlite3.Connection, mock_session: MagicMock
) -> None:
    # Step 1 returns 2 results (ambiguous) — title skipped, Crossref fallback runs
    mock_session.get.side_effect = [
        _mock_dataverse([{"url": "a"}, {"url": "b"}]),  # step 1: ambiguous
        _mock_crossref([]),                              # Crossref fallback
    ]
    found, _ = enrich_replication_urls(jop_conn)
    assert found == 0
    assert mock_session.get.call_count == 2


def test_enrich_api_error_skipped(conn: sqlite3.Connection, mock_session: MagicMock) -> None:
    error_resp = MagicMock()
    error_resp.status_code = 500
    mock_session.get.return_value = error_resp
    found, total = enrich_replication_urls(conn)
    assert found == 0
    assert total == 1
