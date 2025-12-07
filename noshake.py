import json
import argparse
import subprocess
import numpy as np
from pathlib import Path
from py_gpmf_parser.gopro_telemetry_extractor import GoProTelemetryExtractor
from scipy.spatial.transform import Rotation as R


# ------------------ CORE FUNCTIONS ------------------

def extract_cori_quats(video_path):
    ext = GoProTelemetryExtractor(str(video_path))
    ext.open_source()
    try:
        q, t = ext.extract_data("CORI")
    finally:
        ext.close_source()

    q = np.asarray(q)
    t = np.asarray(t)

    if q.ndim == 1:
        q = q.reshape(1, 4)

    return q, t


def cori_sliding_rms(video_path, sliding_window_s=1.0):
    """
    Returns:
      t              → timestamps
      angle_deg      → per-frame rotation angle
      sliding_rms    → sliding RMS of angle_deg
    """
    q_wxyz, t = extract_cori_quats(video_path)
    if q_wxyz.size == 0:
        return None, None, None

    # Convert to scipy xyz-w
    q_xyzw = q_wxyz[:, [1,2,3,0]]
    R_all = R.from_quat(q_xyzw)

    # Frame-to-frame relative rotation
    if len(R_all) > 1:
        R_prev = R_all[:-1]
        R_curr = R_all[1:]
        R_rel = R_curr * R_prev.inv()
        rotvecs = R_rel.as_rotvec()
        angle_deg = np.concatenate([[0.0], np.degrees(np.linalg.norm(rotvecs, axis=1))])
    else:
        angle_deg = np.array([0.0])

    # Frame-to-frame acceleration
    if len(R_rel) > 1:
        a_prev = R_rel[:-1]
        a_curr = R_rel[1:]
        accel = a_curr * a_prev.inv()
        avecs = accel.as_rotvec()
        angle_acc = np.concatenate([[0.0, 0.0], np.degrees(np.linalg.norm(avecs, axis=1))])
    else:
        angle_acc = np.array([0.0, 0.0])

    # Sampling frequency
    dt = np.median(np.diff(t)) if len(t) > 1 else 1.0
    fs = 1.0 / dt

    # ---- Sliding RMS ----
    win_samples = max(1, int(sliding_window_s * fs))
    sq = angle_acc ** 2
    kernel = np.ones(win_samples) / win_samples
    sliding_rms = np.sqrt(np.convolve(sq, kernel, mode='same'))
    half_len = win_samples // 2
    sliding_rms = np.concatenate([sliding_rms[half_len:len(t)], [sliding_rms[-1]] * half_len])  # Ensure same length

    return t, angle_deg, angle_acc, sliding_rms


# ------------------ VIDEO METADATA ------------------

def extract_video_resolution(video_path):
    """
    Extract video resolution using ffprobe, accounting for rotation.
    If rotation is 90° or 270°, swap width and height to reflect logical dimensions.
    Returns: {"width": int, "height": int} or None if extraction fails
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "stream_side_data=rotation",
                "-of", "json",
                str(video_path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        data = json.loads(result.stdout)
        if data.get("streams") and len(data["streams"]) > 0:
            stream = data["streams"][0]
            width = stream.get("width")
            height = stream.get("height")
            rotation = stream.get("side_data_list", [{}])[0].get("rotation", 0)

            # If rotation is 90 or 270, swap dimensions (logical dimensions)
            if rotation in (90, 270, -90, -270):
                width, height = height, width
            
            return {
                "width": width,
                "height": height
            }
    except Exception as e:
        print(f"  Warning: Could not extract resolution: {e}")
    return None

def extract_creation_datetime(video_path):
    """
    Extract creation date/time from video metadata using ffprobe.
    Returns: ISO format datetime string or None if extraction fails
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format_tags=creation_time",
                "-of", "json",
                str(video_path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        data = json.loads(result.stdout)
        creation_time = data.get("format", {}).get("tags",{}).get("creation_time")
        return creation_time
    except Exception as e:
        print(f"  Warning: Could not extract creation time: {e}")
    return None


# ------------------ FRAGMENT DETECTION ------------------

def find_fragments(time, signal, threshold, min_duration_s):
    """
    time     → array of timestamps
    signal   → sliding RMS values
    threshold → maximum value to consider "smooth" (no shake)
    min_duration_s → minimum fragment length in seconds (e.g. 3s)

    Returns list of dicts: [{start: t0, end: t1}, ...]
    """
    if time is None or signal is None:
        return []

    below = signal < threshold
    fragments = []

    i = 0
    N = len(signal)
    while i < N:
        if below[i]:
            start_idx = i
            while i < N and below[i]:
                i += 1
            end_idx = i - 1

            # Convert indices to time
            t0 = float(time[start_idx])
            t1 = float(time[end_idx])

            if t1 - t0 >= min_duration_s:
                fragments.append({"start": t0, "end": t1})
        else:
            i += 1

    return fragments


# ------------------ DIRECTORY PROCESSOR ------------------

def process_directory(
    directory,
    threshold=0.5,          # sliding_rms threshold
    min_duration_s=3.0,     # min fragment length
    sliding_window_s=1.0
):
    directory = Path(directory)

    for mp4 in directory.glob("*.MP4"):
        print(f"Processing {mp4.name}...")

        t, angle_deg, angle_acc, sliding_rms = cori_sliding_rms(
            mp4,
            sliding_window_s=sliding_window_s
        )

        fragments = find_fragments(
            t,
            sliding_rms,
            threshold=threshold,
            min_duration_s=min_duration_s
        )

        # Extract resolution
        resolution = extract_video_resolution(mp4)

        # Extract creation datetime
        creation_datetime = extract_creation_datetime(mp4)

        # Prepare output data
        output_data = {
            "video": mp4.name,
            "resolution": resolution,
            "creation_datetime": creation_datetime,
            "fragments": fragments
        }

        # Write JSON
        out_json = mp4.with_suffix(".json")
        with open(out_json, "w") as f:
            json.dump(output_data, f, indent=2)

        print(f"  -> {len(fragments)} fragments found")
        if resolution:
            print(f"  -> Resolution: {resolution['width']}x{resolution['height']}")
        if creation_datetime:
            print(f"  -> Created: {creation_datetime}")
        print(f"  -> written to {out_json}")


# ------------------ MAIN ------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect shaky video fragments in GoPro MP4 files using CORI telemetry"
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Path to directory containing MP4 files"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.5,
        help="Sliding RMS threshold for shake detection (default: 0.5)"
    )
    parser.add_argument(
        "-d", "--min-duration",
        type=float,
        default=3.0,
        dest="min_duration_s",
        help="Minimum fragment duration in seconds (default: 3.0)"
    )
    parser.add_argument(
        "-w", "--window",
        type=float,
        default=1.0,
        dest="sliding_window_s",
        help="Sliding window size in seconds (default: 1.0)"
    )

    args = parser.parse_args()

    process_directory(
        directory=args.directory,
        threshold=args.threshold,
        min_duration_s=args.min_duration_s,
        sliding_window_s=args.sliding_window_s
    )


if __name__ == "__main__":
    main()

