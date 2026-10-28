from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from app.controllers.common import finish_error, get_router, payload_body
from app.schemas.common import AuthContext
from app.schemas.converters import embedding_vector
from app.schemas.openai_compat import EmbeddingRequest
from app.services.context import RequestCtx
from app.services.embedding_service import EmbeddingService, normalize_input
from app.services.router_service import Capabilities
from app.services.usage_service import usage_service


async def create_embeddings(
    body: EmbeddingRequest, auth: AuthContext, request: Request, background: BackgroundTasks
) -> Response:
    router = get_router(request)
    inputs = normalize_input(body.input)
    ctx = RequestCtx.from_request(
        request,
        auth,
        endpoint="embeddings",
        model=body.model,
        metadata=body.metadata,
        body=payload_body(auth.log_payloads, body),
    )
    candidates = await router.resolve(body.model, auth, Capabilities(model_type="embedding"))
    await usage_service.start(ctx)
    try:
        resp, outcome = await EmbeddingService(router).execute(
            ctx, inputs, body.dimensions, body.provider_options(), candidates
        )
    except BaseException as exc:
        await finish_error(ctx, exc)
        raise
    outcome.response_body = None  # vektor tidak dicatat di payload log
    background.add_task(usage_service.finish, ctx, outcome, status="success")
    data = [
        {"object": "embedding", "index": i, "embedding": embedding_vector(v, body.encoding_format)}
        for i, v in enumerate(resp.vectors)
    ]
    usage = {"prompt_tokens": resp.usage.prompt_tokens, "total_tokens": resp.usage.prompt_tokens}
    return JSONResponse(
        {"object": "list", "data": data, "model": body.model, "usage": usage},
        headers=ctx.headers(),
    )
