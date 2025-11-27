# GoPro Fragment Detection & Concatenation Pipeline

A Python toolkit for analyzing GoPro MP4 videos to identify smooth (non-shaky) video fragments based on telemetry data, group them by resolution, and create concatenated output videos with timestamps.

## Overview

This pipeline consists of four main scripts that work together:

1. **`noshake.py`** — Analyzes GoPro videos to detect smooth fragments
2. **`index_by_resolution.py`** — Groups detected fragments by video resolution
3. **`concatenate_fragments.py`** — Extracts and concatenates fragments into output videos
4. **`run_all.py`** — Master script that runs the entire pipeline in one command

## Prerequisites

- Python 3.7+
- `ffmpeg` and `ffprobe` (for video extraction and metadata)
- GoPro MP4 files with CORI (stabilization) telemetry
- Python packages: see `requirements.txt`

### Installation

```bash
pip install -r requirements.txt
```

Ensure `ffmpeg` and `ffprobe` are in your PATH:
```bash
ffmpeg -version
ffprobe -version
```

## Usage

### Quick Start: Run Everything

The easiest way is to use `run_all.py` to execute the full pipeline:

```bash
python run_all.py /path/to/videos --out output_dir
```

This will:
1. Generate per-video JSON files (in the video directory)
2. Create `index.json` in the output directory
3. Extract and concatenate fragments by resolution

### Individual Scripts

#### 1. Detect Smooth Fragments (`noshake.py`)

Analyzes GoPro videos and outputs a JSON file per video containing detected smooth fragments.

```bash
python noshake.py /path/to/videos -t 0.5 -d 3.0 -w 1.0
```

**Arguments:**
- `directory` (required) — Path to directory with `.MP4` files
- `-t, --threshold` (default: 0.5) — Sliding RMS threshold; fragments with RMS below this are considered smooth
- `-d, --min-duration` (default: 3.0) — Minimum fragment length (seconds)
- `-w, --window` (default: 1.0) — Sliding window size (seconds) for RMS calculation

**Output:**
Creates `<video_name>.json` files in the same directory as the videos:
```json
{
  "video": "GX011031_1763833383191.MP4",
  "resolution": {
    "width": 1920,
    "height": 1080
  },
  "creation_datetime": "2025-11-21T09:42:45.000000Z",
  "fragments": [
    {
      "start": 0.0,
      "end": 25.56
    },
    {
      "start": 26.06,
      "end": 52.92
    }
  ]
}
```

#### 2. Group by Resolution (`index_by_resolution.py`)

Groups detected fragments by video resolution and sorts them by creation datetime.

```bash
python index_by_resolution.py /path/to/videos --out index.json
```

**Arguments:**
- `directory` — Path to directory with `.json` files (from step 1)
- `--out` (default: index.json) — Output JSON file path

**Output:**
Creates `index.json` with resolution groups and creation timestamps:
```json
[
  {
    "resolution": "1920x1080",
    "file_fragments": [
      {
        "filename": "GX011031.MP4",
        "creation": "2025-11-21 09:42",
        "start": 0.0,
        "end": 25.56
      },
      {
        "filename": "GX011032.MP4",
        "creation": "2025-11-21 10:15",
        "start": 2.54,
        "end": 6.44
      }
    ]
  }
]
```

#### 3. Extract & Concatenate (`concatenate_fragments.py`)

Extracts smooth fragments from source videos and concatenates them by resolution group. Includes creation timestamp subtitles.

```bash
python concatenate_fragments.py index.json /path/to/videos --out output_dir
```

**Arguments:**
- `index_json` (required) — Path to `index.json` (from step 2)
- `video_dir` (required) — Directory containing source `.MP4` files
- `--out` (default: current dir) — Output directory for concatenated videos
- `--keep-fragments` — Keep intermediate fragment files (default: auto-cleanup)

**Output:**
For each resolution group, creates `output_<resolution>.mp4` (e.g., `output_1920x1080.mp4`):
- Lossless extraction using ffmpeg codec copy
- Keyframe-aligned cuts for clean transitions
- Embedded subtitle track showing video creation timestamp for 2 seconds at the start of each source file's first fragment
- Example subtitle: `2025-11-21 09:42`

#### 4. Master Runner (`run_all.py`)

Orchestrates the entire pipeline with one command.

```bash
python run_all.py /path/to/videos --out output_dir [options]
```

**Arguments:**
- `videos_dir` (required) — Path to directory with `.MP4` files
- `--out` (default: current dir) — Output directory for final videos
- `-t, --threshold` (default: 0.5) — Passed to `noshake.py`
- `-d, --min-duration` (default: 3.0) — Passed to `noshake.py`
- `-w, --window` (default: 1.0) — Passed to `noshake.py`
- `--keep-fragments` — Keep intermediate fragment files
- `--skip-noshake` — Skip fragment detection (assume JSONs exist)
- `--skip-index` — Skip indexing (assume `index.json` exists in `--out`)
- `--skip-concat` — Skip concatenation

**Examples:**

Full pipeline with custom thresholds:
```bash
python run_all.py ~/videos --out out_final -t 0.4 -d 2.5 -w 1.5
```

Re-run concatenation only (skip detection and indexing):
```bash
python run_all.py ~/videos --skip-noshake --skip-index --out out_final
```

Keep intermediate fragments for inspection:
```bash
python run_all.py ~/videos --out out_final --keep-fragments
```

## Workflow Example

1. Place GoPro videos in a directory:
   ```
   ~/videos/GX011031.MP4
   ~/videos/GX011032.MP4
   ~/videos/GX011033.MP4
   ```

2. Run the full pipeline:
   ```bash
   python run_all.py ~/videos --out ~/output -t 0.5
   ```

3. Check the output:
   ```
   ~/output/index.json                    # Resolution groups and fragment times
   ~/output/output_1920x1080.mp4         # Concatenated smooth fragments at 1920x1080
   ~/output/output_3840x2160.mp4         # Concatenated smooth fragments at 4K (if present)
   ```

4. View the video with embedded subtitles:
   - Open `output_1920x1080.mp4` in any video player
   - Enable subtitles to see creation timestamps

## How It Works

### Fragment Detection (`noshake.py`)

1. Extracts CORI quaternion telemetry from GoPro GPMF metadata
2. Computes frame-to-frame rotation angles
3. Calculates sliding RMS of rotation angles
4. Identifies regions where RMS is below the threshold (smooth regions)
5. Filters fragments by minimum duration

### Concatenation (`concatenate_fragments.py`)

1. **Lossless extraction**: Uses `ffmpeg -c copy` to avoid re-encoding
2. **Keyframe-aligned cuts**: Uses `-fflags +igndts` to align cuts to keyframes
3. **Precise trimming**: Applies `-ss` before input for accurate seeking and `-t` after for exact duration
4. **Concat demuxer**: Merges fragments without re-encoding
5. **Subtitle embedding**: Adds creation datetime labels for traceability

## Output Files

### Per-Video JSON (from `noshake.py`)
- `<video_name>.json` — Metadata and detected fragments for each video

### Index JSON (from `index_by_resolution.py`)
- `index.json` — Aggregated fragments grouped by resolution and sorted by creation time

### Intermediate Fragments (from `concatenate_fragments.py`)
- `_work_<resolution>/` — Temporary directory with extracted fragments (deleted unless `--keep-fragments` used)
- Named as: `<video_stem>_<index>_<start>-<end>.mp4`

### Final Videos (from `concatenate_fragments.py`)
- `output_<resolution>.mp4` — Concatenated smooth fragments with subtitles embedded

## Tuning Parameters

### Threshold (`-t, --threshold`)
- Lower values (e.g., 0.3) → stricter filtering, fewer/shorter fragments
- Higher values (e.g., 0.8) → more permissive, longer fragments
- Default: 0.5 (often works well for typical GoPro stabilization)

### Minimum Duration (`-d, --min-duration`)
- Filters out fragments shorter than this value (seconds)
- Use to avoid very short clips
- Default: 3.0

### Sliding Window (`-w, --window`)
- Size of the rolling window for RMS calculation (seconds)
- Larger window → smoother RMS curve, fewer short fragments
- Smaller window → more responsive to quick motion changes
- Default: 1.0

## Troubleshooting

### No fragments detected
- Lower the threshold: `python run_all.py ~/videos -t 0.3`
- Increase min-duration: `python run_all.py ~/videos -d 1.0`
- Check that videos contain CORI telemetry (GoPro stabilization data)

### FFmpeg errors
- Ensure `ffmpeg` and `ffprobe` are installed and in PATH
- Check file permissions and disk space

### Subtitles not visible
- Some video players don't display mov_text subtitles by default
- Try VLC, ffplay, or re-mux with a different subtitle codec if needed

### Slow processing
- Large videos take time; consider reducing window size to speed up RMS calculation
- Fragments are extracted and concatenated in parallel per resolution group

## File Structure

```
gopro/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── noshake.py                     # Fragment detection
├── index_by_resolution.py         # Resolution grouping
├── concatenate_fragments.py       # Fragment extraction & concatenation
├── run_all.py                     # Master runner
└── output/
    ├── index.json                 # Grouped fragments
    ├── output_1920x1080.mp4       # Final concatenated video
    └── _work_1920x1080/           # Intermediate fragments (optional)
```

## License

Use and modify freely for personal use.

## See Also

- [GoPro Telemetry Parser](https://github.com/gopro/gpmf-parser)
- [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
