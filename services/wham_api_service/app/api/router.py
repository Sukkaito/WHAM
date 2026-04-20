from fastapi import APIRouter

from app.api.routes.jobs import router as jobs_router
from app.api.routes.videos import router as videos_router
from app.api.routes.health import router as health_router

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(videos_router, tags=["videos"])
v1_router.include_router(jobs_router, tags=["jobs"])

api_router = APIRouter()
api_router.include_router(v1_router)
api_router.include_router(health_router, tags=["health"])
