from fastapi import APIRouter, Depends

from app.routes.admin import (
    audit,
    keys,
    maintenance,
    models,
    projects,
    providers,
    quotas,
    requests,
    routes,
    runtime,
    usage,
)
from app.utils.auth import require_admin

# Admin API (TASK-17). Seluruh /admin/* wajib role admin.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
for module in (
    projects,
    keys,
    quotas,
    providers,
    models,
    routes,
    requests,
    usage,
    audit,
    runtime,
    maintenance,
):
    router.include_router(module.router)
