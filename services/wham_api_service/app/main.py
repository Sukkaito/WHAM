import os

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.router import api_router
from app.core.auth import AuthMiddleware
from app.core.logging import get_logger, log_event, setup_logging
from app.core.settings import settings
from app.core.token_registry import bootstrap_api_keys
from app.db.session import init_db
from app.services.job_queue import start_job_worker
from app.services.job_requeue import requeue_unfinished_jobs


_logger = get_logger(__name__)


def _configure_backend_auth() -> None:
    backend = settings.execution_backend
    if backend != "runpod":
        return

    api_key = settings.runpod_api_key.strip()
    if not api_key:
        raise RuntimeError(
            "RUNPOD_API_KEY is required when WHAM_EXECUTION_BACKEND=runpod"
        )

    os.environ["RUNPOD_API_KEY"] = api_key
    log_event(_logger, "startup_runpod_auth_configured", backend=backend)


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="WHAM Media + Pose API",
        version="0.1.0",
        description=(
            "Phase 1 scaffold for upload/download, pose2d, pose3d, "
            "job status, and lineage association endpoints."
        ),
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.add_middleware(AuthMiddleware)

    @app.on_event("startup")
    async def _startup() -> None:
        _configure_backend_auth()
        init_db()
        bootstrap_api_keys()
        start_job_worker(worker_count=settings.job_worker_count)
        requeue_unfinished_jobs()

    app.include_router(api_router)

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = openapi_schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["WHAMSubjectHeader"] = {
            "type": "apiKey",
            "in": "header",
            "name": settings.auth_subject_header,
            "description": "Custom subject header required by the WHAM API.",
        }
        security_schemes["WHAMApiKeyHeader"] = {
            "type": "apiKey",
            "in": "header",
            "name": settings.auth_api_key_header,
            "description": "Custom API key header required by the WHAM API.",
        }
        security_requirement = {
            "WHAMSubjectHeader": [],
            "WHAMApiKeyHeader": [],
        }
        public_paths = {"/ping"}
        for path, path_item in openapi_schema.get("paths", {}).items():
            for operation in path_item.values():
                if isinstance(operation, dict):
                    if path in public_paths:
                        operation["security"] = []
                    else:
                        operation.setdefault("security", []).insert(0, security_requirement)

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()
