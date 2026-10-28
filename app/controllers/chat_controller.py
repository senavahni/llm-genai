from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from app.controllers.common import finish_error, get_router, open_sse, payload_body
from app.schemas.common import AuthContext
from app.schemas.converters import chat_capabilities, chat_chunk, chat_response, chat_to_unified
from app.schemas.openai_compat import ChatCompletionRequest
from app.services.chat_service import ChatService
from app.services.context import Outcome, RequestCtx
from app.services.usage_service import usage_service


async def create_chat_completion(
    body: ChatCompletionRequest, auth: AuthContext, request: Request, background: BackgroundTasks
) -> Response:
    router = get_router(request)
    unified = chat_to_unified(body)
    ctx = RequestCtx.from_request(
        request,
        auth,
        endpoint="chat.completions",
        model=body.model,
        stream=body.stream,
        metadata=body.metadata,
        body=payload_body(auth.log_payloads, body),
    )
    # TASK-16: rate limit & kuota diperiksa di sini (sebelum resolve)
    candidates = await router.resolve(body.model, auth, chat_capabilities(unified))
    service = ChatService(router)
    outcome = Outcome()
    stream = service.execute_stream(ctx, unified, candidates, outcome) if body.stream else None
    await usage_service.start(ctx)
    rid = str(ctx.request_id)
    if stream is not None:
        return await open_sse(
            request,
            ctx,
            outcome,
            stream,
            lambda chunk, created: chat_chunk(chunk, rid, body.model, created),
            include_usage=body.include_usage,
            model=body.model,
            chat=True,
        )
    try:
        resp, outcome = await service.execute(ctx, unified, candidates)
    except BaseException as exc:
        await finish_error(ctx, exc)
        raise
    background.add_task(usage_service.finish, ctx, outcome, status="success")
    return JSONResponse(chat_response(resp, rid, body.model), headers=ctx.headers())
