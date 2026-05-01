import logging

from fastapi import APIRouter, status

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/ping", status_code=status.HTTP_200_OK)
def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    logger.info("Health check requested")
    return {"status": "ok"}