from fastapi import APIRouter, Depends

from runtime.controllers import inference_controller as c
from runtime.core.security import require_runtime_token

router = APIRouter(prefix="/v1", tags=["inference"], dependencies=[Depends(require_runtime_token)])

router.add_api_route("/chat/completions", c.chat_completions, methods=["POST"], response_model=None)
router.add_api_route("/completions", c.completions, methods=["POST"], response_model=None)
router.add_api_route("/embeddings", c.embeddings, methods=["POST"], response_model=None)
router.add_api_route(
    "/images/generations", c.image_generations, methods=["POST"], response_model=None
)
