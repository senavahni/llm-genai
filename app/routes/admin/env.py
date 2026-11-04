from typing import Any

from fastapi import APIRouter, Request

from app.controllers.admin import catalog
from app.services.env_status import env_vars, provider_key_states

router = APIRouter()


@router.get("/env-status")
async def env_status(request: Request) -> dict[str, Any]:
    """Status `.env` untuk Admin Console: nama + keadaan, tanpa nilai secret."""
    settings = request.app.state.settings
    providers = (await catalog.list_providers())["data"]
    return {
        "vars": env_vars(settings),
        "providers": provider_key_states(settings, providers),
    }
