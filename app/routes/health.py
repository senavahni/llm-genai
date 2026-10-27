import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.database import ping_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """ok = DB + semua provider sehat; degraded = DB ok tetapi ada provider (mis. runtime) mati;
    503 bila DB down. Versi lengkap (cache hasil, detail GPU/NPU) di TASK-18."""
    registry = getattr(request.app.state, "registry", None)
    db_ok = await ping_db()
    providers: dict[str, Any] = {}
    if registry is not None and registry.providers:
        codes = list(registry.providers)
        results = await asyncio.gather(
            *(registry.providers[c].health() for c in codes), return_exceptions=True
        )
        for code, res in zip(codes, results, strict=True):
            if isinstance(res, BaseException):
                providers[code] = {"ok": False, "detail": type(res).__name__}
            else:
                providers[code] = res.model_dump(exclude_none=True)
        for code, reason in registry.disabled.items():
            providers[code] = {"ok": None, "detail": reason}
    all_ok = all(p["ok"] for p in providers.values() if p["ok"] is not None)
    status = "down" if not db_ok else ("ok" if all_ok else "degraded")
    return JSONResponse(
        {"status": status, "db": db_ok, "providers": providers},
        status_code=200 if db_ok else 503,
    )
