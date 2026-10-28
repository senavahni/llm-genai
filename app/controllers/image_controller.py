import uuid

from fastapi import BackgroundTasks, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError

from app.controllers.common import admit_and_start, finish_error, get_router, public_base
from app.schemas.common import AuthContext
from app.schemas.converters import image_response, image_to_unified
from app.schemas.images import ImageEditRequest, ImageGenerationRequest
from app.services.context import RequestCtx
from app.services.image_service import ImageService
from app.services.router_service import Capabilities
from app.services.usage_service import usage_service
from app.utils.errors import InvalidRequestError, PayloadTooLarge, UnsupportedParameter

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _payload_meta(body: ImageGenerationRequest) -> dict[str, object]:
    """Gambar tidak pernah masuk request_payloads: hanya metadata (prompt, seed, steps)."""
    return body.model_dump(mode="json", exclude={"image"}, exclude_none=True)


async def _run(
    body: ImageGenerationRequest,
    auth: AuthContext,
    request: Request,
    background: BackgroundTasks,
    *,
    endpoint: str,
    image: bytes | None = None,
    strength: float | None = None,
) -> Response:
    router = get_router(request)
    ctx = RequestCtx.from_request(
        request,
        auth,
        endpoint=endpoint,
        model=body.model,
        metadata=body.metadata,
        body=_payload_meta(body) if auth.log_payloads else None,
    )
    need = Capabilities(model_type="image", image_edit=image is not None)
    candidates = await router.resolve(body.model, auth, need)
    # gambar: estimasi TPM 0, dibatasi RPM & kuota max_images (+ n yang diminta)
    await admit_and_start(ctx, 0, images=body.n)
    service = ImageService(router)
    try:
        result, outcome = await service.execute(
            ctx, image_to_unified(body, image, strength), candidates
        )
        urls = (
            await service.store(ctx, result, public_base(request))
            if body.response_format == "url"
            else None
        )
    except BaseException as exc:
        await finish_error(ctx, exc)
        raise
    background.add_task(usage_service.finish, ctx, outcome, status="success")
    return JSONResponse(image_response(result, urls), headers=ctx.headers())


async def create_image(
    body: ImageGenerationRequest, auth: AuthContext, request: Request, background: BackgroundTasks
) -> Response:
    return await _run(body, auth, request, background, endpoint="images.generations")


async def edit_image(
    form: dict[str, object],
    image: UploadFile,
    mask: UploadFile | None,
    auth: AuthContext,
    request: Request,
    background: BackgroundTasks,
) -> Response:
    """`/v1/images/edits` multipart (format OpenAI) → image-to-image model lokal."""
    if mask is not None:
        raise UnsupportedParameter("Inpainting (mask) tidak didukung", param="mask")
    raw = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PayloadTooLarge("Gambar maksimal 10 MB", param="image")
    if not raw:
        raise InvalidRequestError("Field 'image' kosong", param="image")
    try:
        body = ImageEditRequest.model_validate(
            {k: v for k, v in form.items() if v is not None} | {"image": raw}
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        param = ".".join(str(p) for p in first.get("loc", ())) or None
        raise InvalidRequestError(f"{param}: {first['msg']}", param=param) from exc
    return await _run(
        body,
        auth,
        request,
        background,
        endpoint="images.edits",
        image=body.image,
        strength=body.strength,
    )


async def get_image_file(image_id: uuid.UUID, auth: AuthContext) -> Response:
    path = await ImageService.resolve_file(image_id, auth.project_id)
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )
