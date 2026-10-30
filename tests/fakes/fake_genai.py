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


# ----------------------------------------------------------------- LLM palsu
# Tokenisasi per karakter (id = ord); token spesial = id ≥ 1_000_000 (lihat SPECIAL).
SPECIAL = {"<|endoftext|>": 1_000_000, "<|fim_pad|>": 1_000_001, "<|im_end|>": 1_000_002}
_SPECIAL_BY_ID = {v: k for k, v in SPECIAL.items()}


class StreamingStatus:
    RUNNING = "RUNNING"
    STOP = "STOP"
    CANCEL = "CANCEL"


class StreamerBase:
    def __init__(self) -> None:
        pass


class StructuredOutputConfig:
    def __init__(self, json_schema: str | None = None) -> None:
        self.json_schema = json_schema


class FinishReason:
    def __init__(self, name: str) -> None:
        self.name = name


class GenerationConfig:
    def __init__(self) -> None:
        self.max_new_tokens = 32
        self.temperature = 1.0
        self.do_sample = False
        self.top_p = 1.0
        self.top_k = 0
        self.min_p = 0.0
        self.repetition_penalty = 1.0
        self.presence_penalty = 0.0
        self.frequency_penalty = 0.0
        self.rng_seed = 0
        self.stop_strings: set[str] = set()
        self.stop_token_ids: set[int] = {SPECIAL["<|endoftext|>"]}
        self.apply_chat_template = True
        self.structured_output_config = None


def _encode_ids(text: str) -> list[int]:
    ids, i = [], 0
    while i < len(text):
        for tok, tid in SPECIAL.items():
            if text.startswith(tok, i):
                ids.append(tid)
                i += len(tok)
                break
        else:
            ids.append(ord(text[i]))
            i += 1
    return ids


class LLMTokenizer:
    def encode(self, text: str, add_special_tokens: bool = True) -> Any:
        ids = np.array([_encode_ids(text)], dtype=np.int64)
        return SimpleNamespace(input_ids=SimpleNamespace(data=ids))

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        out = []
        for t in ids:
            if t in _SPECIAL_BY_ID:
                if t == SPECIAL["<|fim_pad|>"] or not skip_special_tokens:
                    out.append(_SPECIAL_BY_ID[t])  # seperti Qwen: <|fim_pad|> tidak di-skip
            else:
                out.append(chr(t))
        return "".join(out)

    def apply_chat_template(
        self, history: list[dict], add_generation_prompt: bool, tools: Any = None
    ) -> str:
        self.last_history, self.last_tools = history, tools
        parts = [f"<{m['role']}>{m.get('content') or ''}" for m in history]
        if tools:
            parts.insert(0, "<tools>" + ",".join(t["function"]["name"] for t in tools))
        return "".join(parts) + ("<assistant>" if add_generation_prompt else "")


class _PerfMetrics:
    def __init__(self, n_in: int, n_out: int) -> None:
        self.n_in, self.n_out = n_in, n_out

    def get_num_generated_tokens(self) -> int:
        return self.n_out

    def get_num_input_tokens(self) -> int:
        return self.n_in


class LLMPipeline:
    """`output` (kelas) = teks yang 'dihasilkan' model; `token_delay_s` = jeda per token."""

    output = "Halo dunia"
    token_delay_s = 0.0
    instances: list["LLMPipeline"] = []

    def __init__(self, path: str, device: str, **props: Any) -> None:
        self.path, self.device, self.props = path, device, props
        self.tokenizer = LLMTokenizer()
        self.calls: list[dict[str, Any]] = []
        self.tokens_generated = 0
        LLMPipeline.instances.append(self)

    def get_tokenizer(self) -> LLMTokenizer:
        return self.tokenizer

    def get_generation_config(self) -> GenerationConfig:
        return GenerationConfig()

    def _text_for(self, cfg: GenerationConfig) -> str:
        return type(self).output

    def generate(self, inputs: Any, cfg: GenerationConfig, streamer: Any = None) -> Any:
        prompt = inputs[0] if isinstance(inputs, list) else inputs
        self.calls.append({"inputs": prompt, "config": cfg})
        ids = _encode_ids(self._text_for(cfg))
        out: list[int] = []
        finish = "STOP"
        self.tokens_generated = 0
        for tid in ids:
            if len(out) >= cfg.max_new_tokens:
                finish = "LENGTH"
                break
            time.sleep(self.token_delay_s)
            self.tokens_generated += 1
            if tid in cfg.stop_token_ids:
                break
            out.append(tid)
            text = self.tokenizer.decode(out)
            hit = next((s for s in cfg.stop_strings if s in text), None)
            if streamer is not None:
                status = streamer.write(tid) if hasattr(streamer, "write") else streamer(chr(tid))
                if status == StreamingStatus.CANCEL:
                    break
            if hit:
                out = _encode_ids(text.split(hit)[0])
                break
        return SimpleNamespace(
            texts=[self.tokenizer.decode(out)],
            perf_metrics=_PerfMetrics(len(_encode_ids(str(prompt))), self.tokens_generated),
            finish_reasons=[FinishReason(finish)],
        )


class ChatHistory(list):
    pass


class VLMPipeline(LLMPipeline):
    def generate(
        self, history: Any, images: Any = None, generation_config: Any = None, streamer: Any = None
    ) -> Any:
        self.last_images = images
        self.last_history = [dict(m) for m in history]
        return super().generate(
            ["".join(str(m.get("content")) for m in history)], generation_config, streamer
        )


def module() -> SimpleNamespace:
    return SimpleNamespace(
        Image2ImagePipeline=Image2ImagePipeline,
        Text2ImagePipeline=Text2ImagePipeline,
        CppStdGenerator=CppStdGenerator,
        Tokenizer=Tokenizer,
        LLMPipeline=LLMPipeline,
        VLMPipeline=VLMPipeline,
        ChatHistory=ChatHistory,
        GenerationConfig=GenerationConfig,
        StreamerBase=StreamerBase,
        StreamingStatus=StreamingStatus,
        StructuredOutputConfig=StructuredOutputConfig,
        _lock=threading.Lock(),
    )
