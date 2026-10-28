from datetime import date
from typing import Any

from app.services.usage_service import usage_service
from app.utils.helper import utcnow


async def verify_usage(day: date | None) -> dict[str, Any]:
    """Konsistensi requests vs usage_daily per project untuk satu hari UTC (selisih harus 0)."""
    day = day or utcnow().date()
    rows = await usage_service.verify(day)
    return {
        "day": day.isoformat(),
        "consistent": all(r["diff"] == 0 and r["image_diff"] == 0 for r in rows),
        "projects": rows,
    }
