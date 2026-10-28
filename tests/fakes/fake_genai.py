"""Modul `openvino_genai` palsu untuk unit test backend OpenVINO tanpa hardware."""

import threading
import time
from types import SimpleNamespace
from typing import Any

import numpy as np


class Tensor:
    def __init__(self, data: np.ndarray) -> None:
        self.data = data


class CppStdGenerator:
    def __init__(self, seed: int) -> None:
        self.seed = seed


class Tokenizer:
    def __init__(self, path: str) -> None:
        self.path = path

    def encode(self, text: str) -> Any:
        ids = np.array([[1, *range(len(text.split())), 2]])
        return SimpleNamespace(input_ids=SimpleNamespace(data=ids))


class _ImagePipeline:
    step_delay_s = 0.0
    instances: list["_ImagePipeline"] = []

    def __init__(self, source: Any) -> None:
        self.source = source
        self.calls: list[dict[str, Any]] = []
        self.steps_run = 0
        _ImagePipeline.instances.append(self)

    def _run(self, prompt: str, image: Any, **kw: Any) -> Tensor:
        self.calls.append({"prompt": prompt, "image": image, **kw})
        self.steps_run = 0
        steps = int(kw["num_inference_steps"])
        if image is not None:
            steps = max(1, int(steps * kw["strength"]))
        for step in range(steps):
            self.steps_run += 1
            time.sleep(self.step_delay_s)
            if kw["callback"](step, steps, None):
                break
        value = (kw["generator"].seed + (7 if image is not None else 0)) % 256
        return Tensor(np.full((1, 8, 8, 3), value, dtype=np.uint8))


class Image2ImagePipeline(_ImagePipeline):
    def reshape(self, n: int, height: int, width: int, guidance: float) -> None:
        self.shape = (n, height, width, guidance)

    def compile(self, te: str, unet: str, vae: str, **props: Any) -> None:
        self.devices = (te, unet, vae)
        self.props = props
        # simulasi cache compile: file baru hanya pada compile pertama
        cache = props["CACHE_DIR"]
        import pathlib

        marker = pathlib.Path(cache) / "blob.cache"
        if not marker.exists():
            marker.write_text("x")

    def generate(self, prompt: str, image: Any, **kw: Any) -> Tensor:
        return self._run(prompt, image, **kw)


class Text2ImagePipeline(_ImagePipeline):
    def generate(self, prompt: str, **kw: Any) -> Tensor:
        return self._run(prompt, None, **kw)


def module() -> SimpleNamespace:
    return SimpleNamespace(
        Image2ImagePipeline=Image2ImagePipeline,
        Text2ImagePipeline=Text2ImagePipeline,
        CppStdGenerator=CppStdGenerator,
        Tokenizer=Tokenizer,
        _lock=threading.Lock(),
    )
