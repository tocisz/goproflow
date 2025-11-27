#!/usr/bin/env python3
"""
Concatenate video fragments from index.json (as created by index_by_resolution.py).

For each resolution group in index.json:
 1. Extract fragments from source MP4 files using ffmpeg with lossless cuts
 2. Generate subtitle file showing filename at start of each fragment
 3. Merge extracted fragments using the concat demuxer
 4. Mux subtitles into the output MP4
 5. Save output as output_<resolution>.mp4 (e.g., output_1920x1080.mp4)
 6. Optionally keep or delete intermediate fragment files

Fragment extraction uses:
  ffmpeg -ss <seek> -i <input.mp4> -ss 0 -c copy -to <duration> -avoid_negative_ts make_zero <fragment.mp4>

This provides precise (millisecond-level) trimming with lossless codec copy.

Usage:
  python concatenate_fragments.py index.json /path/to/videos --out /path/to/output
  python concatenate_fragments.py index.json /path/to/videos --out /path/to/output --keep-fragments
"""

import json
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import List
from datetime import datetime


def seconds_to_timecode(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.ms timecode."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def run_ffmpeg(cmd: List[str]) -> bool:
    """Run ffmpeg command and return True if successful."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            print(f"FFmpeg error: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("FFmpeg command timed out")
        return False
    except Exception as e:
        print(f"Error running ffmpeg: {e}")
        return False


def extract_fragment(
    source_mp4: Path,
    start_sec: float,
    end_sec: float,
    output_fragment: Path
) -> bool:
    """Extract a fragment from source_mp4 using lossless cut on keyframes."""
    start_tc = seconds_to_timecode(start_sec)
    duration = end_sec - start_sec
    
    cmd = [
        "ffmpeg",
        "-ss", start_tc,
        "-i", str(source_mp4),
        "-ss", "0",
        "-c", "copy",
        "-t", str(duration),
        "-avoid_negative_ts", "make_zero",
        "-fflags", "+igndts",
        "-y",  # overwrite output
        str(output_fragment)
    ]
    
    print(f"  Extracting {source_mp4.name} [{start_tc} - {seconds_to_timecode(end_sec)}] (on keyframes)...")
    return run_ffmpeg(cmd)


def concatenate_fragments(
    fragment_paths: List[Path],
    output_mp4: Path
) -> bool:
    """Concatenate fragments using ffmpeg concat demuxer."""
    # Create concat demuxer file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        concat_file = Path(f.name)
        for frag in fragment_paths:
            f.write(f"file '{frag.absolute()}'\n")
    
    try:
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            "-y",  # overwrite output
            str(output_mp4)
        ]
        
        print(f"Concatenating {len(fragment_paths)} fragments into {output_mp4.name}...")
        success = run_ffmpeg(cmd)
        return success
    finally:
        concat_file.unlink(missing_ok=True)


def format_creation(creation_str: str) -> str:
    """Parse ISO creation string and return formatted label 'YYYY-MM-DD HH:MM', or None."""
    if not creation_str:
        return None
    try:
        s = creation_str
        if isinstance(s, str) and s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return None


def generate_subtitles_srt(
    file_fragments: List[dict],
    fragment_durations: dict
) -> str:
    """Generate SRT subtitle content showing filename at start of each fragment."""
    srt_lines = []
    subtitle_idx = 1
    current_time = 0.0
    # Track filenames already shown so we only display each filename once
    shown_filenames = set()

    for frag_info in file_fragments:
        filename = frag_info.get("filename", "unknown")
        creation_raw = frag_info.get("creation")
        creation_label = format_creation(creation_raw) or filename

        # Get the duration of this fragment from our calculated map
        frag_key = (frag_info.get("start"), frag_info.get("end"))
        duration = fragment_durations.get(frag_key, 1.0)

        # Only show the creation datetime subtitle for the first fragment of a source file
        if filename not in shown_filenames:
            # Show creation datetime for 2 seconds at the start of fragment
            start_tc = seconds_to_timecode(current_time)
            end_tc = seconds_to_timecode(current_time + 2.0)

            srt_lines.append(str(subtitle_idx))
            srt_lines.append(f"{start_tc} --> {end_tc}")
            srt_lines.append(creation_label)
            srt_lines.append("")

            subtitle_idx += 1
            shown_filenames.add(filename)

        # Advance timeline by this fragment's duration regardless
        current_time += duration
    
    return "\n".join(srt_lines)


def mux_subtitles(
    video_mp4: Path,
    srt_content: str,
    output_with_subs: Path
) -> bool:
    """Mux subtitle track into video file."""
    # Write SRT file temporarily
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        srt_file = Path(f.name)
        f.write(srt_content)
    
    try:
        cmd = [
            "ffmpeg",
            "-i", str(video_mp4),
            "-i", str(srt_file),
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "mov_text",
            "-metadata:s:s:0", "language=eng",
            "-y",  # overwrite output
            str(output_with_subs)
        ]
        
        print(f"Muxing subtitles into {output_with_subs.name}...")
        success = run_ffmpeg(cmd)
        return success
    finally:
        srt_file.unlink(missing_ok=True)


def process_index(
    index_path: Path,
    video_dir: Path,
    output_dir: Path,
    keep_fragments: bool = False
) -> None:
    """Process index.json and create concatenated outputs for each resolution."""
    
    with index_path.open("r") as f:
        index = json.load(f)
    
    for group_idx, group in enumerate(index):
        resolution = group.get("resolution", "unknown")
        file_fragments = group.get("file_fragments", [])
        
        print(f"\n[{group_idx + 1}/{len(index)}] Processing resolution: {resolution}")
        print(f"  {len(file_fragments)} fragments to process")
        
        # Create temporary work directory for this resolution
        work_dir = output_dir / f"_work_{resolution}"
        work_dir.mkdir(parents=True, exist_ok=True)
        
        extracted_fragments: List[Path] = []
        fragment_durations: dict = {}
        
        # Extract fragments
        for frag_idx, frag_info in enumerate(file_fragments):
            filename = frag_info.get("filename")
            start = frag_info.get("start")
            end = frag_info.get("end")
            
            if not filename or start is None or end is None:
                print(f"  Warning: skipping malformed fragment {frag_idx}")
                continue
            
            source_mp4 = video_dir / filename
            if not source_mp4.exists():
                print(f"  Warning: source file not found: {source_mp4}")
                continue
            
            # Generate fragment filename: <video_name>_<start>-<end>.mp4
            # sanitize filename
            video_stem = source_mp4.stem
            frag_name = f"{video_stem}_{frag_idx:03d}_{start:.3f}-{end:.3f}.mp4"
            frag_output = work_dir / frag_name
            
            if extract_fragment(source_mp4, start, end, frag_output):
                extracted_fragments.append(frag_output)
                # Store fragment duration for subtitle generation
                duration = end - start
                fragment_durations[(start, end)] = duration
            else:
                print(f"  Error: failed to extract fragment {frag_idx}")
        
        if not extracted_fragments:
            print(f"  No fragments extracted for {resolution}")
            work_dir.rmdir()
            continue
        
        # Concatenate fragments
        output_name = f"output_{resolution}.mp4"
        output_mp4 = output_dir / output_name
        
        if concatenate_fragments(extracted_fragments, output_mp4):
            print(f"  -> Created {output_mp4}")
        else:
            print("  Error: failed to concatenate fragments")
            continue
        
        # Generate and mux subtitles
        srt_content = generate_subtitles_srt(file_fragments, fragment_durations)
        output_with_subs = output_dir / f"output_{resolution}_with_subs.mp4"
        
        if mux_subtitles(output_mp4, srt_content, output_with_subs):
            # Replace original with subtitle version
            output_mp4.unlink()
            output_with_subs.rename(output_mp4)
            print(f"  -> Added subtitle track to {output_mp4}")
        else:
            print("  Warning: failed to mux subtitles, keeping video without subtitles")
        
        # Cleanup or keep fragments
        if keep_fragments:
            print(f"  Keeping fragment files in {work_dir}")
        else:
            print("  Cleaning up fragment files...")
            for frag in extracted_fragments:
                frag.unlink(missing_ok=True)
            work_dir.rmdir()


def main():
    parser = argparse.ArgumentParser(
        description="Concatenate video fragments from index.json"
    )
    parser.add_argument(
        "index_json",
        type=str,
        help="Path to index.json created by index_by_resolution.py"
    )
    parser.add_argument(
        "video_dir",
        type=str,
        help="Directory containing source MP4 files"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=".",
        help="Output directory for concatenated videos (default: current dir)"
    )
    parser.add_argument(
        "--keep-fragments",
        action="store_true",
        help="Keep intermediate fragment files (default: delete after concatenation)"
    )
    
    args = parser.parse_args()
    
    index_path = Path(args.index_json)
    video_dir = Path(args.video_dir)
    output_dir = Path(args.out)
    
    # Validation
    if not index_path.exists():
        print(f"Error: {index_path} not found")
        raise SystemExit(2)
    if not video_dir.exists() or not video_dir.is_dir():
        print(f"Error: {video_dir} is not a valid directory")
        raise SystemExit(2)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Reading index from {index_path}")
    print(f"Source videos: {video_dir}")
    print(f"Output directory: {output_dir}")
    print()
    
    process_index(index_path, video_dir, output_dir, args.keep_fragments)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
