# WHAM API Service Runbook

## Purpose

This service provides authenticated upload/download and pose2d/pose3d job orchestration for WHAM media workflows.
Execution mode is explicit per deployment (`docker` or `runpod`), and jobs follow fail-fast behavior on launch failure/timeouts.

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
- `WHAM_EXECUTION_BACKEND`
- `RUNPOD_API_KEY`
- `WHAM_RUNPOD_TEMPLATE_ID`
- `WHAM_RUNPOD_IMAGE`
- `WHAM_RUNPOD_POLL_INTERVAL_SECONDS`
- `WHAM_RUNPOD_JOB_TIMEOUT_SECONDS`
- `WHAM_RUNPOD_DELETE_ON_COMPLETION`
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
3. Ensure backend prerequisites are available:
	- `docker` mode: Docker daemon and GPU runtime.
	- `runpod` mode: `runpodctl` authentication and required template/image identifiers.
4. Start the FastAPI app.
5. Confirm bootstrap API keys were inserted into `api_keys`.

## Operational Notes

- Upload/download remains filesystem-backed for media storage.
- Job lifecycle state is persisted in PostgreSQL when configured.
- Exited execution targets are cleaned up after status recording when cleanup is enabled.
- Jobs are fail-fast: launch failures and execution timeouts transition directly to `failed`.
- No cross-mode fallback is performed during job execution.

## Structured Logging

The service emits structured lifecycle events for queue and reconciliation flows. Key events include:

- `job_enqueued`
- `job_worker_cycle_start`
- `job_launch_start`
- `job_launch_succeeded`
- `job_launch_failed`
- `job_inspect_start`
- `job_inspect_result`
- `job_wait_completion`
- `job_completed`
- `startup_requeue_scan`
- `startup_reconcile_running_start`
- `startup_reconcile_inspect_result`
- `startup_reconcile_finalize`

Use `job_id`, `backend`, and `identifier` fields to correlate an incident across the full lifecycle.

## Incident: Quota Exhaustion or Supply Failure (Runpod)

Symptoms:

- Frequent `job_launch_failed` events with quota/capacity terms.
- New jobs remain `failed` shortly after submission.

Operator actions:

1. Confirm Runpod account quota and capacity status.
2. Verify template/image identifiers and GPU type availability.
3. Capture failed job IDs and corresponding `job_launch_failed` log lines.
4. Mark incident severity based on sustained failure rate.
5. Communicate fail-fast behavior to upstream callers (jobs must be resubmitted when capacity is restored).

## Incident: Pod Failure or Timeout (Runpod)

Symptoms:

- `job_completed` with `status=failed`.
- Timeout summaries in job error fields.

Operator actions:

1. Inspect `job_id` logs for `job_launch_*`, `job_inspect_*`, and `job_completed` events.
2. Fetch pod logs for the failed `identifier` if still available.
3. Determine whether the failure is command/configuration/data-related.
4. Document root cause and affected jobs.
5. Re-submit jobs only after corrective action is applied.

## Example Verification Flow

1. Upload a video.
2. Submit a pose2d job.
3. Observe queue lifecycle events in logs for the submitted `job_id`.
4. Wait for the job status to transition to `succeeded` or `failed`.
5. Submit a pose3d job using the same source video.
6. Check the association endpoint for derived outputs.
7. Download derived media by `video_id` when status is `succeeded`.
