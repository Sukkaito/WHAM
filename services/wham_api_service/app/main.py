from fastapi import FastAPI

from app.api.router import api_router
from app.core.auth import AuthMiddleware
from app.core.logging import setup_logging
from app.core.token_registry import bootstrap_api_keys
from app.db.session import init_db


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="WHAM Media + Pose API",
        version="0.1.0",
        description=(
            "Phase 1 scaffold for upload/download, pose2d, pose3d, "
            "job status, and lineage association endpoints."
        ),
    )
    app.add_middleware(AuthMiddleware)

    @app.on_event("startup")
    async def _startup() -> None:
        init_db()
        bootstrap_api_keys()

    app.include_router(api_router)
    return app


app = create_app()
