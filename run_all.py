#!/usr/bin/env python3
"""
Master runner that executes the pipeline in order:
 1. `noshake.py` (generate per-video JSON files)
 2. `index_by_resolution.py` (create index.json)
 3. `concatenate_fragments.py` (extract and concat fragments)

This script calls the other scripts using the same Python interpreter so they run
in the same environment. It forwards common options (threshold, min-duration,
sliding window) to `noshake.py` and controls output directory and whether to
keep intermediate fragment files.

Usage examples:
  python run_all.py /path/to/videos --out out_dir
  python run_all.py /path/to/videos -t 0.4 -d 2.5 -w 1.5 --keep-fragments

"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, *, check=True):
    print("+ " + " ".join(map(str, cmd)))
    try:
        result = subprocess.run(cmd, check=check)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit {e.returncode}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run noshake -> index_by_resolution -> concatenate_fragments pipeline")
    parser.add_argument("videos_dir", type=str, help="Directory containing MP4 files")
    parser.add_argument("--out", type=str, default='.', help="Output directory for final videos and index.json (default: current dir)")

    # noshake options
    parser.add_argument("-t", "--threshold", type=float, default=0.5, help="Sliding RMS threshold passed to noshake (default: 0.5)")
    parser.add_argument("-d", "--min-duration", type=float, default=3.0, dest='min_duration_s', help="Minimum fragment duration (seconds) for noshake (default: 3.0)")
    parser.add_argument("-w", "--window", type=float, default=1.0, dest='sliding_window_s', help="Sliding window seconds for noshake (default: 1.0)")

    # control steps
    parser.add_argument("--skip-noshake", action='store_true', help="Skip running noshake.py (assume JSON files exist)")
    parser.add_argument("--skip-index", action='store_true', help="Skip running index_by_resolution.py (assume index.json exists in out dir)")
    parser.add_argument("--skip-concat", action='store_true', help="Skip running concatenate_fragments.py")
    parser.add_argument("--playlist", action='store_true', help="Alternative mode: create M3U playlist instead of merging (uses create_playlist.py)")

    # fragments
    parser.add_argument("--keep-fragments", action='store_true', help="Keep intermediate fragment files when concatenating")

    args = parser.parse_args()

    videos_dir = Path(args.videos_dir)
    if not videos_dir.exists() or not videos_dir.is_dir():
        print(f"Error: {videos_dir} is not a directory")
        raise SystemExit(2)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    script_dir = Path(__file__).resolve().parent

    # Step 1: noshake.py
    if not args.skip_noshake:
        noshake_py = script_dir / 'noshake.py'
        if not noshake_py.exists():
            print(f"Error: {noshake_py} not found")
            raise SystemExit(2)

        cmd = [
            py, str(noshake_py), str(videos_dir),
            '-t', str(args.threshold),
            '-d', str(args.min_duration_s),
            '-w', str(args.sliding_window_s),
        ]
        print("\nRunning noshake to generate per-video JSON files...")
        if not run_command(cmd):
            print("noshake failed — aborting")
            raise SystemExit(1)

    # Step 2: index_by_resolution.py -> index.json in out_dir
    index_json = out_dir / 'index.json'
    if not args.skip_index:
        index_py = script_dir / 'index_by_resolution.py'
        if not index_py.exists():
            print(f"Error: {index_py} not found")
            raise SystemExit(2)

        cmd = [py, str(index_py), str(videos_dir), '--out', str(index_json)]
        print("\nGrouping JSONs by resolution to create index.json...")
        if not run_command(cmd):
            print("index_by_resolution failed — aborting")
            raise SystemExit(1)
    else:
        if not index_json.exists():
            print(f"Error: skipped indexing but {index_json} doesn't exist")
            raise SystemExit(2)

    # Step 3: concatenate_fragments.py OR create_playlist.py
    if not args.skip_concat:
        if args.playlist:
            # Alternative: create M3U playlist
            playlist_py = script_dir / 'create_playlist.py'
            if not playlist_py.exists():
                print(f"Error: {playlist_py} not found")
                raise SystemExit(2)

            cmd = [py, str(playlist_py), str(videos_dir), '--out', str(out_dir), '--index', str(index_json)]
            print("\nCreating playlist from fragments...")
            if not run_command(cmd):
                print("create_playlist failed — aborting")
                raise SystemExit(1)
        else:
            # Default: merge fragments per resolution
            concat_py = script_dir / 'concatenate_fragments.py'
            if not concat_py.exists():
                print(f"Error: {concat_py} not found")
                raise SystemExit(2)

            cmd = [py, str(concat_py), str(index_json), str(videos_dir), '--out', str(out_dir)]
            if args.keep_fragments:
                cmd.append('--keep-fragments')

            print("\nExtracting and concatenating fragments per resolution...")
            if not run_command(cmd):
                print("concatenate_fragments failed — aborting")
                raise SystemExit(1)

    print("\nPipeline completed — outputs in:")
    print(f"  {out_dir}")


if __name__ == '__main__':
    main()
