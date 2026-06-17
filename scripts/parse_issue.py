#!/usr/bin/env python3
"""Parse a GitHub issue form body into an override JSON entry.

Usage:
    echo "$ISSUE_BODY" | python scripts/parse_issue.py --type correction
    echo "$ISSUE_BODY" | python scripts/parse_issue.py --type new-entry
"""

from __future__ import annotations

import argparse
import json
import re
import sys


def parse_body(text: str) -> dict[str, str]:
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)
    result: dict[str, str] = {}
    for block in blocks:
        if not block.strip():
            continue
        head, _, rest = block.partition("\n")
        value = rest.strip()
        if value in ("_No response_", ""):
            value = ""
        result[head.strip()] = value
    return result


def parse_authors(raw: str) -> list[dict[str, str]]:
    """'Last, First; Last2, First2' → [{'family': ..., 'given': ...}, ...]"""
    authors = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        family, _, given = entry.partition(",")
        authors.append({"family": family.strip(), "given": given.strip()})
    return authors


def parse_period(raw: str) -> tuple[int | None, int | None]:
    """'1800–1870' or '1800-1870' or '1800' → (start, end)."""
    raw = raw.strip()
    if not raw:
        return None, None
    m = re.match(r"^(-?\d+)\s*[–\-]\s*(-?\d+)$", raw)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(-?\d+)$", raw)
    if m:
        year = int(m.group(1))
        return year, year
    return None, None


def parse_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []


def build_correction(fields: dict[str, str]) -> dict:
    doi = fields.get("DOI", "").strip()
    if not doi:
        raise ValueError("DOI is required")
    entry: dict = {"doi": doi}

    if v := fields.get("Corrected title", "").strip():
        entry["title"] = v

    if v := fields.get("Corrected publication year", "").strip():
        try:
            entry["year"] = int(v)
        except ValueError:
            pass  # optional: a malformed year is dropped, not a hard failure

    if v := fields.get("Corrected abstract", ""):
        entry["abstract"] = v

    if v := fields.get("Corrected authors", ""):
        entry["authors"] = parse_authors(v)

    if v := fields.get("Corrected geographic coverage", ""):
        entry["regions"] = parse_list(v)

    if v := fields.get("Corrected countries", ""):
        entry["countries"] = parse_list(v)

    if v := fields.get("Corrected time period", ""):
        start, end = parse_period(v)
        if start is not None:
            entry["period_start"] = start
        if end is not None:
            entry["period_end"] = end

    if v := fields.get("Corrected data link", ""):
        entry["replication_url"] = v

    if fields.get("Should this paper be excluded from the database?", "").startswith(
        "Yes"
    ):
        entry["is_hpe"] = False

    if v := fields.get("Source / justification", ""):
        entry["note"] = v

    return entry


def build_addition(fields: dict[str, str]) -> dict:
    # Only these are required: a dataset may be posted online with no associated
    # journal/paper, so Journal / Publication year / Geographic coverage are optional.
    required = ("Title (paper or dataset)", "Authors", "DOI", "Data link")
    missing = [f for f in required if not fields.get(f, "").strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    entry: dict = {
        "is_hpe": True,
        "title": fields["Title (paper or dataset)"].strip(),
        "doi": fields["DOI"].strip(),
        "replication_url": fields["Data link"].strip(),
        "countries": parse_list(fields.get("Countries", "")),
    }

    if v := fields.get("Journal", "").strip():
        entry["journal"] = v

    if v := fields.get("Publication year", "").strip():
        try:
            entry["year"] = int(v)
        except ValueError:
            pass  # optional: a malformed year is dropped, not a hard failure

    if v := fields.get("Geographic coverage", "").strip():
        entry["regions"] = parse_list(v)

    if v := fields.get("Abstract / Short Description", ""):
        entry["abstract"] = v

    if v := fields.get("Authors", ""):
        entry["authors"] = parse_authors(v)

    if v := fields.get("Period start (year)", "").strip():
        try:
            entry["period_start"] = int(v)
        except ValueError:
            pass

    if v := fields.get("Period end (year)", "").strip():
        try:
            entry["period_end"] = int(v)
        except ValueError:
            pass

    if v := fields.get("Notes", ""):
        entry["note"] = v

    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, choices=["correction", "new-entry"])
    args = parser.parse_args()

    fields = parse_body(sys.stdin.read())
    entry = (
        build_correction(fields)
        if args.type == "correction"
        else build_addition(fields)
    )
    json.dump(entry, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
