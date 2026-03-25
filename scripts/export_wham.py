import argparse, csv
from pathlib import Path
import numpy as np
import joblib

def to_np(x):
    try:
        import torch
        if isinstance(x, torch.Tensor):
            return x.detach().cpu().numpy()
    except Exception:
        pass
    return np.asarray(x)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wham_pkl", required=True, help="Path to wham_output.pkl")
    ap.add_argument("--out_dir", required=True, help="Output directory")
    ap.add_argument("--body_models", default="/code/dataset/body_models", help="Where J_regressor_wham.npy lives")
    args = ap.parse_args()

    wham_pkl = Path(args.wham_pkl)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = joblib.load(str(wham_pkl))

    # Optional: compute joints3d from verts using regressor (fast, no SMPL needed)
    reg_path = Path(args.body_models) / "J_regressor_wham.npy"
    J = np.load(reg_path) if reg_path.exists() else None
    if J is None:
        print(f"[WARN] Not found: {reg_path}. Will skip joints3d-from-verts export.")
    else:
        print(f"[OK] Loaded regressor: {reg_path} shape={J.shape}")

    for sid, r in data.items():
        sid_dir = out_dir / str(sid)
        sid_dir.mkdir(exist_ok=True)

        # Save common fields if exist
        for k in ["pose", "pose_world", "trans", "trans_world", "betas", "frame_ids"]:
            if k in r:
                np.save(sid_dir / f"{k}.npy", to_np(r[k]))

        # Save verts + joints3d
        if "verts" in r:
            verts = to_np(r["verts"])   # (T, 6890, 3) typically
            np.savez_compressed(sid_dir / "verts.npz", verts=verts)

            if J is not None:
                # joints: (T, J, 3) with einsum (J, V) x (T, V, 3)
                joints = np.einsum("jv,tvc->tjc", J, verts)
                np.save(sid_dir / "joints3d.npy", joints)

                # CSV long format
                with open(sid_dir / "joints3d.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["frame", "joint", "x", "y", "z"])
                    T, JJ, _ = joints.shape
                    for t in range(T):
                        for j in range(JJ):
                            x,y,z = joints[t,j]
                            w.writerow([t, j, float(x), float(y), float(z)])

        # Pack SMPL params for downstream tools (Blender, etc.)
        # poses here are axis-angle SMPL params; not joint positions.
        if ("pose_world" in r) and ("betas" in r) and ("trans_world" in r):
            np.savez(
                sid_dir / "smpl_params.npz",
                poses=to_np(r["pose_world"]),
                betas=to_np(r["betas"]),
                trans=to_np(r["trans_world"]),
                frame_ids=to_np(r.get("frame_ids", np.arange(len(to_np(r["pose_world"]))))),
            )

    print("[DONE] Exported to:", out_dir)

if __name__ == "__main__":
    main()
