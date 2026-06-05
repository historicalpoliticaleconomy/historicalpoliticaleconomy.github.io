#!/usr/bin/env python3
"""Append a parsed issue entry into overrides.json.

Usage:
    python scripts/apply_parsed.py /tmp/parsed.json correction
    python scripts/apply_parsed.py /tmp/parsed.json new-entry
"""

import json
import sys
from pathlib import Path

OVERRIDES_PATH = Path("overrides.json")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: apply_parsed.py <parsed.json> <correction|new-entry>", file=sys.stderr)
        sys.exit(1)

    parsed_path = Path(sys.argv[1])
    entry_type  = sys.argv[2]
    key         = "corrections" if entry_type == "correction" else "additions"

    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    entry     = json.loads(parsed_path.read_text(encoding="utf-8"))

    overrides.setdefault(key, []).append(entry)
    OVERRIDES_PATH.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Appended to overrides.json[{key!r}]: {entry.get('doi', '(no doi)')}")


if __name__ == "__main__":
    main()
