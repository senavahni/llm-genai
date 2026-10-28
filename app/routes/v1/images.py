import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.controllers import image_controller
from app.schemas.common import AuthContext
from app.schemas.images import ImageGenerationRequest
from app.utils.auth import require_scope

router = APIRouter()


@router.post("/images/generations", response_model=None)
async def images_generations(
    body: ImageGenerationRequest,
    request: Request,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_scope("images")),
) -> Response:
    return await image_controller.create_image(body, auth, request, background)


@router.post("/images/edits", response_model=None)
async def images_edits(
    request: Request,
    background: BackgroundTasks,
    image: UploadFile = File(...),
    prompt: str = Form(...),
    model: str = Form("image"),
    n: int = Form(1),
    size: str = Form("512x512"),
    response_format: str = Form("url"),
    mask: UploadFile | None = File(None),
    strength: float | None = Form(None),
    seed: int | None = Form(None),
    steps: int | None = Form(None),
    guidance_scale: float | None = Form(None),
    negative_prompt: str | None = Form(None),
    user: str | None = Form(None),
    auth: AuthContext = Depends(require_scope("images")),
) -> Response:
    form = {
        "prompt": prompt,
        "model": model,
        "n": n,
        "size": size,
        "response_format": response_format,
        "strength": strength,
        "seed": seed,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "negative_prompt": negative_prompt,
        "user": user,
    }
    return await image_controller.edit_image(form, image, mask, auth, request, background)


@router.get("/images/files/{image_id}", response_model=None)
async def image_file(
    image_id: uuid.UUID, auth: AuthContext = Depends(require_scope("images"))
) -> Response:
    return await image_controller.get_image_file(image_id, auth)
