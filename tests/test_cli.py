import datetime
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hpedb.cli import main
from hpedb.fetch import JOURNALS
from hpedb.types import ArticleRecord, AuthorRecord

_MAILTO = "test@example.com"

SAMPLE_ARTICLE: ArticleRecord = {
    "doi": "10.1086/123456",
    "journal": "JOP",
    "title": "Test Article",
    "year": 2022,
    "month": 1,
    "volume": "84",
    "issue": "1",
    "pages": "1-10",
    "abstract": None,
}

SAMPLE_AUTHOR: AuthorRecord = {"sequence": 0, "given": "Jane", "family": "Doe"}


@pytest.fixture
def mock_cli(tmp_path: Path) -> Any:
    """Patches all external dependencies of main(); yields a namespace of mocks."""

    class Mocks:
        conn: MagicMock
        wipe_db: MagicMock
        make_client: MagicMock
        fetch_journal: MagicMock
        upsert_article: MagicMock
        upsert_authors: MagicMock

    m = Mocks()
    m.conn = MagicMock(spec=sqlite3.Connection)

    with patch("hpedb.cli.init_db", return_value=m.conn), \
         patch("hpedb.cli.wipe_db") as m.wipe_db, \
         patch("hpedb.cli.make_client") as m.make_client, \
         patch("hpedb.cli.fetch_journal", return_value=[]) as m.fetch_journal, \
         patch("hpedb.cli.upsert_article") as m.upsert_article, \
         patch("hpedb.cli.upsert_authors") as m.upsert_authors, \
         patch("hpedb.cli.time.sleep"):
        yield m


def _argv(*extra: str) -> list[str]:
    return ["hpedb", "--from-year", "2020", "--mailto", _MAILTO, *extra]


def test_from_year_required() -> None:
    with patch("sys.argv", ["hpedb", "--mailto", _MAILTO]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 2


def test_mailto_required() -> None:
    with patch("sys.argv", ["hpedb", "--from-year", "2020"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 2


def test_mailto_is_passed_to_make_client(mock_cli: Any) -> None:
    with patch("sys.argv", _argv()):
        main()
    mock_cli.make_client.assert_called_once_with(_MAILTO)


def test_fresh_flag_calls_wipe_db(mock_cli: Any) -> None:
    with patch("sys.argv", _argv("--fresh")):
        main()
    mock_cli.wipe_db.assert_called_once_with(mock_cli.conn)


def test_no_fresh_flag_does_not_wipe(mock_cli: Any) -> None:
    with patch("sys.argv", _argv()):
        main()
    mock_cli.wipe_db.assert_not_called()


def test_to_year_defaults_to_current_year(mock_cli: Any) -> None:
    current_year = datetime.date.today().year
    with patch("sys.argv", _argv()):
        main()
    for call in mock_cli.fetch_journal.call_args_list:
        assert call.args[4] == current_year


def test_fetch_journal_called_for_every_journal(mock_cli: Any) -> None:
    with patch("sys.argv", _argv()):
        main()
    called_abbrevs = {call.args[1] for call in mock_cli.fetch_journal.call_args_list}
    assert called_abbrevs == set(JOURNALS.keys())


def test_articles_and_authors_are_upserted(mock_cli: Any) -> None:
    mock_cli.fetch_journal.return_value = [(SAMPLE_ARTICLE, [SAMPLE_AUTHOR])]
    with patch("sys.argv", _argv()):
        main()
    assert mock_cli.upsert_article.call_count == len(JOURNALS)
    mock_cli.upsert_article.assert_any_call(mock_cli.conn, SAMPLE_ARTICLE)
    mock_cli.upsert_authors.assert_any_call(
        mock_cli.conn, SAMPLE_ARTICLE["doi"], [SAMPLE_AUTHOR]
    )
