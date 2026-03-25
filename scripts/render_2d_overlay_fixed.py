import argparse
from pathlib import Path
import numpy as np
import cv2
import joblib

COCO17_EDGES = [
    (0,1),(0,2),(1,3),(2,4),
    (5,6),(5,7),(7,9),(6,8),(8,10),
    (5,11),(6,12),(11,12),
    (11,13),(13,15),(12,14),(14,16),
]

def pick_best_track(tr):
    # Chọn track dài nhất (thường là người chính)
    best_id = None
    best_len = -1
    for tid, r in tr.items():
        kps = np.asarray(r.get("keypoints", []))
        if len(kps) > best_len:
            best_len = len(kps)
            best_id = tid
    return best_id

def build_frame_map(frame_ids, kps):
    """
    Map frame_index -> keypoints index
    Nếu 1 frame có nhiều record (nhiều người), giữ record có mean score cao hơn
    """
    frame_map = {}
    for i, fid in enumerate(frame_ids):
        fid = int(fid)
        pts = kps[i]
        score = float(np.mean(pts[:,2])) if pts.shape[-1] >= 3 else 0.0
        if fid not in frame_map:
            frame_map[fid] = (i, score)
        else:
            if score > frame_map[fid][1]:
                frame_map[fid] = (i, score)
    return {fid: idx for fid,(idx,_) in frame_map.items()}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--tracking_pth", required=True)
    ap.add_argument("--out_mp4", required=True)
    ap.add_argument("--id", type=int, default=None, help="track id muốn vẽ (nếu bỏ trống sẽ auto chọn track dài nhất)")
    ap.add_argument("--score_thr", type=float, default=0.2)
    args = ap.parse_args()

    tr = joblib.load(args.tracking_pth)  # WHAM lưu tracking_results bằng joblib
    if not isinstance(tr, dict) or len(tr) == 0:
        raise SystemExit("tracking_results.pth không hợp lệ hoặc rỗng")

    tid = args.id if args.id is not None else pick_best_track(tr)
    if tid not in tr:
        raise SystemExit(f"Không thấy track id={tid}. Các id có: {list(tr.keys())}")

    r = tr[tid]
    kps = np.asarray(r["keypoints"])  # (T, J, 3)
    frame_ids = np.asarray(r.get("frame_id", np.arange(len(kps))), dtype=int)

    if kps.ndim != 3 or kps.shape[-1] < 2:
        raise SystemExit(f"keypoints shape lạ: {kps.shape}")

    # Nếu J > 17 (hiếm), lấy body 17 điểm đầu (ViTPose coco)
    if kps.shape[1] >= 17:
        kps = kps[:, :17, :]
    else:
        raise SystemExit(f"Joints < 17 (J={kps.shape[1]}), cần skeleton khác")

    frame_map = build_frame_map(frame_ids, kps)

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
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 10**9

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        idx = frame_map.get(t, None)
        if idx is not None:
            pts = kps[idx]
            # edges
            for a, b in COCO17_EDGES:
                xa, ya, sa = pts[a]
                xb, yb, sb = pts[b]
                if sa >= args.score_thr and sb >= args.score_thr:
                    cv2.line(frame, (int(xa), int(ya)), (int(xb), int(yb)), (0,255,0), 2)
            # joints
            for (x, y, s) in pts:
                if s >= args.score_thr:
                    cv2.circle(frame, (int(x), int(y)), 3, (0,0,255), -1)

        vw.write(frame)
        t += 1
        if t % 50 == 0:
            print(f"[INFO] frame {t}/{total}")

    cap.release()
    vw.release()
    print("[DONE] wrote:", out_path)
    print("[INFO] used track id:", tid)

if __name__ == "__main__":
    main()
