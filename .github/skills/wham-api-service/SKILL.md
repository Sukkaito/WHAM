---
name: wham-api-service
description: 'Design and run a WHAM media and pose API service: video upload/download, 2D pose extraction+rendering, and 3D pose inference via Docker+separate extraction scripts. Use when mapping API payloads to extraction pipelines, preserving source-result video lineage, and orchestrating cascading 2D→3D preprocessing.'
argument-hint: 'Feature goal (upload/download/pose2d/pose3d), source video id or upload payload, auth context, and internal execution profile.'
user-invocable: true
---

# WHAM Media + Pose API Service Pipeline

## Outcome
Use this skill to implement and operate a production-oriented media and pose flow:
REST API -> service layer -> media store + extraction execution -> status and artifacts.

This skill enforces explicit source-to-derived video linkage for both 2D and 3D outputs, uses dedicated extraction scripts (extract_2d_poses.py, extract_3d_poses.py) instead of demo.py, and implements cascading preprocessing: 2D artifacts are generated on-demand if missing, then 3D inference proceeds.

## When To Use
- Building endpoints for normal video upload and download.
- Building 2D pose extraction jobs that generate tracking_results.pth (2D pose data) and render overlay videos.
- Building 3D pose drawing jobs that run WHAM via Docker (wham-local).
- Returning stable video identifiers that link source videos to result videos.
- Standardizing request validation, defaults, and completion checks.
- Consuming 2D pose data from pose2d jobs for downstream rendering or 3D inference.

## Runtime Assumptions
- Linux-oriented command execution.
- Host workspace root is `/mnt/nvme1n1p1/mydata/WHAM`.
- Docker image is wham-local.
- In-container working directory is /code.
- Rendering workloads require GPU acceleration.
- Required volumes exist and are mounted:
  - /code/dataset
  - /code/checkpoints
  - /code/output
  - /videos
- Host data root is `/mnt/nvme1n1p1/mydata/WHAM_data` with subfolders `dataset`, `checkpoints`, `output`, `videos`.
- Global trajectory estimation is the default.
- Calibration is optional and usually omitted in this workflow.

## Pose2D Pipeline Details
**Pose2D generates two key artifacts:**
1. `tracking_results.pth` - Core 2D pose data (keypoints, tracking IDs, frame mapping)
2. `slam_results.pth` - Camera trajectory data required for global-coordinate behavior
3. Rendered overlay video - Visualization of 2D poses on original video frames

**Pose2D data structure (tracking_results.pth):**
- Format: joblib-serialized dict
- Structure: `{track_id: {"keypoints": np.array(T, J, 3), "frame_id": [...], ...}, ...}`
- keypoints: (num_frames, num_joints, 3) where dim is (x, y, confidence_score)
- Multiple persons tracked as separate track_ids
- Used by render_2d_overlay.py for visualization and available for downstream use

**Pose2D camera trajectory structure (slam_results.pth):**
- Format: joblib-serialized numpy array
- Shape: (num_frames, 7)
- Semantics: per-frame camera state used by WHAM global-coordinate mode
- Default behavior: generated in pose2d preprocessing (global mode)
- Fallback behavior: if DPVO/SLAM is unavailable, local-only fallback is used with identity-like trajectory

## Inference Execution Policy
- Any operation that infers a new video from a source video MUST run as a Docker job.
- This policy applies to both `pose2d` (2D pose extraction) and `pose3d` (3D pose inference).
- Any operation that renders a video MUST request and use a GPU-assigned Docker runtime.
- Upload and download flows are not inference operations and do not require Docker jobs.

## Source Of Truth For 3D Inference Parameters
Mirror extract_3d_poses.py arguments and defaults for pose3d:
- video (required - source video file)
- output_dir (required - directory containing preprocessing artifacts from extract_2d_poses.py)
- visualize (optional bool, default: false)
- save_pkl (optional bool, default: false)
- run_smplify (optional bool, default: false)
- device (optional, default: cuda:0)

Preprocessing artifacts (extracted by extract_2d_poses.py):
- tracking_results.pth (required - 2D pose data)
- slam_results.pth (required - camera trajectory for global-coordinate mode)

API boundary policy:
- Callers must not provide low-level extraction runtime flags.
- Runtime flags are selected by server-owned execution profile.

Note on cascading preprocessing:
- If preprocessing artifacts are missing from output_dir, extract_2d_poses.py is automatically invoked first.
- The service runs extract_2d_poses.py to generate both tracking_results.pth and slam_results.pth, then runs extract_3d_poses.py.

## Canonical API Surface

### Upload Endpoint
`POST /v1/videos/upload`

Example request fields:
```json
{
  "auth": {
    "subject": "service-A",
    "token": "opaque-token"
  },
  "filename": "IMG_9730.mov"
}
```

Expected response fields:
```json
{
  "video_id": "vid_01HR...",
  "filename": "IMG_9730.mov",
  "status": "stored"
}
```

### Download Endpoint
`GET /v1/videos/{video_id}/download`

Returns the original or derived video stream by `video_id` after authorization.

### Pose2D Job Submit
`POST /v1/pose2d/jobs`

Request:
```json
{
  "source_video_id": "vid_01HR...",
  "auth": {
    "subject": "service-A",
    "token": "opaque-token"
  }
}
```

### Pose3D Job Submit
`POST /v1/pose3d/jobs`

Request:
```json
{
  "source_video_id": "vid_01HR...",
  "auth": {
    "subject": "service-A",
    "token": "opaque-token"
  }
}
```

### Job Status
`GET /v1/jobs/{job_id}`

### Association Query
`GET /v1/videos/{video_id}/associations`

Server-managed fields (not client inputs):
- video path (resolved from source_video_id, for example /videos/IMG_9730.mov)
- transform_type (`pose2d` or `pose3d`)
- job_name
- job_id
- result_video_id (when job succeeds)
- output_pth (computed dynamically, for example from video id + job id)
- gpu_id
- estimate_local_only
- visualize
- save_pkl
- run_smplify
- calib

## End-To-End Procedure
1. REST API layer
- Accept upload/download/pose request payload.
- Validate required identifiers and auth payload.
- Generate server-side metadata for tracking:
  - job_id
  - job_name
  - output_pth (for pose jobs; dynamic and not client-provided)

2. Service layer
- Enforce business rules and branching:
  - Upload: store file and persist canonical source video row.
  - Download: resolve video path from video_id and stream file.
  - Pose2D: resolve source video, run preprocessing through a Docker job to generate tracking_results.pth and slam_results.pth (global mode by default), render overlay video, create derived video row.
  - Pose3D: resolve source video, select server-owned execution profile, invoke Docker WHAM job with GPU assignment, create derived video row.
  - Default estimate_local_only=false (global mode) for pose2d preprocessing and pose3d inference.
  - If DPVO is known unavailable, force estimate_local_only=true fallback and keep generating tracking_results.pth.
  - Default estimate_local_only=false (global mode) for pose3d.
  - If DPVO is known unavailable, force estimate_local_only=true for pose3d.
  - Keep calib unset unless configured by internal profile.
- Build deterministic output directories rooted at /code/output for pose jobs.
- Persist lineage links between source_video_id and result_video_id.

3. Pose2D job layer
- Run 2D pose extraction (extract_2d_poses.py) and overlay rendering (render_2d_overlay.py) as an asynchronous Docker job.
- First step: generate tracking_results.pth (2D pose data) via dedicated extraction script.
- First step also generates slam_results.pth (camera trajectory) for global-coordinate downstream use.
- Second step: use tracking_results.pth to render overlay video via render_2d_overlay.py.
- Assign GPU device/environment for the container runtime.
- Persist tracking_results.pth path, slam_results.pth path, and rendered video path.
- Capture stdout/stderr and exit code.
- Mark result video as derived from source video.

4. Pose3D Docker job layer
- Check if preprocessing artifacts (tracking_results.pth, slam_results.pth) exist in the output directory.
- If missing, run extract_2d_poses.py in a Docker container to generate them (global mode by default).
- Run extract_3d_poses.py in a Docker container for WHAM 3D inference on the preprocessing artifacts.
- Assign GPU device/environment for the container runtimes.
- Capture stdout/stderr and exit code from both extraction steps.
- Mark result video as derived from source video.
- Separation of concerns: 2D preprocessing is decoupled from 3D inference for independent monitoring and reuse.

## Docker Command Template

### 2D Extraction + Rendering (Pose2D)
```bash
WHAM_DATA_DIR="/mnt/nvme1n1p1/mydata/WHAM_data"
JOB_ID="job_abc123"
GPU_ID=0

# Extract 2D poses and SLAM trajectory
docker run --rm --platform linux/amd64 \
  --gpus "device=${GPU_ID}" \
  -e CUDA_VISIBLE_DEVICES="${GPU_ID}" \
  -e PYTHONUNBUFFERED=1 \
  -v "${WHAM_DATA_DIR}/dataset":/code/dataset \
  -v "${WHAM_DATA_DIR}/checkpoints":/code/checkpoints \
  -v "${WHAM_DATA_DIR}/output":/code/output \
  -v "${WHAM_DATA_DIR}/videos":/videos \
  -w /code \
  wham-local \
  bash -lc "python3 scripts/extract_2d_poses.py \
    --video /videos/IMG_9730.mov \
    --output_dir output/pose2d/${JOB_ID}/IMG_9730 \
    --device cuda:0"

# Render 2D overlay video
docker run --rm --platform linux/amd64 \
  --gpus "device=${GPU_ID}" \
  -e CUDA_VISIBLE_DEVICES="${GPU_ID}" \
  -e PYTHONUNBUFFERED=1 \
  -v "${WHAM_DATA_DIR}/dataset":/code/dataset \
  -v "${WHAM_DATA_DIR}/checkpoints":/code/checkpoints \
  -v "${WHAM_DATA_DIR}/output":/code/output \
  -v "${WHAM_DATA_DIR}/videos":/videos \
  -w /code \
  wham-local \
  bash -lc "python3 scripts/render_2d_overlay.py \
    --video /videos/IMG_9730.mov \
    --output_dir output/pose2d/${JOB_ID}/IMG_9730 \
    --device cuda:0"
```

### 3D Pose Inference (Pose3D) with Cascading Preprocessing

**Step 1: Check for preprocessing artifacts and extract if needed**
```bash
WHAM_DATA_DIR="/mnt/nvme1n1p1/mydata/WHAM_data"
JOB_ID="job_xyz789"
GPU_ID=0
OUTPUT_DIR="output/pose3d/${JOB_ID}/IMG_9730"

# Extract 2D poses if not already present
if [ ! -f "${WHAM_DATA_DIR}/output/${OUTPUT_DIR}/tracking_results.pth" ]; then
  docker run --rm --platform linux/amd64 \
    --gpus "device=${GPU_ID}" \
    -e CUDA_VISIBLE_DEVICES="${GPU_ID}" \
    -e PYTHONUNBUFFERED=1 \
    -v "${WHAM_DATA_DIR}/dataset":/code/dataset \
    -v "${WHAM_DATA_DIR}/checkpoints":/code/checkpoints \
    -v "${WHAM_DATA_DIR}/output":/code/output \
    -v "${WHAM_DATA_DIR}/videos":/videos \
    -w /code \
    wham-local \
    bash -lc "python3 scripts/extract_2d_poses.py \
      --video /videos/IMG_9730.mov \
      --output_dir ${OUTPUT_DIR} \
      --device cuda:0"
fi
```

**Step 2: Run 3D pose inference on preprocessing artifacts**
```bash
docker run --rm --platform linux/amd64 \
  --gpus "device=${GPU_ID}" \
  -e CUDA_VISIBLE_DEVICES="${GPU_ID}" \
  -e PYTHONUNBUFFERED=1 \
  -v "${WHAM_DATA_DIR}/dataset":/code/dataset \
  -v "${WHAM_DATA_DIR}/checkpoints":/code/checkpoints \
  -v "${WHAM_DATA_DIR}/output":/code/output \
  -v "${WHAM_DATA_DIR}/videos":/videos \
  -w /code \
  wham-local \
  bash -lc "python3 scripts/extract_3d_poses.py \
    --video /videos/IMG_9730.mov \
    --output_dir ${OUTPUT_DIR} \
    --device cuda:0 \
    --save_pkl"
```

Notes:
- Set `WHAM_DATA_DIR` before `docker run` to switch host-side data root without changing mount structure.
- Expected subfolders under `WHAM_DATA_DIR`: `dataset`, `checkpoints`, `output`, `videos`.
- extract_2d_poses.py generates both tracking_results.pth and slam_results.pth in output_dir.
- extract_3d_poses.py requires both .pth files to exist; it validates prerequisites and errors if missing.
- Service layer (pose3d_service.py) automateshe cascading: checks for artifacts, runs extract_2d_poses if needed, then runs extract_3d_poses.

## Parameter Mapping Rules
### Pose2D
- source_video_id -> resolve to input video path for 2D extraction.
- result_video_id -> assigned server-side for rendered overlay video.
- tracking_results_path -> computed server-side path for 2D pose data (output/pose2d/{job_id}/{stem}/tracking_results.pth).
- slam_results_path -> computed server-side path for camera trajectory data (output/pose2d/{job_id}/{stem}/slam_results.pth).
- execution mode -> server-enforced Docker job dispatch with GPU (not a client request parameter).
- gpu_id -> selected by server scheduler/profile, not client input.

### Pose3D
- source_video_id -> resolve to --video using service mapping (for example /videos/{source_video_filename})
- output_dir -> computed server-side path for extract_3d_poses.py (for example output/pose3d/{job_id}/{stem})
- visualize/save_pkl/run_smplify -> set by internal execution profile only
- gpu_id -> selected by server scheduler/profile, not client input
- extract_2d_poses.py -> invoked automatically if preprocessing artifacts are missing
- extract_3d_poses.py -> always invoked after preprocessing artifacts are guaranteed to exist

### Upload/Download
- upload -> assign stable `video_id` and persist metadata.
- download -> resolve file by `video_id` and stream bytes.

## Response Contract Guidance
Return job-oriented responses for pose2d and pose3d:
- job_id
- job_name
- transform_type
- source_video_id
- result_video_id (present on terminal success)
- container_name (pose3d only)
- output directory
- status: running

Do not return the resolved Docker command to client responses.

Use a separate job-status query flow to report terminal states:
- running
- succeeded
- failed
- error summary when failed

Return association responses so callers can map source media to derived results:
- source_video_id
- derived_videos: array of `{result_video_id, transform_type, job_id, status}`

## Completion Checks
- Upload request stores media and returns stable source `video_id`.
- Download request returns stream for valid `video_id`.
- Pose2D request returns running status immediately with job_id and source_video_id.
- Pose2D Docker job starts successfully with expected mounts and GPU visibility.
- Pose3D request returns running status immediately with job_id and source_video_id.
- Pose3D extraction layer checks for preprocessing artifacts and cascades:
  - If missing: runs extract_2d_poses.py first to generate tracking_results.pth and slam_results.pth
  - Then: runs extract_3d_poses.py for WHAM inference on the artifacts
- Pose jobs exit with code 0 on success.
- Pose2D Docker job produces:
  - tracking_results.pth with structure {track_id: {"keypoints": (T,J,3), "frame_id": [...]}, ...}
  - slam_results.pth with per-frame camera trajectory for global-coordinate mode
  - Rendered overlay video with 2D skeleton visualization
- Pose3D Docker job produces:
  - tracking_results.pth (generated by extract_2d_poses.py if not pre-existing)
  - slam_results.pth (generated by extract_2d_poses.py if not pre-existing)
  - wham_output.pkl when save_pkl=true (output of extract_3d_poses.py)
- Pose2D and pose3d both register result_video_id linked to source_video_id.
- Pose2D job metadata includes tracking_results_path and slam_results_path for downstream consumption.
- Association query reports all derived videos for the same source video.

## Failure Triage
- Upload failure: verify request content type, file size limits, and storage path permissions.
- Download failure: verify video_id exists and caller is authorized.
- Pose2D extraction failure: verify DetectionModel dependencies (ViTPose, YOLOv8, HMR2) and input video readability.
- Pose2D rendering failure: verify render_2d_overlay.py dependencies and tracking_results.pth format.
- Pose2D GPU failure: verify Docker GPU runtime and assigned device visibility.
- Pose3D preprocessing extraction failure (extract_2d_poses.py): verify DetectionModel dependencies and input video readability.
- Pose3D inference failure (extract_3d_poses.py): verify prerequisites exist (tracking_results.pth, slam_results.pth) and WHAM dependencies.
- Pose3D artifact validation failure: verify extract_3d_poses.py prerequisite check (error if .pth files missing).
- Pose3D GPU failure: verify Docker GPU runtime, device selection, and host driver stack.
- Missing checkpoint/body-model files: verify dataset/checkpoints mounts.
- CUDA failure: verify Docker GPU runtime, device selection, and host driver stack.
- Timeout or OOM: retry with reduced concurrency or disable visualize/run_smplify.

## Quality Criteria
- Input-to-command mapping is deterministic and logged.
- No hidden parameter translation; demo.py semantics remain intact for pose3d.
- All source-video inference (`pose2d`, `pose3d`) is executed via Docker jobs.
- All video rendering paths (`pose2d`, `pose3d`) run with GPU-enabled Docker execution.
- One pose3d request corresponds to one isolated Docker job.
- Pose2D and pose3d responses always include source_video_id and result_video_id on success.
- Source-to-derived lineage is queryable for downstream services.
- Client responses never expose raw command strings.
- Errors are surfaced to API callers with actionable messages.
