import argparse
import json
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np


def _run_extract_2d(video_path: str, output_dir: str) -> None:
    cmd = [
        "python3",
        "scripts/extract_2d_poses.py",
        "--video",
        video_path,
        "--output_dir",
        output_dir,
        "--device",
        "cuda:0",
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "extract_2d_poses.py failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )


def _load_tracking_results(path: str) -> dict:
    return joblib.load(path)


def _select_single_track(tracking_results: dict) -> tuple[str, np.ndarray]:
    if not isinstance(tracking_results, dict) or len(tracking_results) == 0:
        raise RuntimeError("No tracks found in tracking_results.pth")
    if len(tracking_results) != 1:
        raise RuntimeError("Multiple tracks found; expected exactly one tracked person")
    track_id = next(iter(tracking_results.keys()))
    entry = tracking_results[track_id]
    keypoints = np.asarray(entry.get("keypoints", []))
    if keypoints.ndim != 3 or keypoints.shape[-1] < 2:
        raise RuntimeError(f"Unexpected keypoints shape: {keypoints.shape}")
    return track_id, keypoints


def _normalize_keypoints(keypoints: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    coords = keypoints[:, :, :2].astype(np.float32)
    if keypoints.shape[-1] >= 3:
        conf = keypoints[:, :, 2].astype(np.float32)
    else:
        conf = np.ones(coords.shape[:2], dtype=np.float32)

    joint_count = coords.shape[1]
    if joint_count >= 13:
        root = (coords[:, 11] + coords[:, 12]) / 2.0
    else:
        root = coords.mean(axis=1)
    centered = coords - root[:, None, :]

    scale_candidates = []
    if joint_count >= 7:
        scale_candidates.append(np.linalg.norm(coords[:, 5] - coords[:, 6], axis=1))
    if joint_count >= 13:
        scale_candidates.append(np.linalg.norm(coords[:, 11] - coords[:, 12], axis=1))
    if scale_candidates:
        scale_series = np.stack(scale_candidates, axis=0).mean(axis=0)
    else:
        scale_series = np.linalg.norm(centered, axis=2).mean(axis=1)

    valid = scale_series[scale_series > 1e-6]
    scale = float(np.median(valid)) if valid.size else 1.0
    if scale <= 1e-6:
        scale = 1.0

    normalized = centered / scale
    return normalized, conf


def _downsample(sequence: np.ndarray, conf: np.ndarray, max_frames: int) -> tuple[np.ndarray, np.ndarray]:
    length = sequence.shape[0]
    if length <= max_frames:
        return sequence, conf
    idx = np.linspace(0, length - 1, max_frames).astype(int)
    return sequence[idx], conf[idx]


def _frame_distance(a: np.ndarray, a_conf: np.ndarray, b: np.ndarray, b_conf: np.ndarray) -> float:
    diff = a - b
    dist = np.linalg.norm(diff, axis=1)
    weights = np.minimum(a_conf, b_conf)
    total = float(weights.sum())
    if total <= 1e-6:
        return 1e6
    return float((dist * weights).sum() / total)


def _dtw_distance(seq_a: np.ndarray, conf_a: np.ndarray, seq_b: np.ndarray, conf_b: np.ndarray, window: int) -> float:
    n = seq_a.shape[0]
    m = seq_b.shape[0]
    window = max(window, abs(n - m))
    inf = float("inf")
    dp = np.full((n + 1, m + 1), inf, dtype=np.float32)
    dp[0, 0] = 0.0

    for i in range(1, n + 1):
        j_start = max(1, i - window)
        j_end = min(m, i + window)
        for j in range(j_start, j_end + 1):
            cost = _frame_distance(seq_a[i - 1], conf_a[i - 1], seq_b[j - 1], conf_b[j - 1])
            dp[i, j] = cost + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])

    total_steps = n + m
    if total_steps <= 0:
        return float("inf")
    return float(dp[n, m] / total_steps)


def _distance_to_score(distance: float) -> float:
    thresholds = [
        (0.10, 10.0),
        (0.20, 9.5),
        (0.30, 9.0),
        (0.40, 8.5),
        (0.60, 8.0),
        (0.80, 7.5),
        (1.00, 7.0),
        (1.20, 6.5),
        (1.40, 6.0),
        (1.60, 5.5),
        (1.80, 5.0),
        (2.00, 4.5),
        (2.50, 4.0),
        (3.00, 3.5),
        (3.50, 3.0),
        (4.00, 2.5),
        (5.00, 2.0),
        (6.00, 1.5),
        (7.00, 1.0),
    ]
    for limit, score in thresholds:
        if distance <= limit:
            return score
    return 0.0


def _round_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade pose similarity with DTW")
    parser.add_argument("--video_a", required=True, help="Path to first input video")
    parser.add_argument("--video_b", required=True, help="Path to second input video")
    parser.add_argument("--output_dir_a", required=True, help="Output directory for video A artifacts")
    parser.add_argument("--output_dir_b", required=True, help="Output directory for video B artifacts")
    parser.add_argument("--tracking_results_a", required=True, help="Path to tracking_results.pth for video A")
    parser.add_argument("--tracking_results_b", required=True, help="Path to tracking_results.pth for video B")
    parser.add_argument("--score_path", required=True, help="Path to score output JSON")
    parser.add_argument("--max_frames", type=int, default=600, help="Max frames per sequence")
    parser.add_argument("--dtw_window", type=int, default=0, help="DTW window size (0=full)")

    # Not used right now by the script itself, but passed through for logging and potential future use
    parser.add_argument("--slam_results_a", default=None, help="Path to slam_results.pth for video A")
    parser.add_argument("--slam_results_b", default=None, help="Path to slam_results.pth for video B")
    parser.add_argument("--source_video_id_a", default=None, help="Source video id for video A")
    parser.add_argument("--source_video_id_b", default=None, help="Source video id for video B")

    args = parser.parse_args()

    tracking_path_a = Path(args.tracking_results_a)
    tracking_path_b = Path(args.tracking_results_b)

    if not tracking_path_a.is_file():
        Path(args.output_dir_a).mkdir(parents=True, exist_ok=True)
        _run_extract_2d(args.video_a, args.output_dir_a)
    if not tracking_path_b.is_file():
        Path(args.output_dir_b).mkdir(parents=True, exist_ok=True)
        _run_extract_2d(args.video_b, args.output_dir_b)

    if not tracking_path_a.is_file():
        raise RuntimeError(f"tracking_results.pth missing for video A at {tracking_path_a}")
    if not tracking_path_b.is_file():
        raise RuntimeError(f"tracking_results.pth missing for video B at {tracking_path_b}")

    tracking_a = _load_tracking_results(str(tracking_path_a))
    tracking_b = _load_tracking_results(str(tracking_path_b))

    track_id_a, keypoints_a = _select_single_track(tracking_a)
    track_id_b, keypoints_b = _select_single_track(tracking_b)

    seq_a, conf_a = _normalize_keypoints(keypoints_a)
    seq_b, conf_b = _normalize_keypoints(keypoints_b)

    if args.max_frames > 0:
        seq_a, conf_a = _downsample(seq_a, conf_a, args.max_frames)
        seq_b, conf_b = _downsample(seq_b, conf_b, args.max_frames)

    window = args.dtw_window if args.dtw_window > 0 else max(seq_a.shape[0], seq_b.shape[0])
    distance = _dtw_distance(seq_a, conf_a, seq_b, conf_b, window)
    score = _round_half(_distance_to_score(distance))

    score_path = Path(args.score_path)
    score_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "score": score,
        "raw_distance": distance,
        "comparison_method": "dtw",
        "selected_track_ids": [track_id_a, track_id_b],
    }
    # source_video_ids not use for now, thus optional
    if args.source_video_id_a and args.source_video_id_b:
        payload["input_video_ids"] = [args.source_video_id_a, args.source_video_id_b]
    score_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[grade_poses] score={score} raw_distance={distance:.6f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[grade_poses] Failed: {exc}", file=sys.stderr)
        sys.exit(1)
