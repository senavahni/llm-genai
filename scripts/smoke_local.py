"""Smoke test kualitas singkat model Qwen lokal (TASK-09 langkah 8), langsung via OpenVINO GenAI
di device katalog (GPU/NPU). Satu model per waktu; output → docs/smoke/. SD diuji test_sd.py.

    scripts\\conda-run.bat python scripts\\smoke_local.py
    scripts\\conda-run.bat python scripts\\smoke_local.py --only local/qwen2.5-coder-1.5b
"""

import argparse
import gc
import io
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.backends.tool_parsers import parse_hermes  # noqa: E402
from scripts._seedfile import load_seed, local_models  # noqa: E402
from scripts.measure_models import pipeline_properties  # noqa: E402

OUT = ROOT / "docs" / "smoke"
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Ambil cuaca terkini sebuah kota",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
CITY_SCHEMA = {
    "type": "object",
    "properties": {"kota": {"type": "string"}, "provinsi": {"type": "string"}},
    "required": ["kota", "provinsi"],
}


def _device(m: dict[str, Any]) -> str:
    return str((m.get("config") or {}).get("device", "GPU"))


def _pipe(m: dict[str, Any]) -> Any:
    import openvino_genai as ov_genai

    device = _device(m)
    cls = ov_genai.VLMPipeline if m["runtime_backend"] == "openvino_vlm" else ov_genai.LLMPipeline
    return cls(str(ROOT / m["artifact_path"]), device, **pipeline_properties(m, device))


def _config(max_new_tokens: int, **kw: Any) -> Any:
    import openvino_genai as ov_genai

    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = max_new_tokens
    cfg.do_sample = False
    cfg.apply_chat_template = False  # prompt sudah diformat template chat native
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _chat_prompt(pipe: Any, user: str, **kw: Any) -> str:
    history = [{"role": "user", "content": user}]
    return str(pipe.get_tokenizer().apply_chat_template(history, True, **kw))


def _generate(pipe: Any, prompt: str, cfg: Any) -> str:
    return str(pipe.generate([prompt], cfg).texts[0])


# ------------------------------------------------------------------ tes per model
def tool_call(m: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    import openvino_genai as ov_genai

    pipe = _pipe(m)
    prompt = _chat_prompt(pipe, "Bagaimana cuaca di Bandung sekarang?", tools=[WEATHER_TOOL])
    raw = _generate(pipe, prompt, _config(256))
    parsed = parse_hermes(raw)
    call = parsed.tool_calls[0]["function"] if parsed.tool_calls else {}
    ok_tool = call.get("name") == "get_weather" and "bandung" in call.get("arguments", "").lower()

    # JSON mode / json_schema lewat structured output (grammar), dasar AC6 TASK-11
    json_cfg = _config(128)
    json_cfg.structured_output_config = ov_genai.StructuredOutputConfig(
        json_schema=json.dumps(CITY_SCHEMA)
    )
    json_raw = _generate(
        pipe, _chat_prompt(pipe, "Bandung ada di provinsi apa? Jawab dalam JSON."), json_cfg
    )
    try:
        obj = json.loads(json_raw)
        ok_json = isinstance(obj, dict) and {"kota", "provinsi"} <= obj.keys()
    except json.JSONDecodeError:
        ok_json = False
    return ok_tool and ok_json, {
        "raw_tool_output": raw,
        "tool_calls": parsed.tool_calls,
        "json_output": json_raw,
        "ok_tool": ok_tool,
        "ok_json": ok_json,
    }


def fim(m: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    cfg = m["config"]
    prefix = 'def is_prime(n: int) -> bool:\n    """True bila n bilangan prima."""\n'
    suffix = "\n\nprint(is_prime(7))\n"
    prompt = cfg["fim_template"].format(prefix=prefix, suffix=suffix)
    pipe = _pipe(m)
    _generate(pipe, prompt, _config(8))  # pemanasan (alokasi pertama)
    t = time.perf_counter()
    text = _generate(pipe, prompt, _config(128, stop_strings=set(cfg.get("fim_stop") or [])))
    total_s = time.perf_counter() - t
    for stop in cfg.get("fim_stop") or []:
        text = text.split(stop)[0]
    ns: dict[str, Any] = {}
    try:
        exec(compile(prefix + text, "<fim>", "exec"), ns)  # noqa: S102 - kode dari model, diuji lokal
        ok = ns["is_prime"](7) and not ns["is_prime"](9) and ns["is_prime"](2)
    except Exception as exc:  # noqa: BLE001
        ok = False
        text += f"\n# ERROR: {exc}"
    return bool(ok), {"completion": text, "total_s": round(total_s, 2)}


def code_chat(m: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    pipe = _pipe(m)
    prompt = _chat_prompt(
        pipe,
        "Tulis fungsi Python `slugify(text: str) -> str` dan satu unit test pytest untuknya. "
        "Hanya kode.",
    )
    content = _generate(pipe, prompt, _config(400))
    return "def slugify" in content and "def test_" in content, {"content": content}


def vision(m: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    import numpy as np
    import openvino as ov
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 110, 150], fill="red")
    draw.text((130, 70), "GATEWAY 42", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    (OUT / "vision_input.png").write_bytes(buf.getvalue())
    pipe = _pipe(m)
    cfg = _config(128)
    cfg.apply_chat_template = True  # VLMPipeline menyisipkan token gambar lewat template
    result = pipe.generate(
        "Describe this image: what colored shape and what text?",
        images=[ov.Tensor(np.asarray(img, dtype=np.uint8)[None])],
        generation_config=cfg,
    )
    content = str(result.texts[0]).lower()
    ok = "red" in content and ("42" in content or "gateway" in content)
    return ok, {"content": content}


TESTS: dict[str, Callable[[dict[str, Any]], tuple[bool, dict[str, Any]]]] = {
    "local/qwen2.5-7b": tool_call,
    "local/qwen2.5-coder-7b": code_chat,
    "local/qwen2.5-coder-1.5b": fim,
    "local/qwen2-vl-2b": vision,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    summary = {k: v for k, v in summary.items() if k in TESTS or k == "local/sd-1.5"}
    for m in local_models(load_seed(), only):
        test = TESTS.get(m["alias"])
        if test is None:
            print(f"{m['alias']}: lewati (SD diuji lewat test_sd.py)")
            continue
        if not (ROOT / m["artifact_path"]).exists():
            print(f"{m['alias']}: lewati, artefak belum ada")
            continue
        print(f"{m['alias']} [{_device(m)}]: {test.__name__} ...", flush=True)
        t = time.perf_counter()
        try:
            ok, detail = test(m)
        except Exception as exc:  # noqa: BLE001 - catat lalu lanjut model berikutnya
            ok, detail = False, {"error": f"{type(exc).__name__}: {exc}"}
        elapsed = round(time.perf_counter() - t, 1)
        gc.collect()
        summary[m["alias"]] = {
            "test": test.__name__,
            "device": _device(m),
            "ok": ok,
            "seconds": elapsed,
        }
        name = m["alias"].split("/")[-1]
        (OUT / f"{name}.json").write_text(
            json.dumps(
                {
                    "alias": m["alias"],
                    "device": _device(m),
                    "test": test.__name__,
                    "ok": ok,
                    "seconds": elapsed,
                    **detail,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  {'OK' if ok else 'GAGAL'} ({elapsed}s)")
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if all(v["ok"] for v in summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
