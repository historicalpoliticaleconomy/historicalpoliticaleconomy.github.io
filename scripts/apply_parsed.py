#!/usr/bin/env python3
"""Append a parsed issue entry into overrides.json.

Usage:
    python scripts/apply_parsed.py <parsed.json> <correction|new-entry> [issue-number]

The optional issue-number is used for idempotency: the same issue cannot be
applied twice, but two different issues for the same DOI can both be applied.
"""

import json
import sys
from pathlib import Path

OVERRIDES_PATH = Path("overrides.json")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: apply_parsed.py <parsed.json> <correction|new-entry> [issue-number]",
              file=sys.stderr)
        sys.exit(1)

    parsed_path  = Path(sys.argv[1])
    entry_type   = sys.argv[2]
    issue_number = sys.argv[3] if len(sys.argv) > 3 else None
    key          = "corrections" if entry_type == "correction" else "additions"

    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    entry     = json.loads(parsed_path.read_text(encoding="utf-8"))

    doi      = entry.get("doi")
    existing = overrides.setdefault(key, [])

    if issue_number:
        if any(e.get("_issue") == issue_number for e in existing):
            print(f"Issue #{issue_number} already applied — skipping.")
            return
        entry["_issue"] = issue_number
    elif doi and any(e.get("doi") == doi for e in existing):
        # Fallback when no issue number: guard by DOI to prevent double-apply
        # on label remove/re-add for the same issue.
        print(f"Already in overrides.json[{key!r}]: {doi} — skipping.")
        return

    existing.append(entry)
    OVERRIDES_PATH.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Appended to overrides.json[{key!r}]: {doi or '(no doi)'}")


if __name__ == "__main__":
    main()
