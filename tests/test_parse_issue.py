"""Tests for scripts/parse_issue.py"""

import importlib.util
import json as _json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import parse_issue as p  # noqa: E402


# ── parse_body ────────────────────────────────────────────────────────────────


def test_parse_body_basic() -> None:
    body = "### DOI\n\n10.1017/example\n\n### Journal\n\nAPSR\n"
    assert p.parse_body(body) == {"DOI": "10.1017/example", "Journal": "APSR"}


def test_parse_body_no_response_becomes_empty() -> None:
    body = "### Countries\n\n_No response_\n"
    assert p.parse_body(body) == {"Countries": ""}


def test_parse_body_blank_value_becomes_empty() -> None:
    body = "### Notes\n\n\n### DOI\n\n10.1/x\n"
    assert p.parse_body(body)["Notes"] == ""


def test_parse_body_multiline_value() -> None:
    body = "### What is wrong?\n\nLine one.\nLine two.\n"
    assert p.parse_body(body) == {"What is wrong?": "Line one.\nLine two."}


def test_parse_body_strips_surrounding_whitespace() -> None:
    body = "### DOI\n\n  10.1/x  \n"
    assert p.parse_body(body) == {"DOI": "10.1/x"}


# ── parse_authors ─────────────────────────────────────────────────────────────


def test_parse_authors_single() -> None:
    assert p.parse_authors("Smith, John") == [{"family": "Smith", "given": "John"}]


def test_parse_authors_multiple() -> None:
    result = p.parse_authors("Acemoglu, Daron; Robinson, James")
    assert result == [
        {"family": "Acemoglu", "given": "Daron"},
        {"family": "Robinson", "given": "James"},
    ]


def test_parse_authors_no_given_name() -> None:
    assert p.parse_authors("Aristotle") == [{"family": "Aristotle", "given": ""}]


def test_parse_authors_extra_whitespace() -> None:
    result = p.parse_authors("  Jones , Alice ;  Smith , Bob  ")
    assert result == [
        {"family": "Jones", "given": "Alice"},
        {"family": "Smith", "given": "Bob"},
    ]


def test_parse_authors_empty_string() -> None:
    assert p.parse_authors("") == []


# ── parse_period ──────────────────────────────────────────────────────────────


def test_parse_period_em_dash() -> None:
    assert p.parse_period("1800–1870") == (1800, 1870)


def test_parse_period_hyphen() -> None:
    assert p.parse_period("1800-1870") == (1800, 1870)


def test_parse_period_single_year() -> None:
    assert p.parse_period("1850") == (1850, 1850)


def test_parse_period_empty() -> None:
    assert p.parse_period("") == (None, None)


def test_parse_period_bce() -> None:
    assert p.parse_period("-500–500") == (-500, 500)


def test_parse_period_whitespace_around_dash() -> None:
    assert p.parse_period("1800 – 1870") == (1800, 1870)


def test_parse_period_garbage_returns_none() -> None:
    assert p.parse_period("around 1800") == (None, None)


# ── parse_list ────────────────────────────────────────────────────────────────


def test_parse_list_multiple() -> None:
    assert p.parse_list("Western Europe, South-eastern Asia") == [
        "Western Europe",
        "South-eastern Asia",
    ]


def test_parse_list_strips_whitespace() -> None:
    assert p.parse_list("  Germany , France ") == ["Germany", "France"]


def test_parse_list_empty_string() -> None:
    assert p.parse_list("") == []


def test_parse_list_single() -> None:
    assert p.parse_list("Germany") == ["Germany"]


# ── build_correction ──────────────────────────────────────────────────────────


def _correction_fields(**kwargs: str) -> dict[str, str]:
    defaults: dict[str, str] = {
        "DOI": "10.1017/test",
        "What is wrong?": "Regions are wrong.",
        "Corrected geographic coverage": "",
        "Corrected countries": "",
        "Corrected time period": "",
        "Corrected data link": "",
        "Should this paper be excluded from the database?": "No",
        "Source / justification": "See paper.",
    }
    return {**defaults, **kwargs}


def test_correction_doi_required() -> None:
    with pytest.raises(ValueError, match="DOI"):
        p.build_correction({"DOI": "", "What is wrong?": "Bad"})


def test_correction_minimal() -> None:
    result = p.build_correction(_correction_fields())
    assert result["doi"] == "10.1017/test"
    assert "regions" not in result
    assert "countries" not in result
    assert "is_hpe" not in result


def test_correction_regions_parsed_as_list() -> None:
    result = p.build_correction(
        _correction_fields(
            **{"Corrected geographic coverage": "Western Europe, Northern America"}
        )
    )
    assert result["regions"] == ["Western Europe", "Northern America"]


def test_correction_countries_parsed_as_list() -> None:
    result = p.build_correction(
        _correction_fields(**{"Corrected countries": "Germany, France"})
    )
    assert result["countries"] == ["Germany", "France"]


def test_correction_period_split() -> None:
    result = p.build_correction(
        _correction_fields(**{"Corrected time period": "1800–1870"})
    )
    assert result["period_start"] == 1800
    assert result["period_end"] == 1870


def test_correction_period_absent_when_blank() -> None:
    result = p.build_correction(_correction_fields())
    assert "period_start" not in result
    assert "period_end" not in result


def test_correction_data_link() -> None:
    result = p.build_correction(
        _correction_fields(**{"Corrected data link": "https://example.com/data"})
    )
    assert result["replication_url"] == "https://example.com/data"


def test_correction_exclude_yes_sets_is_hpe_false() -> None:
    result = p.build_correction(
        _correction_fields(
            **{
                "Should this paper be excluded from the database?": "Yes — not an HPE dataset"
            }
        )
    )
    assert result["is_hpe"] is False


def test_correction_exclude_no_omits_is_hpe() -> None:
    result = p.build_correction(
        _correction_fields(**{"Should this paper be excluded from the database?": "No"})
    )
    assert "is_hpe" not in result


def test_correction_note_included() -> None:
    result = p.build_correction(
        _correction_fields(**{"Source / justification": "See Smith (2020)."})
    )
    assert result["note"] == "See Smith (2020)."


# ── build_addition ────────────────────────────────────────────────────────────


def _addition_fields(**kwargs: str) -> dict[str, str]:
    defaults: dict[str, str] = {
        "Title (paper or dataset)": "Taxation and State Capacity",
        "Authors": "Acemoglu, Daron; Robinson, James",
        "DOI": "10.1093/qje/qjt001",
        "Journal": "Quarterly Journal of Economics",
        "Publication year": "2013",
        "Data link": "https://dataverse.harvard.edu/dataset.xhtml",
        "Geographic coverage": "Western Europe",
        "Countries": "France",
        "Period start (year)": "1800",
        "Period end (year)": "1950",
        "Abstract / Short Description": "",
        "Notes": "",
    }
    return {**defaults, **kwargs}


def test_addition_full() -> None:
    result = p.build_addition(_addition_fields())
    assert result["doi"] == "10.1093/qje/qjt001"
    assert result["title"] == "Taxation and State Capacity"
    assert result["journal"] == "Quarterly Journal of Economics"
    assert result["year"] == 2013
    assert result["is_hpe"] is True
    assert result["regions"] == ["Western Europe"]
    assert result["countries"] == ["France"]
    assert result["period_start"] == 1800
    assert result["period_end"] == 1950
    assert result["replication_url"] == "https://dataverse.harvard.edu/dataset.xhtml"
    assert result["authors"] == [
        {"family": "Acemoglu", "given": "Daron"},
        {"family": "Robinson", "given": "James"},
    ]


def test_addition_missing_required_raises() -> None:
    for field in ("Title (paper or dataset)", "Authors", "DOI", "Data link"):
        with pytest.raises(ValueError):
            p.build_addition(_addition_fields(**{field: ""}))


def test_addition_optional_fields_blank_succeeds() -> None:
    """Journal / Publication year / Geographic coverage are optional (datasets need
    not be tied to a journal); a submission omitting them still parses."""
    result = p.build_addition(
        _addition_fields(
            **{"Journal": "", "Publication year": "", "Geographic coverage": ""}
        )
    )
    assert result["doi"] == "10.1093/qje/qjt001"
    assert result["title"] == "Taxation and State Capacity"
    assert result["is_hpe"] is True
    assert "journal" not in result
    assert "year" not in result
    assert "regions" not in result


def test_addition_invalid_year_skipped() -> None:
    """Year is optional now; a malformed value is dropped rather than rejecting the entry."""
    result = p.build_addition(
        _addition_fields(**{"Publication year": "nineteenth century"})
    )
    assert "year" not in result


def test_addition_no_countries_defaults_to_empty_list() -> None:
    result = p.build_addition(_addition_fields(**{"Countries": ""}))
    assert result["countries"] == []


def test_addition_abstract_captured() -> None:
    result = p.build_addition(
        _addition_fields(
            **{
                "Abstract / Short Description": "Wheat prices, 1500-1800; rainfall; conflict counts."
            }
        )
    )
    assert result["abstract"] == "Wheat prices, 1500-1800; rainfall; conflict counts."


def test_addition_blank_abstract_absent() -> None:
    result = p.build_addition(_addition_fields(**{"Abstract / Short Description": ""}))
    assert "abstract" not in result


def test_addition_blank_period_fields_absent() -> None:
    result = p.build_addition(
        _addition_fields(**{"Period start (year)": "", "Period end (year)": ""})
    )
    assert "period_start" not in result
    assert "period_end" not in result


def test_addition_blank_notes_absent() -> None:
    result = p.build_addition(_addition_fields(**{"Notes": ""}))
    assert "note" not in result


def test_addition_regions_parsed_as_list() -> None:
    result = p.build_addition(
        _addition_fields(**{"Geographic coverage": "Western Europe, Northern America"})
    )
    assert result["regions"] == ["Western Europe", "Northern America"]


# ── apply_parsed (idempotency) ────────────────────────────────────────────────


def _load_apply_parsed() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "apply_parsed",
        Path(__file__).parent.parent / "scripts" / "apply_parsed.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run(
    mod: types.ModuleType,
    overrides: Path,
    parsed: Path,
    entry_type: str,
    issue: str | None = None,
) -> None:
    import sys

    mod.OVERRIDES_PATH = overrides  # type: ignore[attr-defined]
    sys.argv = ["apply_parsed.py", str(parsed), entry_type] + ([issue] if issue else [])
    mod.main()


def test_apply_parsed_appends(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"corrections": [], "additions": []}')
    parsed = tmp_path / "parsed.json"
    parsed.write_text('{"doi": "10.1/test", "regions": ["Western Europe"]}')

    _run(_load_apply_parsed(), overrides, parsed, "correction", "42")

    result = _json.loads(overrides.read_text())
    assert len(result["corrections"]) == 1
    assert result["corrections"][0]["doi"] == "10.1/test"
    assert result["corrections"][0]["_issue"] == "42"


def test_apply_parsed_same_issue_idempotent(tmp_path: Path) -> None:
    """Re-triggering from label remove/re-add on the same issue is a no-op."""
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        '{"corrections": [{"doi": "10.1/test", "_issue": "42"}], "additions": []}'
    )
    parsed = tmp_path / "parsed.json"
    parsed.write_text('{"doi": "10.1/test", "regions": ["Northern Europe"]}')

    _run(_load_apply_parsed(), overrides, parsed, "correction", "42")

    result = _json.loads(overrides.read_text())
    assert len(result["corrections"]) == 1  # not duplicated


def test_apply_parsed_different_issue_same_doi_allowed(tmp_path: Path) -> None:
    """Two separate issues correcting the same DOI both get applied."""
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        '{"corrections": [{"doi": "10.1/test", "regions": ["Western Europe"], "_issue": "42"}], "additions": []}'
    )
    parsed = tmp_path / "parsed.json"
    parsed.write_text('{"doi": "10.1/test", "period_end": 1900}')

    _run(_load_apply_parsed(), overrides, parsed, "correction", "99")

    result = _json.loads(overrides.read_text())
    assert len(result["corrections"]) == 2
    assert result["corrections"][1]["_issue"] == "99"


def test_apply_parsed_no_issue_number_falls_back_to_doi(tmp_path: Path) -> None:
    """Without an issue number, DOI is used as idempotency key (manual runs)."""
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"corrections": [{"doi": "10.1/test"}], "additions": []}')
    parsed = tmp_path / "parsed.json"
    parsed.write_text('{"doi": "10.1/test", "regions": ["Northern Europe"]}')

    _run(_load_apply_parsed(), overrides, parsed, "correction")

    result = _json.loads(overrides.read_text())
    assert len(result["corrections"]) == 1  # blocked by DOI fallback
