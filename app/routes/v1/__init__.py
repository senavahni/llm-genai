from fastapi import APIRouter

from app.routes.v1 import chat, completions, embeddings, images, models, usage

# Endpoint publik kompatibel OpenAI (TASK-14). Route hanya memanggil controller.
router = APIRouter(prefix="/v1", tags=["v1"])
for module in (chat, completions, embeddings, images, models, usage):
    router.include_router(module.router)
