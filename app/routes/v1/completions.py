from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response

from app.controllers import completion_controller
from app.schemas.common import AuthContext
from app.schemas.openai_compat import CompletionRequest
from app.utils.auth import require_scope

router = APIRouter()


@router.post("/completions", response_model=None)
async def completions(
    body: CompletionRequest,
    request: Request,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_scope("completions")),
) -> Response:
    return await completion_controller.create_completion(body, auth, request, background)
