# Project Guidelines

## Code Style
- Use existing Python style in this repository: simple module-level functions, explicit imports, and minimal abstraction.
- Keep changes narrowly scoped; do not refactor broad areas unless requested.
- Preserve naming and stage semantics used in configs and training code (`stage1`, `stage2`, `TRAIN.*`, `DATASET.*`).
- Prefer updating YAML config values or CLI overrides before changing hardcoded defaults.

## Architecture
- Main entrypoints:
  - `demo.py`: inference pipeline for video input.
  - `train.py`: training orchestration.
  - `wham_api.py`: programmatic API wrapper.
- Core model stack lives under `lib/models/` with WHAM network logic in `lib/models/wham.py`.
- Training loop and losses:
  - `lib/core/trainer.py`
  - `lib/core/loss.py`
- Data pipeline and dataset composition:
  - `lib/data/dataloader.py`
  - `lib/data/datasets/`
- Configuration is YACS-based:
  - defaults and argument parsing in `configs/config.py`
  - experiment YAMLs in `configs/yamls/`

## Build And Test
- Environment setup is documented in `docs/INSTALL.md`.
- Treat Linux (Ubuntu-style) setup as the default execution environment.
- Prefer Linux shell commands and paths; avoid adding Windows-specific command variants unless explicitly requested.
- Assume this workspace root path is `/mnt/nvme1n1p1/mydata/WHAM` when absolute paths are required.
- Assume workflows run inside a Docker container image for this project.
- For this workspace, assume assets from `fetch_demo_data.sh` are already available (no re-download needed unless explicitly requested).
- Common setup commands:
  - `pip install -r requirements.txt`
  - `pip install -v -e third-party/ViTPose`
  - DPVO install steps from `docs/INSTALL.md` (requires extra system/compiler constraints).
- Expected assets after demo-data bootstrap:
  - SMPL models under `dataset/body_models/smpl/` (`SMPL_NEUTRAL.pkl`, `SMPL_FEMALE.pkl`, `SMPL_MALE.pkl`)
  - Auxiliary body-model files under `dataset/body_models/`
  - Checkpoints under `checkpoints/` (WHAM weights, HMR2, DPVO, YOLOv8, ViTPose)
  - Demo videos under `examples/`
- Common run commands:
  - Demo: `python demo.py --video <path> --visualize`
  - Train stage 1: `python train.py --cfg configs/yamls/stage1.yaml`
  - Train stage 2: `python train.py --cfg configs/yamls/stage2.yaml TRAIN.CHECKPOINT <stage1_ckpt>`
  - Eval: `python -m lib.eval.evaluate_3dpw --cfg configs/yamls/demo.yaml TRAIN.CHECKPOINT <ckpt>`
- There is no lightweight unit-test suite in this repository; validate changes with targeted script runs relevant to the edited area.

## Conventions
- Config resolution order is important and should be preserved:
  1. defaults (`get_cfg_defaults`)
  2. YAML file (`cfg.merge_from_file`)
  3. CLI overrides (`cfg.merge_from_list`)
- Stage-specific behavior is intentional:
  - Stage 1 and stage 2 use different datasets, optimizer parameter groups, and feature usage.
- Logging and outputs:
  - Use existing logger/TensorBoard flow from `train.py` and `lib/utils/utils.py`.
  - Keep checkpoint and output handling consistent with `prepare_output_dir`.

## Pitfalls
- Do not assume SLAM/DPVO is always available; `--estimate_local_only` and fallback paths are valid workflows.
- Do not change dataset/body-model path expectations casually; training/inference depend on specific directory layouts under `dataset/`.
- Asset bootstrap is based on `fetch_demo_data.sh`; keep downstream path assumptions compatible with files that script places in `dataset/`, `checkpoints/`, and `examples/`.
- Avoid introducing host-specific assumptions that break containerized Linux runs (for example, OS-specific paths or shell syntax).
- Repository includes third-party code under `third-party/`; avoid broad formatting or style rewrites in vendored directories.

## References
- `README.md`
- `docs/INSTALL.md`
- `docs/DATASET.md`
- `docs/API.md`
- `docs/DOCKER.md`