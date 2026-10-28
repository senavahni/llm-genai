from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import UsageDaily
from app.schemas.common import AuthContext
from app.utils.errors import InvalidRequestError
from app.utils.helper import utcnow

MAX_RANGE_DAYS = 366


async def get_usage(auth: AuthContext, start: date | None, end: date | None) -> dict[str, Any]:
    """Agregat harian project pemanggil (termasuk image_count)."""
    if auth.project_id is None:
        raise InvalidRequestError("Key tanpa project tidak memiliki data usage")
    end = end or utcnow().date()
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > MAX_RANGE_DAYS:
        raise InvalidRequestError(f"Rentang tanggal tidak valid (maks {MAX_RANGE_DAYS} hari)")
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(UsageDaily)
                    .where(
                        UsageDaily.project_id == auth.project_id,
                        UsageDaily.day >= start,
                        UsageDaily.day <= end,
                    )
                    .order_by(UsageDaily.day, UsageDaily.model_alias)
                )
            )
            .scalars()
            .all()
        )
    data = [
        {
            "day": r.day.isoformat(),
            "model": r.model_alias,
            "provider": r.provider_code,
            "requests": r.request_count,
            "success": r.success_count,
            "errors": r.error_count,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "image_count": r.image_count,
            "cost_usd": str(r.cost_usd),
        }
        for r in rows
    ]
    return {
        "object": "list",
        "project": auth.project_slug,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "data": data,
    }
