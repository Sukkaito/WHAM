from fastapi import APIRouter

from app.api.routes.jobs import router as jobs_router
from app.api.routes.videos import router as videos_router
from app.api.routes.health import router as health_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(videos_router, tags=["videos"])
api_router.include_router(jobs_router, tags=["jobs"])
api_router.include_router(health_router, tags=["health"])
