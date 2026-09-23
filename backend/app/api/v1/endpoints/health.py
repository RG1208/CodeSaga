from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import DbSession, SettingsDep
from app.schemas.common import HealthResponse, ReadinessResponse
from app.services.health_service import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, summary="Liveness probe")
def health(settings: SettingsDep) -> HealthResponse:
    """The process is up and serving requests. Does not touch the database."""
    return HealthResponse(
        status="ok",
        service="codesage-backend",
        version=__version__,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(db: DbSession) -> ReadinessResponse | JSONResponse:
    """The service can do useful work: its dependencies (the database) are reachable."""
    database_ok = check_database(db)
    body = ReadinessResponse(
        status="ok" if database_ok else "unavailable",
        checks={"database": "ok" if database_ok else "error"},
    )
    if database_ok:
        return body
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump())
