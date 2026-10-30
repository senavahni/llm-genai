# Integrasi klien

Gateway kompatibel dengan API OpenAI (`/v1/chat/completions`, `/v1/completions`,
`/v1/embeddings`, `/v1/images/generations`, `/v1/images/edits`, `/v1/models`). Semua SDK/tool yang
bisa mengganti *base URL* OpenAI bisa langsung dipakai.

| Yang dibutuhkan | Nilai |
|---|---|
| Base URL | `http://127.0.0.1:8000/v1` (mesin yang sama) · Mode B: `http://<host>:8080/v1` |
| API key | `lgw_...` dari admin (satu key per project/agent; lihat `docs/admin-api.http`) |
| Model | nama **route** (disarankan) atau alias model, lihat tabel di bawah dan `GET /v1/models` |

Semua contoh di bawah ada sebagai file yang bisa dijalankan di [`examples/`](../examples/) dan
sudah dieksekusi terhadap gateway yang berjalan (lihat "Hasil eksekusi" di akhir).

## Memilih model (route)

> **Profil aktif saat ini: `remote-only`** (semua model lokal nonaktif). Route `fast`, `smart`,
> `code`, `vision` hanya berisi kandidat remote; `local`, `autocomplete`, `image` dimatikan
> (tidak muncul di `/v1/models`). Tabel di bawah adalah profil `full`; isi route per profil ada
> di `docs/model-catalog.md` → Profil operasional. Selalu cek `GET /v1/models` untuk route yang
> tersedia bagi key Anda.

| Route | Isi (urutan fallback) | Pakai untuk |
|---|---|---|
| `fast` | Qwen2.5-7B lokal → Gemini Flash | task ringan, ringkasan, klasifikasi |
| `smart` | Claude Sonnet → GPT heavy → Qwen2.5-7B lokal | task berat / agent |
| `local` | Qwen2.5-7B → Qwen2.5-Coder-7B (lokal saja) | data yang tidak boleh keluar mesin |
| `code` | Qwen2.5-Coder-7B → Claude Sonnet → Qwen2.5-7B | chat/agent kode |
| `autocomplete` | Qwen2.5-Coder-1.5B (NPU, pinned) | FIM / tab-autocomplete |
| `vision` | Qwen2-VL-2B lokal → GPT light | gambar → teks |
| `image` | Stable Diffusion v1.5 (NPU, pinned) | text→image, image→image |
| `embed-default` | OpenAI text-embedding-3-small | embeddings (tidak ada embedding lokal) |

Provider remote yang key-nya tidak diisi di `.env` dilewati otomatis. Model lokal 7B berbagi satu
iGPU: berpindah antar `qwen2.5-7b` ↔ `qwen2.5-coder-7b` memicu swap (±3–5 s). Dalam satu alur agent
pilih satu model 7B. Header respons `X-Gateway-Model`, `X-Gateway-Provider`, `X-Gateway-Device`
memberi tahu siapa yang melayani.

## 1. Python — SDK `openai`

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key=os.environ["LGW_API_KEY"],
    default_headers={"X-Caller-Task": "ringkas-laporan", "X-Caller-Agent": "agent-a"},
    timeout=600,  # model lokal mungkin perlu swap sebelum token pertama
    max_retries=2,  # retry otomatis 429/5xx, menghormati Retry-After
)

# non-stream; with_raw_response untuk membaca header gateway
raw = client.chat.completions.with_raw_response.create(
    model="smart",
    messages=[
        {"role": "system", "content": "Jawab dalam satu kalimat."},
        {"role": "user", "content": "Apa ibu kota Indonesia?"},
    ],
    max_tokens=40,
)
resp = raw.parse()
print(resp.choices[0].message.content, raw.headers["x-request-id"])

# stream + usage di chunk terakhir
for chunk in client.chat.completions.create(
    model="fast",
    messages=[{"role": "user", "content": "Sebutkan tiga warna primer."}],
    stream=True,
    stream_options={"include_usage": True},
):
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

Contoh lain di [`examples/python_openai_sdk.py`](../examples/python_openai_sdk.py):

| Fitur | Pemanggilan |
|---|---|
| Tools (multi-turn) | `tools=[...]` → `message.tool_calls` → kirim `{"role": "tool", "tool_call_id": ..., "content": ...}` |
| JSON mode | `response_format={"type": "json_object"}` (lokal: dijamin JSON valid lewat grammar) |
| **FIM** | `client.completions.create(model="autocomplete", prompt=prefix, suffix=suffix, max_tokens=64)` |
| **Vision** | content `[{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]` (juga URL http/https) |
| **Images** | `client.images.generate(model="image", prompt=..., size="512x512", response_format="b64_json", extra_body={"steps": 20, "seed": 7})` |
| Image→image | `client.images.edit(model="image", image=open("in.png", "rb"), prompt=..., extra_body={"strength": 0.6})` |
| Embeddings | `client.embeddings.create(model="embed-default", input=[...])` (butuh `OPENAI_API_KEY` di server) |

Catatan images: SD v1.5 lokal hanya `512x512` (ukuran lain → 400 `unsupported_size`), `n` ≤ 4,
`steps` default 25 (maks 50), `strength` image→image default 0,6, ±20–30 detik per gambar. `response_format="url"` mengembalikan `/v1/images/files/...` yang hanya bisa diunduh
dengan key project yang sama dan kedaluwarsa sesuai retensi project.

## 2. JavaScript / TypeScript — SDK `openai`

```js
import OpenAI from "openai";
const client = new OpenAI({ baseURL: "http://127.0.0.1:8000/v1", apiKey: process.env.LGW_API_KEY });

const stream = await client.chat.completions.create({
  model: "fast", messages: [{ role: "user", content: "Hitung 1 sampai 5." }], stream: true,
});
for await (const chunk of stream) process.stdout.write(chunk.choices[0]?.delta?.content ?? "");

const fim = await client.completions.create({
  model: "autocomplete", prompt: "function add(a, b) {\n", suffix: "\n}\n", max_tokens: 32,
});
```
File lengkap: [`examples/js/example.mjs`](../examples/js/example.mjs) (`npm install && node example.mjs`).

## 3. HTTP mentah (curl) — debug header & SSE

```bat
curl -s -N http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer %LGW_API_KEY%" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"fast\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Halo\"}]}"
```
`-N` mematikan buffer sehingga tiap baris `data: {...}` tampil saat tiba, diakhiri `data: [DONE]`.
Error di tengah stream dikirim sebagai `data: {"error": {...}}` lalu `[DONE]`. Lebih banyak di
[`examples/curl.bat`](../examples/curl.bat).

## 4. Framework

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(base_url="http://127.0.0.1:8000/v1", api_key=KEY, model="smart")

from llama_index.llms.openai_like import OpenAILike

llm = OpenAILike(
    api_base="http://127.0.0.1:8000/v1",
    api_key=KEY,
    model="smart",
    is_chat_model=True,
    context_window=8192,
)
```
- **CrewAI**: `LLM(model="openai/smart", base_url="http://127.0.0.1:8000/v1", api_key=KEY)`
  (prefix `openai/` = provider OpenAI-compatible di LiteLLM).
- **AutoGen**: `OpenAIChatCompletionClient(model="smart", base_url=..., api_key=KEY,
  model_info={"vision": False, "function_calling": True, "json_output": True, "family": "unknown"})`.

`ChatOpenAI` dari `langchain-openai` dan `OpenAILike` sudah dieksekusi
([`examples/frameworks.py`](../examples/frameworks.py)); konfigurasi CrewAI/AutoGen mengikuti pola
OpenAI-compatible yang sama tetapi belum dieksekusi di sini.

## 5. Coding assistant

Pola umum: provider "OpenAI compatible", base URL `http://127.0.0.1:8000/v1`, API key `lgw_...`,
lalu model:
- **chat / agent kode** → `code` (Qwen2.5-Coder-7B lokal, fallback Claude bila ada key),
- **task berat** → `smart`,
- **tab-autocomplete** → `autocomplete` (Qwen2.5-Coder-1.5B di NPU, TTFT ±250 ms).

### Continue (`~/.continue/config.yaml`)
```yaml
name: llm-gateway
version: 0.0.1
schema: v1
models:
  - name: Gateway code
    provider: openai
    model: code
    apiBase: http://127.0.0.1:8000/v1
    apiKey: lgw_...
    roles: [chat, edit, apply]
  - name: Gateway autocomplete
    provider: openai
    model: autocomplete
    apiBase: http://127.0.0.1:8000/v1
    apiKey: lgw_...
    roles: [autocomplete]
    # nama "autocomplete" tidak dikenali Continue sebagai Qwen: berikan template FIM Qwen
    promptTemplates:
      autocomplete: "<|fim_prefix|>{{{prefix}}}<|fim_suffix|>{{{suffix}}}<|fim_middle|>"
    autocompleteOptions:
      maxPromptTokens: 512    # konteks kecil = TTFT rendah di NPU
      debounceDelay: 250
```
Continue mengirim prompt FIM yang sudah jadi ke `/v1/completions`; gateway meneruskannya apa adanya
ke model (token `<|fim_*|>` dikenali tokenizer Qwen). Format request ini sudah diuji langsung ke
gateway (lihat hasil eksekusi). Field `roles`, `apiBase`, dan `autocompleteOptions` sesuai referensi
`config.yaml` Continue saat dokumen ini ditulis. Cek ulang di
[docs.continue.dev/reference](https://docs.continue.dev/reference) bila versi Continue berubah.

### Cline / Roo Code
API Provider **OpenAI Compatible** → Base URL `http://127.0.0.1:8000/v1`, API Key `lgw_...`,
Model ID `code` (atau `smart`). Cline mengandalkan tool calling & konteks panjang. Model lokal 7B
(konteks 8K) cukup untuk tugas kecil; untuk tugas besar pakai `smart` dengan provider remote.

### Aider
```bat
set OPENAI_API_BASE=http://127.0.0.1:8000/v1
set OPENAI_API_KEY=lgw_...
aider --model openai/code --weak-model openai/fast
```

### Open WebUI
Settings → Connections → OpenAI API → URL `http://127.0.0.1:8000/v1` (dari container Docker milik
orang lain: `http://host.docker.internal:8000/v1`), key `lgw_...`. Daftar model diambil dari
`/v1/models` (hanya model yang diizinkan untuk key tersebut).

### Cursor
Settings → Models → *OpenAI API Key* + *Override OpenAI Base URL*. **Catatan penting:** request
model dari Cursor dikirim lewat server Cursor (bukan langsung dari editor), sehingga
`http://127.0.0.1:8000` atau IP LAN **tidak terjangkau**. Gateway harus diekspos lewat URL HTTPS
publik (tunnel seperti Cloudflare Tunnel / ngrok) ke Traefik (Mode B). Itu berarti gateway bisa
diakses dari internet: gunakan key khusus dengan kuota ketat dan jangan buka `/admin`. Mode Agent
Cursor dapat memakai Responses API yang tidak didukung gateway; gunakan mode Ask/chat. Tab
autocomplete Cursor selalu memakai model Cursor sendiri. Perilaku ini terdokumentasi di forum
Cursor dan bisa berubah di versi baru.

## 6. Pola agent: system prompt milik project

Gateway **tidak** menyuntikkan atau mengubah system prompt. Persona, aturan, dan format keluaran
dikirim oleh project sendiri, misalnya:
```python
SYSTEM = "Kamu agen penagihan PT X. Jawab formal, bahasa Indonesia, maksimal 3 kalimat."
client.chat.completions.create(
    model="smart",
    messages=[{"role": "system", "content": SYSTEM}, *riwayat, {"role": "user", "content": pesan}],
)
```
Isi `X-Caller-Task` / `X-Caller-Agent` (atau field `metadata` / `user`) agar pemakaian bisa
dilaporkan per task di `/admin/usage`.

## 7. Error & retry

Format error selalu `{"error": {"message", "type", "code", "param"}}` + header `X-Request-ID`.

| HTTP | `code` contoh | Tindakan klien |
|---|---|---|
| 400 | `invalid_request`, `unsupported_parameter`, `unsupported_size`, `context_length_exceeded` | perbaiki request; jangan retry |
| 401 / 403 | `invalid_api_key`, `model_not_allowed`, `scope_denied`, `project_suspended` | cek key / minta admin menambah pola model |
| 404 | `model_not_found` | cek `GET /v1/models` |
| 429 | `rate_limited`, `quota_exceeded` | tunggu `Retry-After` detik (SDK resmi otomatis) |
| 502 | `all_candidates_failed`, `upstream_error` | retry dengan backoff (semua kandidat route gagal) |
| 503 | `model_busy`, `service_unavailable` | retry setelah `Retry-After` (antrean GPU/NPU penuh) |
| 504 | `upstream_timeout` | retry; pertimbangkan route lain / `max_tokens` lebih kecil |

Status HTTP persis per `code` ada di `app/utils/errors.py`; klien sebaiknya bercabang pada
`error.code`, bukan teks `message`.

Header `X-RateLimit-Remaining-Requests` / `-Tokens` menunjukkan sisa jatah. Untuk penelusuran,
berikan nilai `X-Request-ID` ke admin: `GET /admin/requests/{id}` menampilkan detail attempt,
fallback, device, dan latensi.

## Hasil eksekusi

_Diisi setelah contoh dijalankan terhadap gateway._
