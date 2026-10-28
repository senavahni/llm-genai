from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response

from app.controllers import embedding_controller
from app.schemas.common import AuthContext
from app.schemas.openai_compat import EmbeddingRequest
from app.utils.auth import require_scope

router = APIRouter()


@router.post("/embeddings", response_model=None)
async def embeddings(
    body: EmbeddingRequest,
    request: Request,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_scope("embeddings")),
) -> Response:
    return await embedding_controller.create_embeddings(body, auth, request, background)
