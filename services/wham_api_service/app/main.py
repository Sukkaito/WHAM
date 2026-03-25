from fastapi import FastAPI

from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="WHAM Media + Pose API",
        version="0.1.0",
        description=(
            "Phase 1 scaffold for upload/download, pose2d, pose3d, "
            "job status, and lineage association endpoints."
        ),
    )
    app.include_router(api_router)
    return app


app = create_app()
