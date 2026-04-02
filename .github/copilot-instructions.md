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
- API Service layer:
  - `services/wham_api_service/`: FastAPI-based media and pose service.
  - `app/api/routes/`: REST endpoints for video upload/download, pose2d/pose3d jobs, status, and associations.
  - `app/services/`: Domain logic (video_service, pose2d_service, pose3d_service).
  - `app/services/docker_executor.py`: Shared Docker command builders and execution utilities (centralized to avoid duplication).
  - `app/core/settings.py`: Runtime configuration for data paths, GPU, Docker image.

## Build And Test
- Environment setup is documented in `docs/INSTALL.md`.
- Treat Linux (Ubuntu-style) setup as the default execution environment.
- Prefer Linux shell commands and paths; avoid adding Windows-specific command variants unless explicitly requested.
- Assume this workspace root path is `/mnt/e/Code/IT4788/WHAM/WHAM` when absolute paths are required.
- `WHAM_data` folder is expected to be located at `/mnt/e/Code/IT4788/WHAM/WHAM_data` if referenced; do not change this path without updating all relevant configs and code.
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

## API Service Conventions
- **Docker execution**: Use `app/services/docker_executor.py` utilities for all Docker command building (never inline docker commands in service handlers).
  - Import `build_extract_2d_cmd`, `build_extract_3d_cmd`, `build_pose2d_pipeline_cmd` for command construction.
  - Import `execute_docker_blocking`, `execute_docker_detached` for execution; never use subprocess directly.
  - Use `DockerExecResult` to uniformly handle subprocess results (avoids manual return code checks).
- **Service separation**: Keep docker_executor stateless; pose2d_service and pose3d_service own job metadata and persistence logic.
- **Cascading preprocessing**: Pose3d can automatically invoke `build_extract_2d_cmd` to generate preprocessing artifacts if missing; reuse is explicit (via artifact path checks) and logged.
- **GPU and paths**: All paths use host-side mappings from `settings.wham_data_dir` (e.g., `/mnt/e/Code/IT4788/WHAM/WHAM_data`); container paths are always `/code/*`.

## Pitfalls
- Do not assume SLAM/DPVO is always available; `--estimate_local_only` and fallback paths are valid workflows.
- Do not change dataset/body-model path expectations casually; training/inference depend on specific directory layouts under `dataset/`.
- Asset bootstrap is based on `fetch_demo_data.sh`; keep downstream path assumptions compatible with files that script places in `dataset/`, `checkpoints/`, and `examples/`.
- Avoid introducing host-specific assumptions that break containerized Linux runs (for example, OS-specific paths or shell syntax).
- Repository includes third-party code under `third-party/`; avoid broad formatting or style rewrites in vendored directories.
- **In API service**: Do not build Docker commands directly in route handlers or service functions; always use `docker_executor.py` builders.
- **In API service**: Do not concatenate shell commands as strings; use deterministic command builders with structured argument lists.
- **In API service**: Do not leak raw Docker command strings to client responses; return only job_id, status, and error summaries.

## References
- `README.md`
- `docs/INSTALL.md`
- `docs/DATASET.md`
- `docs/API.md`
- `docs/DOCKER.md`
- `.github/skills/wham-api-service/SKILL.md` — API service patterns, Docker pipeline, lineage tracking.
- `docs/API.md`
- `docs/DOCKER.md`