# WHAM API Service Runbook

## Purpose

This service provides authenticated upload/download and pose2d/pose3d job orchestration for WHAM media workflows.

## Required Environment

Set the following variables before starting the service:

- `WHAM_DATA_DIR`
- `WHAM_REPO_DIR`
- `WHAM_DATABASE_URL`
- `WHAM_AUTH_SUBJECT_HEADER`
- `WHAM_AUTH_API_KEY_HEADER`
- `WHAM_BOOTSTRAP_API_KEYS` or `WHAM_BOOTSTRAP_API_KEYS_FILE`
- `WHAM_DOCKER_IMAGE`
- `WHAM_GPU_ID`
- `WHAM_DOCKER_CLEANUP_ENABLED`
- `WHAM_POSE2D_VISUALIZE`
- `WHAM_POSE2D_ESTIMATE_LOCAL_ONLY`
- `WHAM_POSE3D_VISUALIZE`
- `WHAM_POSE3D_ESTIMATE_LOCAL_ONLY`
- `WHAM_POSE3D_SAVE_PKL`
- `WHAM_POSE3D_RUN_SMPLIFY`

## Storage Layout

The service expects the following layout under `WHAM_DATA_DIR`:

- `videos/` for uploaded and derived media
- `dataset/` for model assets
- `checkpoints/` for weights and body-model checkpoints
- `output/` for pose2d and pose3d artifacts

## Authentication

All protected endpoints require:

- `X-WHAM-Subject`
- `X-WHAM-Api-Key`

The API key is checked against the PostgreSQL `api_keys` table. Bootstrap keys may be seeded from the environment or a JSON file on startup.

## Startup Checklist

1. Verify PostgreSQL is reachable.
2. Verify the WHAM data directories exist.
3. Ensure Docker is installed and the GPU runtime is available.
4. Start the FastAPI app.
5. Confirm bootstrap API keys were inserted into `api_keys`.

## Operational Notes

- Upload/download remains filesystem-backed for media storage.
- Job lifecycle state is persisted in PostgreSQL when configured.
- Exited Docker containers are cleaned up after status recording when cleanup is enabled.
- Pose2d and pose3d inference jobs must run through Docker and use the server-owned execution profile.

## Example Verification Flow

1. Upload a video.
2. Submit a pose2d job.
3. Wait for the job status to transition to `succeeded`.
4. Submit a pose3d job using the same source video.
5. Check the association endpoint for both derived outputs.
6. Download the derived media by `video_id`.
