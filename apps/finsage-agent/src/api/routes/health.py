from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Liveness and readiness probe endpoint."""
    return {"status": "ok"}
