from fastapi import APIRouter, Depends

from app.utils.auth import require_admin

# Endpoint admin diisi di TASK-17. Seluruh /admin/* wajib role admin.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
