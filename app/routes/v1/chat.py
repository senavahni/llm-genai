from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response

from app.controllers import chat_controller
from app.schemas.common import AuthContext
from app.schemas.openai_compat import ChatCompletionRequest
from app.utils.auth import require_scope

router = APIRouter()


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_scope("chat")),
) -> Response:
    return await chat_controller.create_chat_completion(body, auth, request, background)
