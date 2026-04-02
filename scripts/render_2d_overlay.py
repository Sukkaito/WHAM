# Deprecated

import argparse
from pathlib import Path
import joblib
import cv2
import numpy as np

# COCO-17 skeleton edges (common)
EDGES = [
    (0,1),(1,2),(2,3),(3,4),      # right arm
    (0,5),(5,6),(6,7),(7,8),      # left arm
    (9,10),(11,12),               # hips
    (5,11),(6,12),                # torso
    (11,13),(13,15),              # left leg
    (12,14),(14,16)               # right leg
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--tracking_pth", required=True)
    ap.add_argument("--out_mp4", required=True)
    ap.add_argument("--id", default=None, help="subject id; default: first key")
    ap.add_argument("--score_thr", type=float, default=0.2)
    args = ap.parse_args()

    tr = joblib.load(args.tracking_pth)
    sid = args.id if args.id is not None else next(iter(tr.keys()))
    r = tr[sid]

    # common key name: 'keypoints'
    kps = r.get("keypoints", None)
    if kps is None:
        raise SystemExit("No 'keypoints' in tracking_results for this id")

    kps = np.asarray(kps)  # (T, J, 3) => x,y,score
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit("Cannot open video")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_path = Path(args.out_mp4)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))

    t = 0
    while True:
        ok, frame = cap.read()
        if not ok or t >= len(kps):
            break

        pts = kps[t]
        # draw edges
        for a,b in EDGES:
            if a < pts.shape[0] and b < pts.shape[0]:
                xa,ya,sa = pts[a]
                xb,yb,sb = pts[b]
                if sa >= args.score_thr and sb >= args.score_thr:
                    cv2.line(frame, (int(xa), int(ya)), (int(xb), int(yb)), (0,255,0), 2)

        # draw joints
        for j,(x,y,s) in enumerate(pts):
            if s >= args.score_thr:
                cv2.circle(frame, (int(x), int(y)), 3, (0,0,255), -1)

        vw.write(frame)
        t += 1
        if t % 50 == 0:
            print(f"[INFO] frame {t}/{len(kps)}")

    cap.release()
    vw.release()
    print("[DONE] wrote:", out_path)

if __name__ == "__main__":
    main()
