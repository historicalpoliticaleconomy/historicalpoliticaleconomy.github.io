import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
import requests

from hpedb.db import init_db, upsert_article, upsert_authors
from hpedb.supplement import _MAX_RETRIES, _fetch_batch_chunk, main, supplement_abstracts
from hpedb.types import ArticleRecord, AuthorRecord

ARTICLE_NO_ABSTRACT: ArticleRecord = {
    "doi": "10.1086/000001",
    "journal": "JOP",
    "title": "A Title",
    "year": 2022,
    "month": 1,
    "volume": "84",
    "issue": "1",
    "pages": "1-10",
    "abstract": None,
}

ARTICLE_HAS_ABSTRACT: ArticleRecord = {
    "doi": "10.1086/000002",
    "journal": "JOP",
    "title": "Another Title",
    "year": 2022,
    "month": 1,
    "volume": "84",
    "issue": "1",
    "pages": "11-20",
    "abstract": "Already here.",
}

AUTHOR: AuthorRecord = {"sequence": 0, "given": "Jane", "family": "Doe"}


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = init_db(str(tmp_path / "test.db"))
    for article in (ARTICLE_NO_ABSTRACT, ARTICLE_HAS_ABSTRACT):
        upsert_article(c, article)
        upsert_authors(c, article["doi"], [AUTHOR])
    yield c
    c.close()


def _mock_session(status_code: int, body: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    session = MagicMock()
    session.post.return_value = resp
    return session


def test_fetch_batch_chunk_success() -> None:
    dois = ["10.1086/000001", "10.1086/000002"]
    body = [{"abstract": "First abstract."}, {"abstract": "Second abstract."}]
    session = _mock_session(200, body)
    result = _fetch_batch_chunk(dois, session)
    assert result == {
        "10.1086/000001": "First abstract.",
        "10.1086/000002": "Second abstract.",
    }


def test_fetch_batch_chunk_missing_paper() -> None:
    dois = ["10.1086/000001", "10.1086/000002"]
    body = [None, {"abstract": "Found."}]
    session = _mock_session(200, body)
    result = _fetch_batch_chunk(dois, session)
    assert result == {"10.1086/000002": "Found."}


def test_fetch_batch_chunk_empty_abstract_excluded() -> None:
    dois = ["10.1086/000001"]
    body = [{"abstract": ""}]
    session = _mock_session(200, body)
    assert _fetch_batch_chunk(dois, session) == {}


def test_fetch_batch_chunk_no_abstract_field_excluded() -> None:
    dois = ["10.1086/000001"]
    body: list[dict[str, Any]] = [{}]
    session = _mock_session(200, body)
    assert _fetch_batch_chunk(dois, session) == {}


def test_fetch_batch_chunk_rate_limit_then_success() -> None:
    dois = ["10.1086/000001"]
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = [{"abstract": "Retry worked."}]
    session = MagicMock()
    session.post.side_effect = [resp_429, resp_200]

    with patch("hpedb.supplement.time.sleep") as mock_sleep:
        result = _fetch_batch_chunk(dois, session)

    assert result == {"10.1086/000001": "Retry worked."}
    mock_sleep.assert_called_once_with(60)  # attempt 0: 60 * 2^0


def test_fetch_batch_chunk_exponential_backoff() -> None:
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = [{"abstract": "Eventually."}]
    session = MagicMock()
    session.post.side_effect = [resp_429, resp_429, resp_200]

    with patch("hpedb.supplement.time.sleep") as mock_sleep:
        _fetch_batch_chunk(["10.1086/000001"], session)

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [60, 120]  # 60 * 2^0, 60 * 2^1


def test_fetch_batch_chunk_persistent_rate_limit_raises() -> None:
    session: MagicMock = _mock_session(429)
    with patch("hpedb.supplement.time.sleep"):
        with pytest.raises(RuntimeError, match="429"):
            _fetch_batch_chunk(["10.1086/000001"], session)


def test_fetch_batch_chunk_server_error_retries_then_raises() -> None:
    session: MagicMock = _mock_session(500)
    with patch("hpedb.supplement.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="500"):
            _fetch_batch_chunk(["10.1086/000001"], session)
    assert mock_sleep.call_count == _MAX_RETRIES - 1


def test_fetch_batch_chunk_server_error_retries_then_succeeds() -> None:
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = [{"abstract": "Recovered."}]
    session = MagicMock()
    session.post.side_effect = [resp_500, resp_200]

    with patch("hpedb.supplement.time.sleep"):
        result = _fetch_batch_chunk(["10.1086/000001"], session)
    assert result == {"10.1086/000001": "Recovered."}


def test_fetch_batch_chunk_client_error_raises_immediately() -> None:
    session: MagicMock = _mock_session(400)
    with patch("hpedb.supplement.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="400"):
            _fetch_batch_chunk(["10.1086/000001"], session)
    mock_sleep.assert_not_called()


def test_supplement_abstracts_none_missing(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "empty.db"))
    article: ArticleRecord = {**ARTICLE_HAS_ABSTRACT, "doi": "10.1086/has_one"}
    upsert_article(conn, article)

    found, total = supplement_abstracts(conn)
    conn.close()

    assert total == 0
    assert found == 0


def test_supplement_abstracts_multiple_batches(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "big.db"))
    base: ArticleRecord = {
        "doi": "",
        "journal": "JOP",
        "title": "T",
        "year": 2022,
        "month": None,
        "volume": None,
        "issue": None,
        "pages": None,
        "abstract": None,
    }
    for i in range(501):
        upsert_article(conn, {**base, "doi": f"10.1086/{i:06d}"})

    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = [None] * 500

    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = [{"abstract": "Found."}]

    with patch("hpedb.supplement.requests.Session") as mock_cls, \
         patch("hpedb.supplement.time.sleep"):
        mock_session = MagicMock()
        mock_session.post.side_effect = [resp1, resp2]
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        found, total = supplement_abstracts(conn)

    conn.close()

    assert total == 501
    assert found == 1
    assert mock_session.post.call_count == 2


def test_supplement_main(tmp_path: Path) -> None:
    db_path = str(tmp_path / "main.db")
    with patch("sys.argv", ["hpedb-supplement", "--db", db_path]), \
         patch("hpedb.supplement.supplement_abstracts", return_value=(3, 10)) as mock_supp, \
         patch("hpedb.supplement.init_db") as mock_init:
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_init.return_value = mock_conn
        main()
    mock_init.assert_called_once_with(db_path)
    mock_supp.assert_called_once_with(mock_conn)
    mock_conn.close.assert_called_once()


def test_supplement_abstracts_updates_missing_only(conn: sqlite3.Connection) -> None:
    body: list[dict[str, Any]] = [{"abstract": "New abstract."}]

    with patch("hpedb.supplement.requests.Session") as mock_cls, \
         patch("hpedb.supplement.time.sleep"):
        mock_session = _mock_session(200, body)
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        found, total = supplement_abstracts(conn)

    assert total == 1
    assert found == 1

    row = conn.execute(
        "SELECT abstract FROM articles WHERE doi=?", (ARTICLE_NO_ABSTRACT["doi"],)
    ).fetchone()
    assert row[0] == "New abstract."

    row2 = conn.execute(
        "SELECT abstract FROM articles WHERE doi=?", (ARTICLE_HAS_ABSTRACT["doi"],)
    ).fetchone()
    assert row2[0] == "Already here."
