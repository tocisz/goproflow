#!/usr/bin/env python3
"""
Group JSON/MP4 pairs by resolution and produce `index.json`.

For each resolution the script will:
 - find JSON files in the given directory (default: current dir)
 - read resolution and creation_datetime from each JSON
 - sort files within each resolution by `creation_datetime` (ascending)
 - list all fragments (each as {"filename":"..","start":..,"end":..})
   in the order of files sorted by creation_datetime and fragments sorted by start
 - write the result to `index.json` (or other output path)

Usage:
  python index_by_resolution.py /path/to/dir --out index.json

"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


def parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept trailing Z as UTC
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        return datetime.fromisoformat(s2)
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: failed to load {path}: {e}")
        return None


def resolution_key(res: Optional[Dict[str, Any]]) -> str:
    if not res:
        return "unknown"
    w = res.get("width")
    h = res.get("height")
    if w is None or h is None:
        return "unknown"
    return f"{w}x{h}"


def gather_index(directory: Path) -> List[Dict[str, Any]]:
    # map resolution_str -> list of file entries
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for json_path in sorted(directory.glob("*.json")):
        data = load_json_file(json_path)
        if data is None:
            continue

        # Try to get the mp4 filename from `video` field, fallback to sibling .MP4 name
        filename = data.get("video") or json_path.with_suffix('.MP4').name

        res = data.get("resolution")
        res_str = resolution_key(res)

        creation_dt = parse_iso_datetime(data.get("creation_datetime"))

        fragments = data.get("fragments")
        if not isinstance(fragments, list):
            # handle fallback where file contains array directly
            if isinstance(data, list):
                fragments = data
            else:
                fragments = []

        # Normalize and filter fragments: ensure start/end floats and start<end
        normalized: List[Dict[str, float]] = []
        for f in fragments:
            try:
                s = float(f.get("start"))
                e = float(f.get("end"))
                if e >= s:
                    normalized.append({"start": s, "end": e})
            except Exception:
                continue

        # Sort fragments by start
        normalized.sort(key=lambda x: x["start"]) 

        entry = {
            "filename": filename,
            "creation_datetime": creation_dt,
            "fragments": normalized
        }

        groups.setdefault(res_str, []).append(entry)

    # Build final grouped list
    result: List[Dict[str, Any]] = []
    for res_str, entries in sorted(groups.items()):
        # sort entries by creation_datetime (None -> after defined times)
        entries.sort(key=lambda e: (e["creation_datetime"] is None, e["creation_datetime"]))

        file_fragments: List[Dict[str, Any]] = []
        for e in entries:
            for frag in e["fragments"]:
                creation_str = e["creation_datetime"].isoformat() if e["creation_datetime"] else None
                file_fragments.append({
                    "creation": creation_str,
                    "filename": e["filename"],
                    "start": frag["start"],
                    "end": frag["end"]
                })

        result.append({
            "resolution": res_str,
            "file_fragments": file_fragments
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="Index JSON fragment files by resolution")
    parser.add_argument("directory", type=str, nargs='?', default='.', help="Directory with .json and .MP4 files")
    parser.add_argument("--out", type=str, default="index.json", help="Output JSON file path (default: index.json)")

    args = parser.parse_args()
    d = Path(args.directory)
    if not d.exists() or not d.is_dir():
        print(f"Error: {d} is not a directory")
        raise SystemExit(2)

    index = gather_index(d)

    out_path = Path(args.out)
    try:
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        print(f"Wrote index with {len(index)} resolution groups to {out_path}")
    except Exception as e:
        print(f"Error writing {out_path}: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
