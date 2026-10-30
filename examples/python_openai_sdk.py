"""Contoh lengkap SDK `openai` (Python) terhadap gateway — dieksekusi sebagai bagian TASK-23.

set LGW_BASE_URL=http://127.0.0.1:8000/v1
set LGW_API_KEY=lgw_...
python examples/python_openai_sdk.py            (semua contoh)
python examples/python_openai_sdk.py fim vision (sebagian)
"""

import base64
import io
import json
import os
import sys

import openai
from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("LGW_BASE_URL", "http://127.0.0.1:8000/v1"),
    api_key=os.environ["LGW_API_KEY"],
    # header opsional untuk pelacakan biaya per task/agent di laporan admin
    default_headers={"X-Caller-Task": "contoh-dokumentasi", "X-Caller-Agent": "examples"},
    timeout=600,  # model lokal 7B bisa perlu swap (± 5–15 s) sebelum token pertama
    max_retries=2,  # SDK otomatis retry 429/5xx dengan menghormati Retry-After
)


def chat() -> None:
    raw = client.chat.completions.with_raw_response.create(
        model="smart",
        messages=[
            # gateway TIDAK menyuntikkan system prompt: persona/aturan dikirim project sendiri
            {"role": "system", "content": "Kamu asisten singkat. Jawab dalam satu kalimat."},
            {"role": "user", "content": "Apa ibu kota Indonesia?"},
        ],
        max_tokens=40,
    )
    resp = raw.parse()
    print("chat:", resp.choices[0].message.content)
    print(
        "  model:", raw.headers["x-gateway-model"], "device:", raw.headers.get("x-gateway-device")
    )
    print("  request id (untuk penelusuran admin):", raw.headers["x-request-id"])


def stream() -> None:
    print("stream: ", end="")
    events = client.chat.completions.create(
        model="fast",
        messages=[{"role": "user", "content": "Sebutkan tiga warna primer."}],
        max_tokens=40,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in events:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
        if chunk.usage:
            print(f"\n  usage: {chunk.usage.prompt_tokens} + {chunk.usage.completion_tokens} token")


def tools() -> None:
    weather = {
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
    messages = [{"role": "user", "content": "Bagaimana cuaca di Bandung sekarang?"}]
    first = client.chat.completions.create(
        model="local", messages=messages, tools=[weather], temperature=0, max_tokens=128
    )
    call = first.choices[0].message.tool_calls[0]
    print("tools: model memanggil", call.function.name, call.function.arguments)
    # jalankan fungsi di sisi project, kirim hasilnya kembali
    messages += [
        first.choices[0].message.model_dump(exclude_none=True),
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps({"suhu_c": 21, "cuaca": "hujan"}),
        },
    ]
    final = client.chat.completions.create(
        model="local", messages=messages, tools=[weather], max_tokens=80
    )
    print("  jawaban:", final.choices[0].message.content)


def json_mode() -> None:
    resp = client.chat.completions.create(
        model="local",
        messages=[{"role": "user", "content": "Data satu kota di Jawa Barat dalam JSON."}],
        response_format={"type": "json_object"},
        max_tokens=80,
    )
    print("json:", json.loads(resp.choices[0].message.content))


def fim() -> None:
    # autocomplete kode: Qwen2.5-Coder-1.5B di NPU (pinned), TTFT ±250 ms
    resp = client.completions.create(
        model="autocomplete",
        prompt='def is_prime(n: int) -> bool:\n    """True bila n bilangan prima."""\n',
        suffix="\n\nprint(is_prime(7))\n",
        max_tokens=64,
        temperature=0,
    )
    print("fim:\n" + resp.choices[0].text)


def vision() -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 160), "white")
    ImageDraw.Draw(img).rectangle([10, 10, 110, 150], fill="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    resp = client.chat.completions.create(
        model="vision",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is the shape in this image?"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        max_tokens=40,
    )
    print("vision:", resp.choices[0].message.content)


def images() -> None:
    # SD v1.5 di NPU, ±20–30 detik per gambar 512²; parameter tambahan lewat extra_body
    resp = client.images.generate(
        model="image",
        prompt="a small red house near a lake, watercolor",
        size="512x512",
        n=1,
        response_format="b64_json",
        extra_body={"steps": 20, "seed": 7},
    )
    out = "contoh-gambar.png"
    with open(out, "wb") as fh:
        fh.write(base64.b64decode(resp.data[0].b64_json))
    print("images: tersimpan di", out)


def embeddings() -> None:
    # route embed-default = OpenAI text-embedding-3-small (tidak ada embedding lokal)
    resp = client.embeddings.create(model="embed-default", input=["halo", "dunia"])
    print("embeddings:", len(resp.data), "vektor, dimensi", len(resp.data[0].embedding))


def errors() -> None:
    try:
        client.chat.completions.create(
            model="model-yang-tidak-ada", messages=[{"role": "user", "content": "x"}]
        )
    except openai.APIStatusError as exc:
        body = exc.response.json()["error"]
        print(
            f"errors: HTTP {exc.status_code} code={body['code']} request_id="
            f"{exc.response.headers.get('x-request-id')}"
        )


EXAMPLES = {
    f.__name__: f for f in (chat, stream, tools, json_mode, fim, vision, images, embeddings, errors)
}

if __name__ == "__main__":
    for name in sys.argv[1:] or EXAMPLES:
        try:
            EXAMPLES[name]()
        except openai.APIStatusError as exc:
            print(f"{name}: GAGAL HTTP {exc.status_code}: {exc.response.text[:200]}")
