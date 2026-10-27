from fastapi import APIRouter

# Endpoint publik (chat, completions, embeddings, images, models, usage) diisi di TASK-14.
router = APIRouter(prefix="/v1", tags=["v1"])
