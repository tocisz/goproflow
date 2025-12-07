#!/usr/bin/env python3
"""
Fixup script for JSON fragment files.

Scans *.json files in a given directory. For files with resolution 1080x1920 or 1920x1080,
shifts the creation_datetime by +2 hours and writes the updated JSON back to disk.

Reports to stdout which files were updated and their datetime shifts.

Usage:
  python fixup_resolution.py /path/to/json/dir

"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta


def parse_iso_datetime(s: str) -> datetime:
    """Parse ISO datetime string (with optional Z suffix)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def to_iso_datetime(dt: datetime) -> str:
    """Convert datetime to ISO format string with Z suffix."""
    return dt.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def needs_fixup(resolution) -> bool:
    """Check if resolution is 1080x1920 or 1920x1080."""
    if not resolution or not isinstance(resolution, dict):
        return False
    w = resolution.get("width")
    h = resolution.get("height")
    if w is None or h is None:
        return False
    return (w == 1080 and h == 1920) or (w == 1920 and h == 1080)


def process_json_file(json_path: Path) -> tuple[bool, str]:
    """
    Process a single JSON file.
    
    Returns (updated: bool, message: str)
    """
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"  {json_path.name}: error reading: {e}"

    # Check if resolution matches
    resolution = data.get("resolution")
    if not needs_fixup(resolution):
        return False, f"  {json_path.name}: no fixup needed (resolution {resolution})"

    # Try to parse and shift creation_datetime
    creation_datetime_str = data.get("creation_datetime")
    if not creation_datetime_str:
        return False, f"  {json_path.name}: no creation_datetime, skipping"

    try:
        dt = parse_iso_datetime(creation_datetime_str)
    except Exception as e:
        return False, f"  {json_path.name}: error parsing datetime: {e}"

    # Shift by +2 hours
    new_dt = dt + timedelta(hours=2)
    new_datetime_str = to_iso_datetime(new_dt)

    # Update JSON
    data["creation_datetime"] = new_datetime_str

    # Write back
    try:
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        return False, f"  {json_path.name}: error writing: {e}"

    return True, f"  {json_path.name}: UPDATED (resolution {resolution['width']}x{resolution['height']}) — {creation_datetime_str} → {new_datetime_str}"


def main():
    parser = argparse.ArgumentParser(
        description="Fixup script: shift creation_datetime +2 hours for 1080x1920 / 1920x1080 resolution videos"
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Directory containing *.json files"
    )

    args = parser.parse_args()
    directory = Path(args.directory)

    if not directory.exists() or not directory.is_dir():
        print(f"Error: {directory} is not a directory")
        raise SystemExit(1)

    json_files = sorted(directory.glob("*.json"))
    if not json_files:
        print(f"No *.json files found in {directory}")
        return

    updated_count = 0
    print(f"Scanning {len(json_files)} JSON files in {directory}...\n")

    for json_path in json_files:
        updated, message = process_json_file(json_path)
        print(message)
        if updated:
            updated_count += 1

    print(f"\nTotal updated: {updated_count}/{len(json_files)}")


if __name__ == "__main__":
    main()
