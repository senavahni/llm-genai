"""Backend vision Qwen2-VL lewat OpenVINO GenAI `VLMPipeline` (TASK-11). Percakapan dikirim
sebagai ChatHistory (stateless, multi-turn); gambar ditandai `<ov_genai_image_N>` di posisi
aslinya dan dikirim sebagai daftar ov.Tensor."""

from typing import Any, ClassVar

from app.utils.errors import CapabilityNotSupported, InvalidRequestError
from runtime.backends.image_input import load_image
from runtime.backends.ov_common import genai
from runtime.backends.ov_llm_backend import OVLLMBackend, Prepared

IMAGE_TAG = "<ov_genai_image_{}>"


class OVVLMBackend(OVLLMBackend):
    kind: ClassVar[str] = "openvino_vlm"
    pipeline_class: ClassVar[str] = "VLMPipeline"
    _image_index: int = 0  # penomoran tag gambar saat merender pesan (satu request per waktu)

    @property
    def max_images(self) -> int:
        return int(self.cfg.get("max_images", 4))

    @property
    def max_image_px(self) -> int:
        return int(self.cfg.get("max_image_px", 1280))

    async def _load_images(self, req: dict[str, Any]) -> list[Any]:
        urls = [
            part["image_url"]["url"] if isinstance(part.get("image_url"), dict) else None
            for m in req.get("messages") or []
            if isinstance(m.get("content"), list)
            for part in m["content"]
            if part.get("type") == "image_url"
        ]
        if len(urls) > self.max_images:
            raise InvalidRequestError(
                f"Maksimal {self.max_images} gambar per request", param="messages"
            )
        if any(not isinstance(u, str) or not u for u in urls):
            raise InvalidRequestError("image_url.url wajib diisi", param="messages")
        return [await load_image(str(u), self.max_image_px) for u in urls]

    def message_content(self, content: Any) -> str:
        if content is None or isinstance(content, str):
            return content or ""
        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                parts.append(IMAGE_TAG.format(self._image_index))
                self._image_index += 1
        return "".join(parts)

    def _prepare_vlm(self, req: dict[str, Any], arrays: list[Any]) -> Prepared:
        import numpy as np
        import openvino as ov

        if req.get("tools"):
            raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung tools")
        self._image_index = 0
        messages = self.chat_messages(req)
        history = genai().ChatHistory(messages)
        images = [ov.Tensor(np.ascontiguousarray(a)[None]) for a in arrays]
        # perkiraan token teks untuk batas; jumlah akurat (termasuk token gambar) dari perf_metrics
        text_tokens = self.count_tokens("\n".join(m["content"] for m in messages))
        cfg, max_new, warnings = self.generation_config(req, text_tokens)
        cfg.apply_chat_template = True  # VLMPipeline menyisipkan token gambar via template
        return Prepared(
            inputs=(history, images),
            config=cfg,
            prompt_tokens=text_tokens,
            max_new_tokens=max_new,
            warnings=warnings,
        )

    async def prepare_chat_async(self, req: dict[str, Any]) -> Prepared:
        arrays = await self._load_images(req)
        return await self.run_sync(self._prepare_vlm, req, arrays)

    def run_generate(self, prep: Prepared, streamer: Any) -> Any:
        history, images = prep.inputs
        return self._pipe.generate(
            history, images=images, generation_config=prep.config, streamer=streamer
        )

    async def completion(self, req: dict[str, Any]) -> dict[str, Any]:
        raise CapabilityNotSupported(f"{self.spec.alias} hanya mendukung chat")

    def completion_stream(self, req: dict[str, Any], cancel: Any) -> Any:
        raise CapabilityNotSupported(f"{self.spec.alias} hanya mendukung chat")
