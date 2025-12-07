#!/usr/bin/env python3
"""
Generate a playlist from fragments without merging.

Reads index.json (all fragments across all resolutions/files),
extracts each fragment to a timestamped MP4 file, and creates an M3U playlist
listing all fragments sorted by fragment start time.

Fragment filename format: YYYY-MM-DD_HH:mm:ss.mp4
  (based on source file creation_datetime + fragment start time)

Usage:
  python create_playlist.py /path/to/dir --out output_dir --index index.json

"""

import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any


def load_index(index_path: Path) -> List[Dict[str, Any]]:
    """Load index.json. Each entry has 'resolution' and 'file_fragments' list."""
    try:
        with index_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading index {index_path}: {e}")
        raise SystemExit(1)


def parse_iso_datetime(s: str) -> datetime:
    """Parse ISO datetime string (with optional Z suffix)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def extract_fragment(video_path: Path, start_s: float, end_s: float, output_path: Path) -> bool:
    """Extract fragment using ffmpeg (lossless stream copy).
    
    Uses -fflags +igndts to respect keyframes.
    Returns True on success, False otherwise.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(start_s),
            "-to", str(end_s),
            "-c", "copy",
            "-fflags", "+igndts",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  Warning: ffmpeg failed for {output_path.name}: {result.stderr[:200]}")
            return False
        return True
    except Exception as e:
        print(f"  Warning: extraction error for {output_path.name}: {e}")
        return False


def fragment_datetime(creation_dt_str: str, fragment_start_s: float) -> datetime:
    """
    Compute fragment datetime = source file creation_datetime + fragment_start_s offset.
    
    Args:
        creation_dt_str: ISO datetime string of source file creation time
        fragment_start_s: fragment start time in seconds (offset from video start)
    
    Returns:
        datetime object for the fragment
    """
    creation_dt = parse_iso_datetime(creation_dt_str)
    offset = timedelta(seconds=fragment_start_s)
    return creation_dt + offset


def process_all_fragments(
    index_data: List[Dict[str, Any]],
    source_dir: Path,
    output_dir: Path
) -> List[Dict[str, Any]]:
    """
    Extract all fragments and collect metadata for playlist.
    
    Returns list of dicts with keys: filename, fragment_datetime, fragment_start, fragment_end
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    fragments_extracted: List[Dict[str, Any]] = []
    
    # Flatten all fragments from all resolutions
    for res_group in index_data:
        file_fragments = res_group.get("file_fragments", [])
        for frag_entry in file_fragments:
            filename = frag_entry["filename"]
            creation_str = frag_entry["creation"]
            start = float(frag_entry["start"])
            end = float(frag_entry["end"])
            
            if not creation_str:
                print(f"  Skipping fragment {filename} (no creation_datetime)")
                continue
            
            # Compute fragment datetime
            frag_dt = fragment_datetime(creation_str, start)
            frag_dt_str = frag_dt.strftime("%Y-%m-%d_%H:%M:%S")
            output_filename = f"{frag_dt_str}.mp4"
            output_path = output_dir / output_filename
            
            # Handle duplicate filenames by appending counter
            counter = 1
            base_stem = output_filename[:-4]  # remove .mp4
            while output_path.exists():
                output_filename = f"{base_stem}_{counter:02d}.mp4"
                output_path = output_dir / output_filename
                counter += 1
            
            # Find the source MP4
            source_path = source_dir / filename
            if not source_path.exists():
                print(f"  Warning: source file {filename} not found, skipping fragment")
                continue
            
            print(f"  Extracting {filename} [{start:.2f}s - {end:.2f}s] -> {output_filename}...")
            if extract_fragment(source_path, start, end, output_path):
                fragments_extracted.append({
                    "filename": output_filename,
                    "fragment_datetime": frag_dt,
                    "start": start,
                    "end": end,
                    "source": filename
                })
            else:
                # Failed extraction, but continue
                pass
    
    return fragments_extracted


def create_m3u_playlist(fragments: List[Dict[str, Any]], playlist_path: Path) -> None:
    """Create M3U playlist from extracted fragments, sorted by fragment_datetime."""
    # Sort by fragment datetime
    fragments_sorted = sorted(fragments, key=lambda x: x["fragment_datetime"])
    
    try:
        with playlist_path.open("w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for frag in fragments_sorted:
                # Duration in milliseconds (for M3U format)
                duration_ms = int((frag["end"] - frag["start"]) * 1000)
                dt_str = frag["fragment_datetime"].strftime("%Y-%m-%d %H:%M:%S")
                filename = frag["filename"]
                f.write(f"#EXTINF:{duration_ms}ms, {dt_str} (from {frag['source']})\n")
                f.write(f"{filename}\n")
        print(f"Wrote playlist with {len(fragments_sorted)} fragments to {playlist_path}")
    except Exception as e:
        print(f"Error writing playlist {playlist_path}: {e}")
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Create playlist from all fragments (no merging, no resolution grouping)"
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Directory containing MP4 files and index.json"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="playlist_out",
        help="Output directory for fragment files and playlist (default: playlist_out)"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="index.json",
        help="Path to index.json (default: index.json in source directory)"
    )

    args = parser.parse_args()
    source_dir = Path(args.directory)
    output_dir = Path(args.out)
    
    # Resolve index path: try output_dir first, then source_dir, then as-is
    index_path = Path(args.index)
    if not index_path.is_absolute():
        # Try output_dir first
        if (output_dir / index_path).exists():
            index_path = output_dir / index_path
        # Otherwise try source_dir
        elif (source_dir / index_path).exists():
            index_path = source_dir / index_path
        # Otherwise keep as-is (will fail below with clear error)
    
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"Error: {source_dir} is not a directory")
        raise SystemExit(1)
    
    if not index_path.exists():
        print(f"Error: {index_path} not found")
        raise SystemExit(1)

    print("Loading index from {}".format(index_path))
    index_data = load_index(index_path)
    
    print("Processing fragments...")
    fragments = process_all_fragments(index_data, source_dir, output_dir)
    
    playlist_path = output_dir / "playlist.m3u"
    create_m3u_playlist(fragments, playlist_path)
    print(f"Done. Extracted {len(fragments)} fragments.")


if __name__ == "__main__":
    main()
