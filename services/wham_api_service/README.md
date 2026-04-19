# WHAM Media + Pose API Service

This folder contains a FastAPI-based media and pose service for WHAM inference workflows.

## Quick Start

1. Copy [`.env.example`](.env.example) to `.env` and set at least `WHAM_DATABASE_URL`, `WHAM_AUTH_SUBJECT_HEADER`, `WHAM_AUTH_API_KEY_HEADER`, and the bootstrap API key settings.
2. Ensure the expected WHAM data layout exists under `WHAM_DATA_DIR`:
  - `videos/`
  - `dataset/`
  - `checkpoints/`
  - `output/`
3. Start the service with your normal FastAPI entrypoint.

## Environment Reference

- `WHAM_DATA_DIR`: host root for videos, dataset, checkpoints, and output.
- `WHAM_REPO_DIR`: repository root used for Docker command execution.
- `WHAM_DATABASE_URL`: PostgreSQL connection string for job persistence.
- `WHAM_AUTH_SUBJECT_HEADER`: subject header name, default `X-WHAM-Subject`.
- `WHAM_AUTH_API_KEY_HEADER`: API key header name, default `X-WHAM-Api-Key`.
- `WHAM_BOOTSTRAP_API_KEYS`: optional CSV bootstrap list like `service-a:key-1,service-b:key-2`.
- `WHAM_BOOTSTRAP_API_KEYS_FILE`: optional JSON bootstrap file for API keys.
- `WHAM_DOCKER_CLEANUP_ENABLED`: remove exited job containers after status is recorded.
- `WHAM_POSE2D_VISUALIZE`, `WHAM_POSE3D_VISUALIZE`: server-owned execution defaults.
- `WHAM_POSE2D_ESTIMATE_LOCAL_ONLY`, `WHAM_POSE3D_ESTIMATE_LOCAL_ONLY`: local-only fallback flags.
- `WHAM_POSE3D_SAVE_PKL`, `WHAM_POSE3D_RUN_SMPLIFY`: pose3d runtime profile flags.

## Auth Model

All protected endpoints require these headers:
- `X-WHAM-Subject`
- `X-WHAM-Api-Key`

Keys are verified against the PostgreSQL `api_keys` table, with optional bootstrap loading during startup.

## Implemented in Phase 2

### Core Services
- **video_service.py**: Upload/download flow with stable `video_id` generation, metadata persistence via JSON index, and association tracking.
  - `store_video()`: Accept multipart upload, validate format, persist to `/WHAM_data/videos/`.
  - `get_video()`: Auth check and file streaming.
  - `list_assoc()`: Query source-to-derived video associations.
  
- **pose2d_service.py**: Dedicated 2D pose extraction and rendering pipeline.
  - Separates 2D keypoint detection from 3D inference (does NOT use demo.py).
  - Pipeline: extract_2d_poses.py → tracking_results.pth → render_2d_overlay.py → result video.
  - Generated 2D data (tracking_results.pth) available for downstream use by pose3d.
  - Runs via GPU-enabled Docker job.

- **pose3d_service.py**: PendingImplementation (Phase 2 Step 4).
  - Will use demo.py with server-managed WHAM parameters.
  - Can optionally consume 2D data from completed pose2d jobs.

### API Endpoints
- `POST /v1/videos/upload`: Multipart upload with file validation.
- `GET /v1/videos/{video_id}/download`: Auth-gated file streaming.
- `POST /v1/pose2d/jobs`: Submit 2D pose extraction/rendering job.
- `POST /v1/pose3d/jobs`: Submit 3D pose inference job (placeholder).
- `GET /v1/jobs`: List jobs with optional filters.
- `GET /v1/jobs/{job_id}`: Query job status (placeholder).
- `POST /v1/jobs/{job_id}/cancel`: Cancel a queued or running job.
- `GET /v1/videos/{video_id}/associations`: List derived videos from source.

### 2D/3D Architecture

**Pose2D Pipeline:**
```
source_video → extract_2d_poses.py → tracking_results.pth
                                  ↓
                         render_2d_overlay.py → result_video
```
- 2D keypoints stored in output/pose2d/{job_id}/{stem}/tracking_results.pth
- Overlay video stored in output/pose2d/{job_id}/{stem}/{result_id}.mp4
- Both paths persisted in job metadata for downstream use

**Pose3D Pipeline (forthcoming):**
- Will read source video or optionally reference 2D data from pose2d
- Output structure: output/pose3d/{job_id}/{stem}/

### Storage

Video storage remains on the existing filesystem-backed setup for now:
- source and derived media live under `/WHAM_data/videos/`
- video metadata and lineage associations continue to use the JSON index at `/WHAM_data/videos/.video_index.json`

Job lifecycle state is PostgreSQL-backed when `WHAM_DATABASE_URL` is configured. If the database URL is not set, the service falls back to the current JSON job index so the API remains usable during incremental rollout.

## API Notes

- `POST /v1/videos/upload`: multipart upload with `file` plus auth headers.
- `GET /v1/videos/{video_id}/download`: download with auth headers.
- `POST /v1/pose2d/jobs`: JSON body with `source_video_id` plus auth headers.
- `POST /v1/pose3d/jobs`: JSON body with `source_video_id` plus auth headers.
- `GET /v1/jobs`: list jobs for the authenticated subject with filters `status`, `job_type`, `source_video_id`, `result_video_id`, `execution_backend`, `limit`, and `offset`.
- `GET /v1/jobs/{job_id}`: job lifecycle lookup.
- `POST /v1/jobs/{job_id}/cancel`: cancel a queued/running job for an authorized source owner.
- `GET /v1/videos/{video_id}/associations`: source-to-derived lineage query.
- `GET /v1/jobs/{job_id}/artifacts/download`: zip download of the source video and all derived artifacts for a job under the current `WHAM_data` layout.

## PostgreSQL Setup

Create the database and set `WHAM_DATABASE_URL` to a SQLAlchemy URL such as:

```text
postgresql+psycopg://wham:wham@localhost:5432/wham
```

On startup the service creates the required tables if the database is reachable. This includes job state and persisted API keys.

## Example Requests

Upload:

```bash
curl -X POST http://localhost:8000/v1/videos/upload \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1' \
  -F 'file=@examples/IMG_9732.mov'
```

Pose2D job:

```bash
curl -X POST http://localhost:8000/v1/pose2d/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1' \
  -d '{"source_video_id":"vid_123"}'
```

Pose3D job:

```bash
curl -X POST http://localhost:8000/v1/pose3d/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1' \
  -d '{"source_video_id":"vid_123"}'
```

Job status:

```bash
curl http://localhost:8000/v1/jobs/job_123 \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1'
```

List jobs (with filters):

```bash
curl 'http://localhost:8000/v1/jobs?status=queued&job_type=pose2d&limit=20&offset=0' \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1'
```

Cancel job:

```bash
curl -X POST http://localhost:8000/v1/jobs/job_123/cancel \
  -H 'X-WHAM-Subject: service-a' \
  -H 'X-WHAM-Api-Key: key-1'
```

**Directory Layout:**
```
/WHAM_data/videos/          # User-uploaded source videos
/WHAM_data/output/pose2d/   # 2D extraction results and rendered videos
/WHAM_data/output/pose3d/   # 3D inference results (Phase 2 Step 4+)
```

The artifacts download endpoint preserves these relative paths inside the zip archive, so the bundle mirrors the existing `WHAM_data` folder structure.
