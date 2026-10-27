# TASK-11 — Runtime Backend llama.cpp: Teks, Kode (FIM), Vision, Embedding

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 3 hari |
| Dependensi | TASK-09, TASK-10 |
| Referensi PRD | §7.4 A–B, §8.3, §8.5, §9.4 |

## Tujuan
Menjalankan seluruh model GGUF di GPU melalui `llama-cpp-python`, dengan dukungan chat, streaming, tool calling, JSON mode, FIM, vision (Qwen2-VL), dan embedding. Backend cadangan `llama-server.exe` dipakai bila sebuah fitur/model tidak didukung wheel yang terpasang.

Model yang dilayani:
- `qwen2.5-7b`, `qwen2.5-coder-7b`, `qwen2.5-coder-1.5b`, `qwen2-vl-2b`
- `llama-3.2-3b`, `llama-3.1-8b`, `phi-3.5-mini`, `deepseek-r1-qwen-7b`, `nomic-embed`

## Spesifikasi — `runtime/backends/llamacpp_backend.py` (`kind="llama_cpp_python"`)

### Load
```python
Llama(
  model_path=spec.artifact_path,          # shard pertama bila model di-split
  n_gpu_layers=-1,                        # SEMUA layer ke GPU (wajib)
  n_ctx=cfg.n_ctx, n_batch=cfg.n_batch, flash_attn=cfg.flash_attn,
  type_k=GGML_TYPE[cfg.type_k], type_v=GGML_TYPE[cfg.type_v],   # q8_0 untuk model heavy
  chat_format=cfg.chat_format,            # None = template Jinja dari metadata GGUF
  chat_handler=vision_handler_or_None,
  embedding=cfg.embedding, pooling_type=..., 
  offload_kqv=True, use_mmap=True, verbose=True,   # log native → logger runtime DEBUG
)
```
- Verifikasi sha256 artefak saat load pertama (cache hasil per proses).
- `actual_device()`: parse log native atau metadata (`llm_load_tensors: offloaded N/N layers to GPU`). Bila `offloaded < total` → anggap `cpu`/parsial dan tolak (PRD §7.5 aturan 5).
- Nama parameter (`flash_attn`, `type_k`, `pooling_type`, dst.) **disesuaikan dengan versi `llama-cpp-python` yang ter-pin** di `requirements-local.txt`. Buat test yang gagal bila signature berubah.

### Chat & streaming
- `create_chat_completion(messages, temperature, top_p, max_tokens, stop, seed, response_format, stream, ...)` hanya dengan field yang dikirim caller, ditambah `provider_options` lokal yang di-whitelist: `top_k`, `min_p`, `repeat_penalty`, `presence_penalty`, `frequency_penalty`, `mirostat_*`, `grammar`, `logit_bias`.
- `response_format={"type":"json_object"}` / `json_schema` → grammar JSON bawaan llama-cpp-python.
- Stream: iterator di thread → queue → SSE. `cancel` diperiksa tiap chunk; bila diset, generator ditutup (`close()`) sehingga generasi berhenti. `finish_reason="cancelled"` dicatat di runtime.
- Usage: dari respons akhir (`usage`). Untuk stream, hitung `completion_tokens` dari jumlah token yang dihasilkan dan `prompt_tokens` dari `llm.tokenize(prompt_terformat)`.

### Tool calling
Template Jinja GGUF menyisipkan definisi tools ke prompt, tetapi output model perlu di-*parse* menjadi `tool_calls` OpenAI. Parser dipilih per model lewat `models.config.tool_parser`:

| Parser | Model | Pola output |
|---|---|---|
| `hermes` | Qwen2.5-7B, Qwen2.5-Coder-7B | `<tool_call>{"name":..,"arguments":{..}}</tool_call>` (bisa berulang) |
| `llama3_json` | Llama-3.1-8B, Llama-3.2-3B | JSON `{"name":..,"parameters":{..}}` di awal jawaban, atau `<\|python_tag\|>` |
| `none` | Phi-3.5, DeepSeek-R1, Qwen2-VL | `supports_tools=false` di DB |

- Bila template GGUF tidak menyisipkan tools, gunakan `tool_chat_format` (mis. `chatml-function-calling`) sebagai cadangan.
- Streaming dengan tools: buffer token sejak penanda awal tool (`<tool_call>` / `{` di posisi awal) sampai penanda akhir, lalu kirim `delta_tool_calls` lengkap per call (id `call_<uuid8>`). Teks di luar penanda tetap di-stream sebagai `delta_content`.
- Pesan `tool` dan `assistant.tool_calls` dari caller diteruskan ke template apa adanya (format OpenAI), karena template Qwen/Llama mendukung role `tool`.
- Test kontrak: percakapan multi-turn yang sama dengan TASK-08 harus lulus untuk `qwen2.5-7b` dan `llama-3.1-8b`.

### Completion & FIM (`qwen2.5-coder-1.5b`)
- `/v1/completions` tanpa `suffix` → `create_completion(prompt=...)` (raw).
- Dengan `suffix` dan `supports_fim` → prompt = `cfg.fim_template.format(prefix=prompt, suffix=suffix)`, tambahkan `cfg.fim_stop` ke `stop`, default `max_tokens=128`, `temperature` hanya bila dikirim caller.
- Support `stream=true` untuk autocomplete.
- Target latensi: TTFT p50 < 300 ms (model pinned, tanpa load).
- Model pinned ini memakai `replicas: 1` default; ubah ke 2 hanya bila budget GPU masih cukup (cek di TASK-09).

### Vision (`qwen2-vl-2b`)
- Handler: `MTMDChatHandler(clip_model_path=cfg.mmproj_path, verbose=False)`; nama parameter mengikuti versi wheel. Bila handler/arsitektur Qwen2-VL belum didukung → `load_failed(reason='vision_handler_unsupported')` dan Device Manager beralih ke `cfg.fallback_backend="llama_server"`.
- Input: content part `image_url` berupa data URL base64 atau URL http(s).
  - URL http diunduh oleh runtime dengan batas 10 MB dan timeout 10 detik; host privat ditolak (anti-SSRF: tolak `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`).
  - Gambar di-resize agar sisi terpanjang ≤ `cfg.max_image_px` (default 1280) untuk membatasi token visual dan VRAM.
- Banyak gambar per pesan diizinkan maksimal `cfg.max_images` (default 4).

### Embedding (`nomic-embed`)
- `Llama(embedding=True)` → `create_embedding(input)`, normalisasi L2 bila `cfg.normalize`.
- Prefix tugas: `cfg.query_prefix` / `cfg.document_prefix` hanya diterapkan bila caller mengirim `provider_options.input_type = "query" | "document"` (gateway tidak menambah behavior diam-diam).
- Usage = jumlah token hasil `tokenize`.

### Reasoning (`deepseek-r1-qwen-7b`)
- Default: output diteruskan apa adanya, termasuk `<think>…</think>`.
- Bila caller mengirim `provider_options.separate_reasoning=true` → isi `<think>` dipindah ke field ekstensi `reasoning_content` (non-stream dan stream).

## Spesifikasi — `runtime/backends/llama_server_backend.py` (`kind="llama_server"`, cadangan)
- `load()`: spawn `LLAMA_SERVER_EXE` dengan `-m <gguf> [--mmproj <file>] -ngl 99 -c <n_ctx> --host 127.0.0.1 --port <port bebas 8110–8199> --jinja [-fa] --no-webui`, `stdout/stderr` ke `logs/llama-server-<alias>.log`. Tunggu `GET /health` = ok (timeout 180 detik).
- Inferensi: proxy HTTP (httpx) ke `/v1/chat/completions` milik proses tersebut; format sudah OpenAI.
- `unload()`: `terminate()` lalu `kill()` setelah 10 detik. VRAM dihitung Device Manager sama seperti backend lain.
- `actual_device()`: periksa log server untuk jumlah layer ter-offload.
- Flag disesuaikan versi binary (cek `llama-server --help`).

## Deliverables
- [ ] `llamacpp_backend.py`, `llama_server_backend.py`
- [ ] `runtime/backends/tool_parsers.py` (`hermes`, `llama3_json`) + unit test teks/stream
- [ ] `runtime/backends/image_input.py` (decode, resize, anti-SSRF)
- [ ] Konfigurasi `models.config` final ke-9 model di `seed_models.yaml`
- [ ] Test integrasi hardware (`@pytest.mark.gpu`) per model: chat, stream, cancel; tools untuk model `supports_tools`; FIM; vision; embedding

## Acceptance Criteria
1. Ke-9 model GGUF dapat dipanggil via runtime; log menunjukkan semua layer di GPU.
2. Tool calling multi-turn lulus untuk Qwen2.5-7B, Qwen2.5-Coder-7B, dan Llama-3.1-8B (non-stream & stream).
3. FIM Coder-1.5B: TTFT p50 < 300 ms, hasil tidak menyertakan token FIM.
4. Vision Qwen2-VL-2B menjawab pertanyaan tentang gambar uji (via `mtmd` atau backend cadangan, dicatat yang mana di `docs/hardware.md`).
5. Cancel di tengah stream menghentikan generasi < 500 ms, dan model siap melayani request berikutnya.
6. `response_format=json_object` selalu menghasilkan JSON valid (100 percobaan).
