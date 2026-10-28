"""Backend LLM Qwen lewat OpenVINO GenAI (TASK-11): chat, stream, tool calling (Hermes), JSON mode,
completions + FIM, di GPU/NPU (device eksplisit, tanpa CPU). Format OpenAI di batas runtime."""

import asyncio
import contextlib
import gc
import json
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.utils.errors import (
    CapabilityNotSupported,
    ContextLengthExceeded,
    InvalidRequestError,
    UnsupportedParameter,
)
from app.utils.logger import get_logger
from runtime.backends.base import LoadResult, LocalBackend
from runtime.backends.ov_common import (
    cache_dir,
    cache_entries,
    device_kind,
    genai,
    model_path,
    validate_device,
    verify_artifact,
)
from runtime.backends.tool_parsers import StreamToolParser, parse_tool_output
from runtime.core.catalog import LocalModelSpec

log = get_logger("runtime.backends.llm")

DEFAULT_MAX_TOKENS = 1024
DEFAULT_FIM_MAX_TOKENS = 128
# parameter sampling tambahan yang boleh diteruskan (top-level atau provider_options)
SAMPLING_WHITELIST = ("top_k", "min_p", "repetition_penalty")
_FINISH = {"STOP": "stop", "LENGTH": "length", "TOOL_CALL": "tool_calls"}


@dataclass
class Prepared:
    """Hasil persiapan request (dihitung di thread, bukan di event loop)."""

    inputs: Any  # prompt string (LLM) atau (ChatHistory, images) (VLM)
    config: Any  # openvino_genai.GenerationConfig
    prompt_tokens: int
    max_new_tokens: int
    tools: bool = False
    warnings: list[str] = field(default_factory=list)
    strip: tuple[str, ...] = ()  # token yang dibuang dari output (mis. token FIM)
    tool_names: frozenset[str] = frozenset()


class OVLLMBackend(LocalBackend):
    kind: ClassVar[str] = "openvino_llm"
    pipeline_class: ClassVar[str] = "LLMPipeline"

    def __init__(self, spec: LocalModelSpec) -> None:
        super().__init__(spec)
        self._pipe: Any = None
        self._tok: Any = None
        self._device: str | None = None

    @property
    def cfg(self) -> dict[str, Any]:
        return self.spec.config

    @property
    def is_npu(self) -> bool:
        return (
            (self._device or self.cfg.get("device") or self.spec.device).upper().startswith("NPU")
        )

    @property
    def max_prompt_len(self) -> int | None:
        """Batas prompt: wajib di NPU (shape statis), opsional di GPU (config)."""
        value = self.cfg.get("max_prompt_len")
        if value:
            return int(value)
        return 1024 if self.is_npu else None

    @property
    def min_response_len(self) -> int:
        return int(self.cfg.get("min_response_len", 128))

    # ------------------------------------------------------------------ load
    def _properties(self, device: str) -> dict[str, Any]:
        props: dict[str, Any] = {"CACHE_DIR": str(cache_dir(self.spec))}
        if device.upper().startswith("NPU"):
            props["MAX_PROMPT_LEN"] = self.max_prompt_len
            props["MIN_RESPONSE_LEN"] = self.min_response_len
            if self.cfg.get("prefill_chunk_size"):
                # prefill NPU diproses per chunk statis: chunk kecil = TTFT prompt pendek kecil
                # (Coder-1.5B: 2048 → 1,6 s; 256 → 0,25 s untuk prompt ≤ 256 token)
                props["NPUW_LLM_PREFILL_CHUNK_SIZE"] = int(self.cfg["prefill_chunk_size"])
        return props

    def _load_sync(self) -> dict[str, Any]:
        g = genai()
        path = model_path(self.spec)
        verify_artifact(self.spec, path)
        device = validate_device(self.cfg.get("device") or self.spec.device)
        cdir = cache_dir(self.spec)
        before = cache_entries(cdir)
        start = time.perf_counter()
        pipe = getattr(g, self.pipeline_class)(str(path), device, **self._properties(device))
        compile_ms = int((time.perf_counter() - start) * 1000)
        self._pipe, self._tok, self._device = pipe, pipe.get_tokenizer(), device
        return {
            "compile_ms": compile_ms,
            "cache_hit": before > 0 and cache_entries(cdir) == before,
            "ov_device": device,
        }

    async def load(self) -> LoadResult:
        start = time.perf_counter()
        details = await self.run_sync(self._load_sync)
        return LoadResult(
            load_ms=int((time.perf_counter() - start) * 1000),
            device=self.actual_device(),
            details=details,
        )

    async def unload(self) -> None:
        self._pipe = self._tok = None
        await self.run_sync(gc.collect)

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def actual_device(self) -> str:
        return device_kind(self._device) if self._device else self.spec.device

    # --------------------------------------------------------------- helpers
    def count_tokens(self, text: str) -> int:
        return int(len(self._tok.encode(text, add_special_tokens=False).input_ids.data[0]))

    def _token_ids(self, text: str) -> list[int]:
        return [int(t) for t in self._tok.encode(text, add_special_tokens=False).input_ids.data[0]]

    def _decode(self, ids: list[int]) -> str:
        return str(self._tok.decode(ids)) if ids else ""

    def generation_config(
        self,
        req: dict[str, Any],
        prompt_tokens: int,
        *,
        default_max: int | None = None,
        extra_stop: tuple[str, ...] = (),
    ) -> tuple[Any, int, list[str]]:
        """Request OpenAI → GenerationConfig; hanya field yang dikirim caller yang diubah,
        sisanya default model (generation_config.json)."""
        g = genai()
        warnings: list[str] = []
        if int(req.get("n") or 1) != 1:
            raise UnsupportedParameter("Model lokal hanya mendukung n=1", param="n")
        cfg = self._pipe.get_generation_config()
        cfg.apply_chat_template = False  # prompt sudah diformat backend
        max_new = req.get("max_completion_tokens") or req.get("max_tokens")
        max_new = int(max_new or default_max or self.spec.max_output_tokens or DEFAULT_MAX_TOKENS)
        if max_new < 1:
            raise InvalidRequestError("max_tokens harus ≥ 1", param="max_tokens")
        if self.is_npu:
            # kapasitas KV NPU statis = MAX_PROMPT_LEN + MIN_RESPONSE_LEN
            capacity = (self.max_prompt_len or 0) + self.min_response_len - prompt_tokens
            if max_new > capacity:
                max_new = max(1, capacity)
                warnings.append("max_tokens_clamped_to_npu_capacity")
        cfg.max_new_tokens = max_new
        options = {**(req.get("provider_options") or {}), **req}
        if req.get("temperature") is not None:
            cfg.temperature = float(req["temperature"])
            cfg.do_sample = cfg.temperature > 0
        if req.get("top_p") is not None:
            cfg.top_p = float(req["top_p"])
        for key in ("presence_penalty", "frequency_penalty", *SAMPLING_WHITELIST):
            if options.get(key) is not None:
                setattr(cfg, key, options[key])
        if req.get("seed") is not None:
            cfg.rng_seed = int(req["seed"])
        stop = req.get("stop")
        stops = [stop] if isinstance(stop, str) else list(stop or [])
        # stop dari backend (token FIM) yang satu token cukup di level token: stop_strings
        # membuat GenAI menahan stream 1 token (+50 ms TTFT FIM di NPU)
        token_stops, _ = self.stop_plan(extra_stop)
        stops += [s for s in extra_stop if s not in stops and len(self._token_ids(s)) != 1]
        user_ids, _ = self.stop_plan(stops)
        if stops:
            cfg.stop_strings = set(stops)  # stop caller: tetap dicocokkan di teks (akurat)
        if token_stops | user_ids:
            cfg.stop_token_ids = set(cfg.stop_token_ids or ()) | token_stops | user_ids
        schema = self._json_schema(req.get("response_format"))
        if schema is not None:
            cfg.structured_output_config = g.StructuredOutputConfig(json_schema=schema)
        return cfg, max_new, warnings

    @staticmethod
    def _json_schema(response_format: Any) -> str | None:
        if not response_format:
            return None
        kind = response_format.get("type") if isinstance(response_format, dict) else None
        if kind in (None, "text"):
            return None
        if kind == "json_object":
            return json.dumps({"type": "object"})
        if kind == "json_schema":
            spec = response_format.get("json_schema") or {}
            schema = spec.get("schema") if isinstance(spec, dict) else None
            if not isinstance(schema, dict):
                raise InvalidRequestError(
                    "response_format.json_schema.schema wajib berupa objek",
                    param="response_format",
                )
            return json.dumps(schema)
        raise UnsupportedParameter(
            f"response_format.type={kind!r} tidak didukung", param="response_format"
        )

    # ------------------------------------------------------------- messages
    def chat_messages(self, req: dict[str, Any]) -> list[dict[str, Any]]:
        messages = req.get("messages")
        if not isinstance(messages, list) or not messages:
            raise InvalidRequestError("messages wajib diisi", param="messages")
        out = []
        for m in messages:
            role = "system" if m.get("role") == "developer" else m.get("role")
            msg: dict[str, Any] = {"role": role, "content": self.message_content(m.get("content"))}
            if m.get("tool_calls"):
                msg["tool_calls"] = [_tool_call_for_template(c) for c in m["tool_calls"]]
            if m.get("tool_call_id"):
                msg["tool_call_id"] = m["tool_call_id"]
            if m.get("name"):
                msg["name"] = m["name"]
            out.append(msg)
        return out

    def message_content(self, content: Any) -> str:
        if content is None or isinstance(content, str):
            return content or ""
        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung input gambar")
        return "".join(parts)

    # ---------------------------------------------------------- persiapan
    def prepare_chat(self, req: dict[str, Any]) -> Prepared:
        tools = req.get("tools") or None
        if tools and not self.spec.supports_tools:
            raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung tools")
        if req.get("tool_choice") not in (None, "auto", "none") and tools:
            # template Qwen tidak bisa memaksa fungsi tertentu
            raise UnsupportedParameter(
                "tool_choice hanya 'auto'/'none' untuk model lokal", param="tool_choice"
            )
        if req.get("tool_choice") == "none":
            tools = None
        messages = self.chat_messages(req)
        prompt = str(self._tok.apply_chat_template(messages, True, tools=tools))
        prompt_tokens = self.count_tokens(prompt)
        self._check_prompt(prompt_tokens)
        cfg, max_new, warnings = self.generation_config(req, prompt_tokens)
        names = frozenset(str((t.get("function") or {}).get("name")) for t in tools or [])
        return Prepared(
            inputs=prompt,
            config=cfg,
            prompt_tokens=prompt_tokens,
            max_new_tokens=max_new,
            tools=bool(tools),
            warnings=warnings,
            tool_names=names,
        )

    def prepare_completion(self, req: dict[str, Any]) -> Prepared:
        prompt = req.get("prompt")
        if not isinstance(prompt, str):
            raise InvalidRequestError("prompt harus string (list belum didukung)", param="prompt")
        if req.get("echo"):
            raise UnsupportedParameter("echo tidak didukung model lokal", param="echo")
        suffix = req.get("suffix")
        warnings: list[str] = []
        strip: tuple[str, ...] = ()
        extra_stop: tuple[str, ...] = ()
        default_max = None
        if suffix is not None:
            if not self.spec.supports_fim or not self.cfg.get("fim_template"):
                raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung FIM (suffix)")
            prompt, truncated = self.fim_prompt(prompt, str(suffix))
            if truncated:
                warnings.append("fim_prompt_truncated")
            extra_stop = tuple(self.cfg.get("fim_stop") or ())
            strip = extra_stop
            default_max = DEFAULT_FIM_MAX_TOKENS
        prompt_tokens = self.count_tokens(prompt)
        self._check_prompt(prompt_tokens)
        cfg, max_new, more = self.generation_config(
            req, prompt_tokens, default_max=default_max, extra_stop=extra_stop
        )
        return Prepared(
            inputs=prompt,
            config=cfg,
            prompt_tokens=prompt_tokens,
            max_new_tokens=max_new,
            warnings=warnings + more,
            strip=strip,
        )

    def fim_prompt(self, prefix: str, suffix: str) -> tuple[str, bool]:
        """Prompt FIM; bila melebihi `fim_max_prompt_tokens` (atau max_prompt_len), pangkas
        bagian terjauh dari kursor (awal prefix & akhir suffix)."""
        template = str(self.cfg["fim_template"])
        prompt = template.format(prefix=prefix, suffix=suffix)
        limits = [v for v in (self.cfg.get("fim_max_prompt_tokens"), self.max_prompt_len) if v]
        limit = min(int(v) for v in limits) if limits else None
        if limit is None or self.count_tokens(prompt) <= limit:
            return prompt, False
        overhead = self.count_tokens(template.format(prefix="", suffix=""))
        budget = max(limit - overhead - 2, 16)
        pre, suf = self._token_ids(prefix), self._token_ids(suffix)
        keep_suf = min(len(suf), budget // 4)
        keep_pre = min(len(pre), budget - keep_suf)
        keep_suf = min(len(suf), budget - keep_pre)  # sisa budget dipakai suffix
        prefix = self._decode(pre[len(pre) - keep_pre :])
        suffix = self._decode(suf[:keep_suf])
        return template.format(prefix=prefix, suffix=suffix), True

    def _check_prompt(self, prompt_tokens: int) -> None:
        limit = self.max_prompt_len
        if limit is not None and prompt_tokens > limit:
            raise ContextLengthExceeded(
                f"Prompt {prompt_tokens} token melebihi batas {limit} token "
                f"{self.spec.alias} ({'NPU' if self.is_npu else 'config'})",
                param="messages",
            )

    # --------------------------------------------------------------- eksekusi
    def run_generate(self, prep: Prepared, streamer: Callable[[str], Any] | None) -> Any:
        return self._pipe.generate([prep.inputs], prep.config, streamer)

    def _generate_sync(self, prep: Prepared) -> Any:
        return self.run_generate(prep, None)

    @staticmethod
    def _text(result: Any) -> str:
        return str(result.texts[0])

    def _usage(self, result: Any, prep: Prepared) -> tuple[dict[str, int], int]:
        completion = int(result.perf_metrics.get_num_generated_tokens())
        prompt = int(result.perf_metrics.get_num_input_tokens() or prep.prompt_tokens)
        usage = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
        return usage, completion

    def _finish(self, result: Any, prep: Prepared, completion_tokens: int) -> str:
        reasons = getattr(result, "finish_reasons", None) or []
        if reasons:
            name = getattr(reasons[0], "name", str(reasons[0])).split(".")[-1]
            if name in _FINISH:
                return _FINISH[name]
        return "length" if completion_tokens >= prep.max_new_tokens else "stop"

    def _clean(self, text: str, prep: Prepared) -> str:
        for token in prep.strip:
            text = text.split(token)[0]
        return text

    # ------------------------------------------------------------------ chat
    async def prepare_chat_async(self, req: dict[str, Any]) -> Prepared:
        return await self.run_sync(self.prepare_chat, req)

    async def chat(self, req: dict[str, Any]) -> dict[str, Any]:
        prep = await self.prepare_chat_async(req)
        result = await self.run_sync(self._generate_sync, prep)
        text = self._text(result)
        usage, completion = self._usage(result, prep)
        finish = self._finish(result, prep, completion)
        message: dict[str, Any] = {"role": "assistant", "content": text}
        if prep.tools:
            parsed = parse_tool_output(text, prep.tool_names)
            message["content"] = parsed.content
            if parsed.tool_calls:
                message["tool_calls"] = parsed.tool_calls
                finish = "tool_calls"
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.spec.upstream_name,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": usage,
            "_warnings": prep.warnings,
        }

    def chat_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        return self._chat_stream(req, cancel)

    async def _chat_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        prep = await self.prepare_chat_async(req)
        chunk_id, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        parser = StreamToolParser(set(prep.tool_names)) if prep.tools else None
        n_calls = 0
        role_sent = False

        def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> dict[str, Any]:
            return {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": self.spec.upstream_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                **extra,
            }

        def events_to_chunks(events: list[tuple[str, Any]]) -> list[dict[str, Any]]:
            nonlocal n_calls, role_sent
            out = []
            for kind, value in events:
                delta: dict[str, Any] = {} if role_sent else {"role": "assistant"}
                role_sent = True
                if kind == "content":
                    delta["content"] = value
                else:
                    delta["tool_calls"] = [{"index": n_calls, **value}]
                    n_calls += 1
                out.append(chunk(delta))
            return out

        result = None
        async for kind, value in self.stream_generate(prep, cancel):
            if kind == "text":
                events = parser.feed(value) if parser else [("content", value)]
                for item in events_to_chunks(events):
                    yield item
            else:
                result = value
        if parser:
            for item in events_to_chunks(parser.finish()):
                yield item
        if cancel.is_set() or result is None:
            log.info("generation_cancelled", model=self.spec.alias)
            yield chunk({}, "cancelled")
            return
        usage, completion = self._usage(result, prep)
        finish = "tool_calls" if n_calls else self._finish(result, prep, completion)
        yield chunk({}, finish, usage=usage, _warnings=prep.warnings)

    def stop_plan(self, stops: Any) -> tuple[set[int], int]:
        """Stop satu-token (mis. `<|fim_pad|>`) → id token (ditangani per token, tanpa menahan
        teks); stop multi-token → streamer menahan (panjang terpanjang − 1) karakter."""
        ids: set[int] = set()
        longest = 1
        for s in stops:
            if not s:
                continue
            tokens = self._token_ids(s)
            if len(tokens) == 1:
                ids.add(tokens[0])
            else:
                longest = max(longest, len(s))
        return ids, longest - 1

    def _token_streamer(
        self,
        on_text: Callable[[str], None],
        stop: threading.Event,
        stop_ids: set[int],
        holdback: int,
        stop_strings: tuple[str, ...] = (),
    ) -> Any:
        """Streamer per token: decode inkremental dan kirim teks segera. TextStreamer bawaan
        menahan ±3 token pertama (TTFT FIM +145 ms). Teks hanya ditahan untuk stop string
        multi-token (dan dipotong tepat sebelum stop string lengkap) serta saat UTF-8 belum
        lengkap; token stop tunggal tidak pernah dikirim."""
        g = genai()
        tok = self._tok

        class _Streamer(g.StreamerBase):  # type: ignore[misc,name-defined]
            def __init__(self) -> None:
                super().__init__()
                self.ids: list[int] = []
                self.sent = 0
                self.halted = False

            def write(self, token: Any) -> Any:
                for t in token if isinstance(token, list) else [token]:
                    if int(t) in stop_ids:
                        self.halted = True  # generasi berhenti di token ini; jangan dikirim
                    if not self.halted:
                        self.ids.append(int(t))
                text = str(tok.decode(self.ids))
                cut = min((i for s in stop_strings if (i := text.find(s)) >= 0), default=-1)
                if cut >= 0:  # stop string lengkap: kirim hanya teks sebelumnya
                    text, self.halted = text[:cut], True
                ready = len(text) if self.halted else len(text) - holdback
                if not text.endswith("�") and ready > self.sent:
                    on_text(text[self.sent : ready])
                    self.sent = ready
                return g.StreamingStatus.CANCEL if stop.is_set() else g.StreamingStatus.RUNNING

            def end(self) -> None:
                pass

        return _Streamer()

    async def stream_generate(
        self, prep: Prepared, cancel: asyncio.Event
    ) -> AsyncIterator[tuple[str, Any]]:
        """generate() di thread device dengan streamer → ("text", potongan)… lalu
        ("done", hasil). Cancel/aclose → streamer mengembalikan CANCEL (berhenti di token
        berikutnya); generator baru selesai setelah thread berhenti."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        stop = threading.Event()
        emitted: list[str] = []

        def put(item: tuple[str, Any]) -> None:
            with contextlib.suppress(RuntimeError):  # loop sudah ditutup
                loop.call_soon_threadsafe(queue.put_nowait, item)

        def on_text(piece: str) -> None:
            emitted.append(piece)
            put(("text", piece))

        stop_strings = tuple(s for s in getattr(prep.config, "stop_strings", None) or () if s)
        stop_ids, holdback = self.stop_plan(stop_strings)
        stop_ids |= {int(t) for t in getattr(prep.config, "stop_token_ids", None) or ()}
        streamer = self._token_streamer(on_text, stop, stop_ids, holdback, stop_strings)

        def work() -> None:
            try:
                put(("done", self.run_generate(prep, streamer)))
            except BaseException as exc:  # noqa: BLE001 - diteruskan ke consumer
                put(("error", exc))

        async def watch() -> None:
            await cancel.wait()
            stop.set()

        future = loop.run_in_executor(self.executor, work)
        watcher = asyncio.ensure_future(watch())
        try:
            while True:
                kind, value = await queue.get()
                if kind == "error":
                    raise value
                if kind == "done":
                    if not stop.is_set():
                        # teks final (stop string sudah dibuang) = sumber kebenaran: kirim sisa
                        # yang tertahan holdback
                        final = self._clean(self._text(value), prep)
                        sent = "".join(emitted)
                        if final.startswith(sent) and len(final) > len(sent):
                            yield ("text", final[len(sent) :])
                        yield ("done", value)
                    return
                yield (kind, value)
        finally:
            stop.set()
            watcher.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(future)

    # ------------------------------------------------------------ completions
    async def completion(self, req: dict[str, Any]) -> dict[str, Any]:
        prep = await self.run_sync(self.prepare_completion, req)
        result = await self.run_sync(self._generate_sync, prep)
        usage, completion = self._usage(result, prep)
        return {
            "id": f"cmpl-{uuid.uuid4().hex}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": self.spec.upstream_name,
            "choices": [
                {
                    "index": 0,
                    "text": self._clean(self._text(result), prep),
                    "finish_reason": self._finish(result, prep, completion),
                }
            ],
            "usage": usage,
            "_warnings": prep.warnings,
        }

    def completion_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        return self._completion_stream(req, cancel)

    async def _completion_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        prep = await self.run_sync(self.prepare_completion, req)
        chunk_id, created = f"cmpl-{uuid.uuid4().hex}", int(time.time())

        def chunk(text: str, finish: str | None = None, **extra: Any) -> dict[str, Any]:
            return {
                "id": chunk_id,
                "object": "text_completion",
                "created": created,
                "model": self.spec.upstream_name,
                "choices": [{"index": 0, "text": text, "finish_reason": finish}],
                **extra,
            }

        result = None
        async for kind, value in self.stream_generate(prep, cancel):
            if kind == "text":
                text = self._clean(value, prep)
                if text:
                    yield chunk(text)
            else:
                result = value
        if cancel.is_set() or result is None:
            yield chunk("", "cancelled")
            return
        usage, completion = self._usage(result, prep)
        yield chunk(
            "", self._finish(result, prep, completion), usage=usage, _warnings=prep.warnings
        )


def _tool_call_for_template(call: dict[str, Any]) -> dict[str, Any]:
    """`arguments` string JSON (format OpenAI) → objek, agar template Qwen merender JSON asli."""
    function = dict(call.get("function") or {})
    args = function.get("arguments")
    if isinstance(args, str):
        with contextlib.suppress(json.JSONDecodeError):
            function["arguments"] = json.loads(args)
    return {"id": call.get("id"), "type": call.get("type", "function"), "function": function}
