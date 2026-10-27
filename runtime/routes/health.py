from fastapi import APIRouter

from runtime.controllers import runtime_controller as c

# Tanpa token: runtime hanya bind 127.0.0.1 dan endpoint ini tidak membuka data sensitif.
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


router.add_api_route("/ready", c.health_ready, methods=["GET"], response_model=None)
