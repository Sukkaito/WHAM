# WHAM Media + Pose API Service

This folder contains a FastAPI-based media and pose service for WHAM inference workflows.

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
- `GET /v1/jobs/{job_id}`: Query job status (placeholder).
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

**Directory Layout:**
```
/WHAM_data/videos/          # User-uploaded source videos
/WHAM_data/output/pose2d/   # 2D extraction results and rendered videos
/WHAM_data/output/pose3d/   # 3D inference results (Phase 2 Step 4+)
```
