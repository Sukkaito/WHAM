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
    [--device cuda:0] [--estimate_local_only] [--calib calib.txt] \\
    [--visualize] [--save_pkl] [--id 0] [--score_thr 0.2] [--overlay_out output.mp4]
"""
import argparse
import os.path as osp
import sys
import traceback
from pathlib import Path

import cv2
import joblib
import numpy as np
import torch

try:
    from ._bootstrap import ensure_repo_root_on_path
except ImportError:
    from _bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

# WHAM imports
from configs.config import get_cfg_defaults
from lib.models.preproc.detector import DetectionModel
from lib.models.preproc.extractor import FeatureExtractor
from scripts.pose2d_artifact_utils import pick_best_track, render_overlay_video

try:
    from lib.models.preproc.slam import SLAMModel

    _run_global = True
except Exception:
    _run_global = False


def main() -> int:
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
    ap.add_argument(
        "--visualize",
        action="store_true",
        help="Render 2D overlay video from tracking results (like extract_3d visualize flag)",
    )
    ap.add_argument(
        "--save_pkl",
        action="store_true",
        help="Compatibility flag with extract_3d_poses; tracking/slam artifacts are always saved",
    )
    ap.add_argument(
        "--id",
        type=int,
        default=None,
        help="Track id to render; if omitted, the longest track is used",
    )
    ap.add_argument(
        "--score_thr",
        type=float,
        default=0.2,
        help="Confidence threshold for rendered keypoints",
    )
    ap.add_argument(
        "--overlay_out",
        default=None,
        type=str,
        help="Optional overlay output path. Defaults to <output_dir>/pose2d_overlay.mp4",
    )
    args = ap.parse_args()

    cfg = get_cfg_defaults()
    cfg.merge_from_file("configs/yamls/api_cuda.yaml")
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
    print(f"[extract_2d_poses] visualize: {args.visualize}")
    print(f"[extract_2d_poses] save_pkl: {args.save_pkl}")
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
        extractor = FeatureExtractor(args.device.lower(), cfg.FLIP_EVAL)
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

        # Extract image features and init states to match demo preprocessing outputs.
        print(f"[extract_2d_poses] Extracting image features...")
        tracking_results = extractor.run(args.video, tracking_results)

    # Save tracking results
    out_path = osp.join(str(output_dir), "tracking_results.pth")
    slam_out_path = osp.join(str(output_dir), "slam_results.pth")
    joblib.dump(tracking_results, out_path)
    joblib.dump(slam_results, slam_out_path)

    if not isinstance(tracking_results, dict) or len(tracking_results) == 0:
        raise RuntimeError("No person tracks detected in video")

    # Report statistics
    num_persons = len(tracking_results)
    num_frames_tracked = 0
    for person_id, person_data in tracking_results.items():
        if "keypoints" in person_data:
            num_frames_tracked = max(num_frames_tracked, person_data["keypoints"].shape[0])

    print(f"[extract_2d_poses] Output: {num_persons} person(s), {num_frames_tracked} frame(s) with keypoints")
    print(f"[extract_2d_poses] Saved: {out_path}")
    print(f"[extract_2d_poses] Saved: {slam_out_path}")

    if args.visualize:
        if not isinstance(tracking_results, dict) or len(tracking_results) == 0:
            raise RuntimeError("Cannot visualize: tracking_results are empty or invalid")

        track_id = args.id if args.id is not None else pick_best_track(tracking_results)
        if track_id not in tracking_results:
            raise RuntimeError(
                f"Cannot visualize: track id={track_id} not in available ids {list(tracking_results.keys())}"
            )

        overlay_out = args.overlay_out or str(output_dir / "pose2d_overlay.mp4")
        print(f"[extract_2d_poses] Rendering overlay: {overlay_out}")
        render_overlay_video(
            video_path=args.video,
            track_record=tracking_results[track_id],
            out_mp4=overlay_out,
            score_thr=args.score_thr,
        )
        print(f"[extract_2d_poses] Saved: {overlay_out}")

    print(f"[extract_2d_poses] Success")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[extract_2d_poses] Failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
