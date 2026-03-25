---
name: wham-expert
description: 'Use this repository correctly for WHAM demo inference, training stages, and evaluation. Use when selecting entrypoints, mapping arguments, and following repo-specific execution flow and config semantics.'
argument-hint: 'Goal, mode (demo/train/eval/api), input video or checkpoint, config yaml, and desired outputs.'
user-invocable: true
---

# WHAM Expert

## Outcome
This skill guides correct usage of this WHAM repository by choosing the right entrypoint, passing the right arguments, and preserving stage/config behavior.

## When To Use
- Running inference on videos with `demo.py`.
- Running stage 1 or stage 2 training with `train.py`.
- Running evaluation with `lib.eval` modules.
- Mapping programmatic usage to `wham_api.py` behavior.
- Deciding which mode to run based on user intent.

## Runtime Assumptions
- Use repository-relative paths and Linux-oriented command style.
- When an absolute path is needed, use `/mnt/nvme1n1p1/mydata/WHAM` as the workspace root.
- Required assets from `fetch_demo_data.sh` are already available in this workspace.
- Default inference mode is global trajectory estimation.
- `--calib` is optional and usually omitted.

## Trigger Process
Use this branching flow to decide what to run:
1. If user asks to process a custom video, trigger `demo` mode.
2. If user asks to train from scratch/lifting, trigger `train-stage1`.
3. If user asks to finetune with stage1 weights, trigger `train-stage2`.
4. If user asks to benchmark a checkpoint, trigger `eval`.
5. If user asks for programmatic integration, trigger `api` mode and map to `wham_api.py` semantics.

### Mode A: Demo Inference (`demo.py`)
Use this when input is a video file.

Base command:
```bash
python demo.py --video examples/IMG_9732.mov --output_pth output/cam1
```

Optional flags and decision logic:
- Default behavior is global estimation, so do not pass `--estimate_local_only` unless explicitly needed.
- Use `--estimate_local_only` only as fallback when DPVO/SLAM is unavailable.
- Add `--calib <path>` only when known camera intrinsics are available.
- Add `--save_pkl` to produce `wham_output.pkl`.
- Add `--visualize` to render visual output.
- Add `--run_smplify` for post-optimization (slower, usually better alignment).

Important path behavior:
- `demo.py` appends the video stem as a subfolder under `--output_pth`.
- Example: `--output_pth output/cam1` and video `IMG_9730.mov` produces files under `output/cam1/IMG_9730/`.

Example full command:
```bash
python demo.py \
  --video examples/IMG_9732.mov \
  --output_pth output/cam1 \
  --save_pkl \
  --visualize
```

### Mode B: Train Stage 1
```bash
python train.py --cfg configs/yamls/stage1.yaml
```

Use CLI overrides only when needed, for example:
```bash
python train.py --cfg configs/yamls/stage1.yaml TRAIN.BATCH_SIZE 32 TRAIN.END_EPOCH 100
```

### Mode C: Train Stage 2
```bash
python train.py --cfg configs/yamls/stage2.yaml TRAIN.CHECKPOINT checkpoints/wham_stage1.pth.tar
```

### Mode D: Evaluation
3DPW:
```bash
python -m lib.eval.evaluate_3dpw --cfg configs/yamls/demo.yaml TRAIN.CHECKPOINT checkpoints/wham_vit_w_3dpw.pth.tar
```

RICH:
```bash
python -m lib.eval.evaluate_rich --cfg configs/yamls/demo.yaml TRAIN.CHECKPOINT checkpoints/wham_vit_w_3dpw.pth.tar
```

EMDB split 1 or 2:
```bash
python -m lib.eval.evaluate_emdb --cfg configs/yamls/demo.yaml --eval-split 1 TRAIN.CHECKPOINT checkpoints/wham_vit_w_3dpw.pth.tar
```

### Mode E: Programmatic API (`wham_api.py`)
Use when integration code needs direct Python calls.

Behavioral contract:
- Input: `video`, optional `output_dir`, optional `calib`, `run_global`, `visualize`.
- Returns: `results, tracking_results, slam_results`.
- Maintains same global-vs-local fallback pattern used by demo flow.

## Completion Checks
- Demo run creates expected outputs in video-specific folder:
  - `tracking_results.pth`
  - `slam_results.pth`
  - `wham_output.pkl` (if `--save_pkl` is set)
- Training/eval logs show successful config load and checkpoint path resolution.

## Failure Triage
- If DPVO is missing or fails to import, rerun with `--estimate_local_only`.
- If video cannot open, verify the path is valid and readable.
- If checkpoint errors occur, verify filename and path under `checkpoints/`.
- If CUDA errors occur, verify PyTorch CUDA environment and device visibility.

## Notes For Argument Handling
- Keep config precedence unchanged:
  1. Defaults from `configs/config.py`
  2. YAML via `--cfg`
  3. CLI overrides (`TRAIN.*`, `DATASET.*`, etc.)
- Prefer YAML/CLI overrides rather than changing code defaults for runtime variations.
