"""
Extract WHAM preprocessing artifacts without running 3D inference.

Outputs:
- tracking_results.pth: 2D pose tracking data
- slam_results.pth: camera trajectory data for global-coordinate mode

This mirrors demo.py preprocessing while stopping before 3D inference.

Usage:
    python extract_2d_poses.py \\
        --video path/to/video.mp4 \\
        --output_dir output/path \\
        [--device cuda:0] [--estimate_local_only] [--calib calib.txt]
"""
import argparse
import os.path as osp
from pathlib import Path

import cv2
import joblib
import numpy as np
import torch

# WHAM imports
from configs.config import get_cfg_defaults
from lib.models.preproc.detector import DetectionModel

try:
    from lib.models.preproc.slam import SLAMModel

    _run_global = True
except Exception:
    _run_global = False


def main():
    ap = argparse.ArgumentParser(
        description="Extract 2D pose tracking from video"
    )
    ap.add_argument("--video", required=True, type=str, help="Path to input video")
    ap.add_argument(
        "--output_dir", required=True, type=str, help="Output directory for tracking_results.pth"
    )
    ap.add_argument(
        "--device", default="cuda:0", type=str, help="Device for model inference (cuda:0, cpu, etc.)"
    )
    ap.add_argument(
        "--estimate_local_only",
        action="store_true",
        help="Disable global trajectory estimation and produce identity slam_results",
    )
    ap.add_argument(
        "--calib",
        default=None,
        type=str,
        help="Optional calibration file path for SLAM",
    )
    args = ap.parse_args()

    cfg = get_cfg_defaults()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verify input video exists
    if not osp.exists(args.video):
        raise RuntimeError(f"Video not found: {args.video}")

    # Open video and extract metadata
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"[extract_2d_poses] Video: {args.video}")
    print(f"[extract_2d_poses] FPS: {fps}, Length: {length} frames, Resolution: {width}x{height}")
    print(f"[extract_2d_poses] Device: {args.device}")
    print(f"[extract_2d_poses] Output: {output_dir}/tracking_results.pth")
    print(f"[extract_2d_poses] Output: {output_dir}/slam_results.pth")

    run_global = (not args.estimate_local_only) and _run_global
    if not _run_global and not args.estimate_local_only:
        print("[extract_2d_poses] DPVO/SLAM unavailable, falling back to local-only mode")
    print(f"[extract_2d_poses] run_global={run_global}")

    # Initialize detector
    print(f"[extract_2d_poses] Initializing DetectionModel...")
    with torch.no_grad():
        detector = DetectionModel(args.device)
        if run_global:
            slam = SLAMModel(args.video, str(output_dir), width, height, args.calib)
        else:
            slam = None

        # Process video frames
        print(f"[extract_2d_poses] Processing frames...")
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Run 2D pose detection and tracking
            detector.track(frame, fps, length)
            if slam is not None:
                slam.track()

            if (frame_idx + 1) % 50 == 0:
                print(f"[extract_2d_poses] Processed {frame_idx + 1}/{length} frames")
            frame_idx += 1

        cap.release()

        # Finalize tracking results
        print(f"[extract_2d_poses] Finalizing tracking results...")
        tracking_results = detector.process(fps)
        if slam is not None:
            slam_results = slam.process()
        else:
            slam_results = np.zeros((length, 7))
            slam_results[:, 3] = 1.0

    # Save tracking results
    out_path = osp.join(str(output_dir), "tracking_results.pth")
    slam_out_path = osp.join(str(output_dir), "slam_results.pth")
    joblib.dump(tracking_results, out_path)
    joblib.dump(slam_results, slam_out_path)

    # Report statistics
    num_persons = len(tracking_results)
    num_frames_tracked = 0
    for person_id, person_data in tracking_results.items():
        if "keypoints" in person_data:
            num_frames_tracked = max(num_frames_tracked, person_data["keypoints"].shape[0])

    print(f"[extract_2d_poses] Output: {num_persons} person(s), {num_frames_tracked} frame(s) with keypoints")
    print(f"[extract_2d_poses] Saved: {out_path}")
    print(f"[extract_2d_poses] Saved: {slam_out_path}")
    print(f"[extract_2d_poses] Success")


if __name__ == "__main__":
    main()
