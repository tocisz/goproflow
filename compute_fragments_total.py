#!/usr/bin/env python3
"""
Scan a directory for JSON files produced by `noshake.py` and compute
- per-file total length of fragments (seconds)
- grand total across all JSON files

Usage:
  python compute_fragments_total.py /path/to/json_dir
  python compute_fragments_total.py /path/to/json_dir --per-file

The script prints a short summary to stdout and exits with 0.
"""

import json
import argparse
from pathlib import Path
from typing import Optional


def sum_fragments_in_file(path: Path) -> Optional[float]:
    """Return total duration (seconds) of fragments in the JSON file, or None if file invalid."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Warning: could not read {path}: {e}")
        return None

    fragments = data.get("fragments") if isinstance(data, dict) else None
    if not isinstance(fragments, list):
        # Maybe file is just the fragments array itself
        if isinstance(data, list):
            fragments = data
        else:
            print(f"Warning: {path} has no 'fragments' list")
            return None

    total = 0.0
    for frag in fragments:
        try:
            start = float(frag.get("start"))
            end = float(frag.get("end"))
            if end >= start:
                total += (end - start)
        except Exception:
            # skip malformed fragment entries
            continue

    return total


def main():
    parser = argparse.ArgumentParser(
        description="Compute total duration of fragments from JSON files"
    )
    parser.add_argument("directory", type=str, help="Directory containing JSON files")
    parser.add_argument("--per-file", action="store_true", help="Print per-file totals")
    parser.add_argument("--ext", default=".json", help="File extension to search for (default: .json)")

    args = parser.parse_args()
    d = Path(args.directory)
    if not d.exists() or not d.is_dir():
        print(f"Error: '{d}' is not a valid directory")
        raise SystemExit(2)

    files = sorted(d.glob(f"*{args.ext}"))
    if not files:
        print("No JSON files found.")
        raise SystemExit(0)

    grand_total = 0.0
    files_seen = 0
    for p in files:
        total = sum_fragments_in_file(p)
        if total is None:
            continue
        files_seen += 1
        grand_total += total
        if args.per_file:
            print(f"{p.name}: {total:.3f} s")

    print("---")
    print(f"Files processed: {files_seen}")
    print(f"Grand total fragments length: {grand_total:.3f} s")


if __name__ == "__main__":
    main()
