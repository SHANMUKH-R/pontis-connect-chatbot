from fastapi import APIRouter
from pydantic import BaseModel

from pontis_chat.dependency_injectors import AppConfigDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health(config: AppConfigDep) -> HealthResponse:
    return HealthResponse(status=config.health_status)