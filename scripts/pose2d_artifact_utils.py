"""Utilities for pose2d tracking artifacts used by extraction and rendering scripts."""

from pathlib import Path

import cv2
import numpy as np


COCO17_EDGES = [
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
]


def pick_best_track(tracking_results: dict):
    """Pick the track with the longest keypoint sequence."""
    best_id = None
    best_len = -1
    for track_id, row in tracking_results.items():
        kps = np.asarray(row.get("keypoints", []))
        if len(kps) > best_len:
            best_len = len(kps)
            best_id = track_id
    return best_id


def build_frame_map(frame_ids: np.ndarray, keypoints: np.ndarray) -> dict[int, int]:
    """Build map: frame_index -> keypoint row index with best confidence per frame."""
    frame_map = {}
    for i, frame_id in enumerate(frame_ids):
        fid = int(frame_id)
        pts = keypoints[i]
        score = float(np.mean(pts[:, 2])) if pts.shape[-1] >= 3 else 0.0
        prev = frame_map.get(fid)
        if prev is None or score > prev[1]:
            frame_map[fid] = (i, score)
    return {fid: idx for fid, (idx, _) in frame_map.items()}


def render_overlay_video(
    video_path: str,
    track_record: dict,
    out_mp4: str,
    score_thr: float = 0.2,
) -> None:
    """Render 2D keypoints overlay video from a single tracking record."""
    kps = np.asarray(track_record["keypoints"])
    frame_ids = np.asarray(track_record.get("frame_id", np.arange(len(kps))), dtype=int)

    if kps.ndim != 3 or kps.shape[-1] < 2:
        raise RuntimeError(f"Unexpected keypoints shape: {kps.shape}")
    if kps.shape[1] < 17:
        raise RuntimeError(f"Joints < 17 (J={kps.shape[1]}), expected COCO-17 compatible data")
    kps = kps[:, :17, :]

    frame_map = build_frame_map(frame_ids, kps)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 10**9

    out_path = Path(out_mp4)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        kps_idx = frame_map.get(frame_idx)
        if kps_idx is not None:
            pts = kps[kps_idx]
            for a, b in COCO17_EDGES:
                xa, ya, sa = pts[a]
                xb, yb, sb = pts[b]
                if sa >= score_thr and sb >= score_thr:
                    cv2.line(frame, (int(xa), int(ya)), (int(xb), int(yb)), (0, 255, 0), 2)
            for x, y, s in pts:
                if s >= score_thr:
                    cv2.circle(frame, (int(x), int(y)), 3, (0, 0, 255), -1)

        vw.write(frame)
        frame_idx += 1
        if frame_idx % 50 == 0:
            print(f"[pose2d_overlay] frame {frame_idx}/{total}")

    cap.release()
    vw.release()
