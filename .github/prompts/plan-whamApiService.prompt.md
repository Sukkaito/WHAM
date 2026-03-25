## Plan: WHAM Media + Pose API Service

Implement a new service under `services/wham_api_service` that supports normal video upload/download, 2D pose rendering, and 3D pose rendering, with PostgreSQL-backed state and explicit source-to-result video associations. Any operation that infers a new video from a source video must run as a Docker job (including both pose2d and pose3d). Any operation that renders a video must run with GPU-enabled Docker execution. Reuse existing WHAM semantics from `demo.py`/`wham_api.py` for pose3d and keep runtime flags server-owned via execution profiles.

**Architectural Note on 2D/3D Pipeline:** Pose2d uses a dedicated extract_2d_poses.py script to generate preprocessing artifacts independent of 3D inference: tracking_results.pth (2D keypoint data) and slam_results.pth (camera trajectory for global-coordinate mode). This separates concerns and makes both artifacts available before 3D processing, enabling flexible pipelining and reuse patterns.

**Steps**
1. Phase 1 - Service skeleton, API surface, and lineage model.
2. Create a new root folder `services/wham_api_service` with a Python package layout for `api`, `service`, `infra`, `db`, and `tests`.
3. Define request/response models for endpoints:
4. `POST /v1/videos/upload` for normal upload.
5. `GET /v1/videos/{video_id}/download` for normal download.
6. `POST /v1/pose2d/jobs` for 2D pose drawing jobs.
7. `POST /v1/pose3d/jobs` for 3D pose drawing jobs.
8. `GET /v1/jobs/{job_id}` for lifecycle status.
9. `GET /v1/videos/{video_id}/associations` for source-to-derived mappings.
10. Add a shared lineage model so every derived output stores `source_video_id`, `result_video_id`, `transform_type` (`pose2d` or `pose3d`), and `job_id`.
11. Phase 2 - Domain and mapping logic.
12. Implement upload service flow: validate media, persist metadata, assign stable `video_id`, and store under `/mnt/nvme1n1p1/mydata/WHAM_data/videos`.
13. Implement download service flow: auth check, existence check, and streamed response.
14. Implement pose2d service flow with dedicated 2D extraction: resolve source video, run extract_2d_poses.py to generate tracking_results.pth (2D pose data artifact with structure {track_id: {keypoints: (T,J,3), frame_id: [...]}, ...}) and slam_results.pth (camera trajectory artifact for global-coordinate mode), invoke render_2d_overlay.py to create overlay video from tracking_results.pth via GPU-enabled Docker job, persist rendered video and both preprocessing artifact locations, and associate with source. Default behavior must be global mode; fallback local-only only when DPVO/SLAM is unavailable.
15. Implement pose3d service mapping from `source_video_id` to server-managed runtime fields: `video`, `output_pth`, `job_id`, `job_name`, `gpu_id`, preprocessing artifact paths (`tracking_results_path`, `slam_results_path`) when available, and execution profile flags (`estimate_local_only`, `visualize`, `save_pkl`, `run_smplify`, `calib`).
16. Encode demo-compatibility rules for pose3d: default global mode, fallback local-only policy when DPVO is unavailable, and output path semantics equivalent to `demo.py` (`output_pth/<video_stem>`).
17. Add deterministic pose3d command builder that generates `docker run` arguments (no raw shell concatenation in handlers), using host data root `/mnt/nvme1n1p1/mydata/WHAM_data`, image `wham-local`, mounts for `dataset`, `checkpoints`, `output`, `videos`, and explicit GPU assignment.
18. Phase 3 - Execution and persistence.
19. Add PostgreSQL persistence for video metadata, job metadata, runtime parameters, lifecycle status, timestamps, exit code, and error summary.
20. Implement async pose2d and pose3d GPU-enabled Docker job launchers that return immediately; persist initial `running` state before launch and update to `succeeded`/`failed` on completion monitoring.
21. Implement status retrieval endpoint returning normalized terminal/running states, source_video_id, and result_video_id when available.
22. Implement association endpoint returning all derived outputs for a source video.
23. Phase 4 - Hardening and operability.
24. Add auth payload validation at boundary (shape and required fields), structured logging, and sanitized error surfaces (never return raw docker command to clients).
25. Enforce policy guardrails: any source-video inference request is rejected unless routed through Docker execution path.
26. Add profile/config module for server-owned defaults (GPU selection strategy for pose2d and pose3d, timeout, retries, local-only fallback policy for pose3d, renderer profile for pose2d) with environment overrides.
27. Add concise runbook docs for local execution, required env vars, PostgreSQL setup, and API examples for upload/download/pose2d/pose3d.
28. Phase 5 - Verification.
29. Add integration-style tests for upload/download success, invalid payload rejection, status lifecycle transitions, Docker command mapping correctness, and failure handling (missing video, renderer failure, container failure).
30. Add explicit tests confirming both pose2d and pose3d inference paths execute through Docker jobs.
31. Perform manual end-to-end verification against one real video in WHAM_data/videos: upload -> pose2d -> pose3d -> download and confirm source association includes both result video IDs.

**Relevant files**
- `/mnt/nvme1n1p1/mydata/WHAM/demo.py` - authoritative CLI/runtime semantics for `--video`, `--output_pth`, and global/local behavior.
- `/mnt/nvme1n1p1/mydata/WHAM/wham_api.py` - reusable programmatic flow and output contract expectations.
- `/mnt/nvme1n1p1/mydata/WHAM/scripts/render_2d_overlay.py` - candidate renderer pipeline for pose2d output generation.
- `/mnt/nvme1n1p1/mydata/WHAM/scripts/render_2d_overlay_fixed.py` - fallback/reference for pose2d rendering behavior.
- `/mnt/nvme1n1p1/mydata/WHAM/configs/config.py` - config precedence patterns to preserve in service defaults.
- `/mnt/nvme1n1p1/mydata/WHAM/lib/utils/utils.py` - logger/output patterns worth mirroring.
- `/mnt/nvme1n1p1/mydata/WHAM/.github/skills/wham-api-service/SKILL.md` - required API-layer behavior and Docker mapping policy.
- New folder to add: `/mnt/nvme1n1p1/mydata/WHAM/services/wham_api_service/` (FastAPI app, domain service, Docker executor, PostgreSQL persistence, docs/tests).

**Verification**
1. Upload/download checks: uploaded video is retrievable by `video_id`.
2. Pose2d checks: submit source video and verify succeeded job with `result_video_id`, `tracking_results.pth`, and `slam_results.pth` (or explicit local-only fallback when DPVO is unavailable).
3. Pose3d checks: submit source video and verify succeeded job with `result_video_id`; in default global mode, confirm slam input is present (reused from pose2d artifact when available or generated by pose3d preprocessing).
4. Command-mapping validation: pose2d and pose3d docker invocations include explicit GPU assignment, match skill constraints, and do not leak command strings in responses.
5. Association checks: querying source video returns both 2D and 3D derived result video IDs when both jobs were run.
6. DB checks: row transitions `running -> succeeded|failed` are durable across API restarts for both pose2d and pose3d.
7. Failure-mode checks: simulate missing source video, renderer failure, unavailable GPU, and DPVO failure path; verify actionable error summaries.
8. Policy checks: verify no source-video inference endpoint can execute without Docker job dispatch, and no rendering endpoint runs without GPU-enabled Docker execution.
9. Note: Pose2d and Pose3d require further verification beyond standard testing (for example runtime stability, artifact quality, and GPU behavior under real workloads).

**Decisions**
- Framework: FastAPI.
- Execution model: async job launch with status endpoint.
- State storage: PostgreSQL (not in-memory/SQLite/Redis).
- New service location: `services/wham_api_service`.
- API includes upload/download plus pose2d/pose3d jobs and association query.
- Runtime flags remain server-owned.
- Pose responses must include source and result video identifiers.
- Rendering jobs must run with server-assigned GPU-enabled Docker runtime.

**Further Considerations**
1. Docker execution strategy recommendation: start with local subprocess-based launcher for `docker run`; upgrade to a job queue/worker only if concurrency/latency pressure appears.
2. Auth recommendation: keep boundary validation now (required fields + format), defer token introspection/integration until downstream auth service contract is finalized.
3. Observability recommendation: include per-job correlation IDs and source/result video IDs in logs from day one to simplify debugging across API, launcher, renderer, and DB updates.
