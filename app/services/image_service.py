"""Image generation & image-to-image (TASK-14): validasi parameter terhadap model, eksekusi
dengan fallback (hanya bila belum ada gambar yang dihasilkan), penyimpanan file untuk
`response_format=url`, dan penyajian file milik project."""

import asyncio
import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.image import GeneratedImage
from app.schemas.catalog import ModelConfig
from app.schemas.unified import UnifiedImageRequest, UnifiedImageResponse
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router
from app.utils.errors import ImageNotFound, InvalidRequestError, UnsupportedSize
from app.utils.helper import utcnow
from app.utils.logger import get_logger

log = get_logger(__name__)


def validate_image_params(req: UnifiedImageRequest, candidates: list[ModelConfig]) -> None:
    """Size harus didukung minimal satu kandidat; steps ≤ max_steps kandidat (lokal)."""
    sizes: list[str] = []
    for m in candidates:
        allowed = m.config.get("allowed_sizes")
        if not allowed:
            return  # kandidat tanpa batasan (mis. remote) → biarkan provider memutuskan
        sizes.extend(str(s) for s in allowed)
    if req.size not in sizes:
        raise UnsupportedSize(
            f"Ukuran {req.size} tidak didukung; tersedia: {', '.join(dict.fromkeys(sizes))}"
        )
    max_steps = max(int(m.config.get("max_steps") or 0) for m in candidates) or None
    if req.steps is not None and max_steps and req.steps > max_steps:
        raise InvalidRequestError(f"steps maksimal {max_steps}", param="steps")


def storage_root() -> Path:
    return Path(get_settings().storage_dir).resolve()


class ImageService:
    def __init__(self, router: Router) -> None:
        self.router = router

    async def execute(
        self, ctx: RequestCtx, req: UnifiedImageRequest, candidates: list[ModelConfig]
    ) -> tuple[UnifiedImageResponse, Outcome]:
        validate_image_params(req, candidates)
        result, _ = await self.router.run_with_fallback(
            ctx, candidates, lambda p, m: p.generate_images(m, req)
        )
        images = result.images
        return result, Outcome(
            upstream_model=result.upstream_model,
            runtime_meta=result.runtime_meta,
            image_count=len(images),
            extra_tags={
                "seeds": [i.seed for i in images],
                "steps": images[0].steps if images else None,
                "size": req.size,
                "image_to_image": req.image is not None,
            },
            # gambar tidak pernah masuk request_payloads (hanya metadata)
            response_body={"images": [{"sha256": i.sha256, "seed": i.seed} for i in images]},
        )

    async def store(
        self, ctx: RequestCtx, result: UnifiedImageResponse, public_base: str
    ) -> list[str]:
        """Tulis PNG ke STORAGE_DIR/images/{yyyy-mm-dd}/{request_id}_{idx}.png, lalu insert
        generated_images (transaksi terpisah). Insert gagal → file dihapus (tanpa file yatim)."""
        root = storage_root()
        day = utcnow().strftime("%Y-%m-%d")
        rel_paths = [
            Path("images") / day / f"{ctx.request_id}_{i}.png" for i in range(len(result.images))
        ]

        def write_files() -> None:
            for rel, img in zip(rel_paths, result.images, strict=True):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(img.png_bytes)

        await asyncio.to_thread(write_files)
        expires = utcnow() + timedelta(days=max(ctx.auth.image_retention_days, 1))
        ids = [uuid.uuid4() for _ in result.images]
        try:
            async with SessionLocal() as session:
                session.add_all(
                    GeneratedImage(
                        id=image_id,
                        request_id=ctx.request_id,
                        project_id=ctx.auth.project_id,
                        model_id=ctx.served_by.id if ctx.served_by else None,
                        idx=i,
                        file_path=rel.as_posix(),
                        width=img.width,
                        height=img.height,
                        seed=img.seed,
                        steps=img.steps,
                        guidance_scale=Decimal(str(img.guidance_scale)),
                        sha256=img.sha256 or hashlib.sha256(img.png_bytes).hexdigest(),
                        bytes=len(img.png_bytes),
                        expires_at=expires,
                    )
                    for i, (image_id, rel, img) in enumerate(
                        zip(ids, rel_paths, result.images, strict=True)
                    )
                )
                await session.commit()
        except Exception:

            def remove_files() -> None:
                for rel in rel_paths:
                    (root / rel).unlink(missing_ok=True)

            await asyncio.to_thread(remove_files)
            raise
        base = public_base.rstrip("/")
        return [f"{base}/v1/images/files/{image_id}" for image_id in ids]

    @staticmethod
    async def resolve_file(image_id: uuid.UUID, project_id: uuid.UUID | None) -> Path:
        """File milik project pemanggil & belum kedaluwarsa; selain itu 404 yang sama
        (tidak membocorkan keberadaan). Path di-resolve di dalam STORAGE_DIR."""
        async with SessionLocal() as session:
            row = (
                await session.execute(select(GeneratedImage).where(GeneratedImage.id == image_id))
            ).scalar_one_or_none()
        if row is None or row.project_id != project_id or row.expires_at <= utcnow():
            raise ImageNotFound("Gambar tidak ditemukan", param="image_id")
        root = storage_root()
        path = (root / row.file_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            log.warning("image_file_missing", image_id=str(image_id))
            raise ImageNotFound("Gambar tidak ditemukan", param="image_id")
        return path
