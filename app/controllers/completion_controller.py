from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from app.controllers.common import finish_error, get_router, open_sse, payload_body
from app.schemas.common import AuthContext
from app.schemas.converters import (
    completion_capabilities,
    completion_chunk,
    completion_response,
    completion_to_unified,
)
from app.schemas.openai_compat import CompletionRequest
from app.services.completion_service import CompletionService
from app.services.context import Outcome, RequestCtx
from app.services.usage_service import usage_service


async def create_completion(
    body: CompletionRequest, auth: AuthContext, request: Request, background: BackgroundTasks
) -> Response:
    """Legacy completions: raw prompt, atau FIM bila `suffix` diisi (route autocomplete)."""
    router = get_router(request)
    unified = completion_to_unified(body)
    ctx = RequestCtx.from_request(
        request,
        auth,
        endpoint="completions",
        model=body.model,
        stream=body.stream,
        metadata=body.metadata,
        body=payload_body(auth.log_payloads, body),
    )
    candidates = await router.resolve(body.model, auth, completion_capabilities(unified))
    service = CompletionService(router)
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
            lambda chunk, created: completion_chunk(chunk, rid, body.model, created),
            include_usage=body.include_usage,
            model=body.model,
            chat=False,
        )
    try:
        resp, outcome = await service.execute(ctx, unified, candidates)
    except BaseException as exc:
        await finish_error(ctx, exc)
        raise
    background.add_task(usage_service.finish, ctx, outcome, status="success")
    return JSONResponse(completion_response(resp, rid, body.model), headers=ctx.headers())
