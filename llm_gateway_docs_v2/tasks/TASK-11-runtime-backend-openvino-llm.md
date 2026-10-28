# TASK-11 — Runtime Backend OpenVINO GenAI: Qwen Teks, Kode (FIM), Vision

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 3 hari |
| Dependensi | TASK-09, TASK-10 |
| Referensi PRD | §7.4 A–B, §8.3, §8.5, §9.4 |

> **Revisi 28 Okt 2026:** menggantikan backend llama.cpp. Semua model chat lokal adalah Qwen dan
> dijalankan `openvino_genai` di **GPU atau NPU** (device eksplisit, tidak pernah CPU). Embedding
> lokal dan model reasoning DeepSeek dihapus dari katalog (lihat TASK-09).

## Tujuan
Menjalankan model Qwen dalam format OpenVINO IR lewat `openvino_genai` dengan dukungan chat,
streaming, tool calling, JSON mode, FIM, dan vision, memakai format OpenAI di batas runtime.

| Alias | Device | Backend (`kind`) | Fitur |
|---|---|---|---|
| `qwen2.5-7b` | GPU | `openvino_llm` | chat, stream, tools, JSON |
| `qwen2.5-coder-7b` | GPU | `openvino_llm` | chat, stream, tools, JSON |
| `qwen2.5-coder-1.5b` | NPU (pinned) | `openvino_llm` | completions + FIM, stream |
| `qwen2-vl-2b` | GPU | `openvino_vlm` | chat + gambar, stream |

## Spesifikasi — `runtime/backends/ov_llm_backend.py` (`kind="openvino_llm"`)

### Load
```python
props = {"CACHE_DIR": OV_CACHE_DIR}
if device == "NPU":                       # NPU butuh shape statis
    props |= {"MAX_PROMPT_LEN": cfg.max_prompt_len, "MIN_RESPONSE_LEN": cfg.min_response_len}
pipe = openvino_genai.LLMPipeline(spec.artifact_path, device, **props)   # device = "GPU" | "NPU"
tokenizer = pipe.get_tokenizer()
```
- Device dari `models.config.device`, **hanya** `GPU`, `GPU.<n>`, atau `NPU`. `CPU`, `AUTO`,
  `HETERO`, `MULTI` ditolak validator (PRD §7.5 aturan 5) kecuali `ALLOW_CPU_FALLBACK=true`.
  OpenVINO tidak berpindah ke CPU diam-diam bila device eksplisit.
- `actual_device()` = device yang dipakai saat load. Bila load gagal (mis. compiler NPU menolak
  model) → `load_failed`, **tidak** dicoba di CPU.
- Verifikasi `artifact_sha256` (digest folder, `runtime/core/artifacts.py`) saat load pertama;
  hasil di-cache per proses.
- Event `load` mencatat `details={"device", "cache_dir", "compile_ms"}`. Compile pertama di NPU
  bisa ±1–2 menit; berikutnya dari `CACHE_DIR`.
- Satu `generate()` per pipeline pada satu waktu (pipeline tidak thread-safe); dijaga semaphore
  per model di Device Manager (TASK-10).

### Chat & streaming
- Stateless: setiap request membawa seluruh `messages`; tidak memakai `start_chat()`.
- Prompt = `tokenizer.apply_chat_template(messages, add_generation_prompt=True, tools=tools)`
  (template chat native dari IR), lalu `generate(prompt, config)` dengan
  `config.apply_chat_template = False`.
- Pemetaan parameter OpenAI → `GenerationConfig` (hanya field yang dikirim caller):

| OpenAI | GenerationConfig |
|---|---|
| `max_tokens` / `max_completion_tokens` | `max_new_tokens` (default `models.max_output_tokens`) |
| `temperature` | `temperature`; `do_sample = temperature > 0` |
| `top_p` | `top_p` |
| `stop` | `stop_strings` |
| `seed` | `rng_seed` |
| `presence_penalty`, `frequency_penalty` | sama |
| `provider_options.top_k`, `min_p`, `repetition_penalty` | sama (whitelist) |

- `response_format={"type":"json_object"}` → `StructuredOutputConfig(json_schema='{"type":"object"}')`;
  `json_schema` → skema dari caller. Grammar menjamin JSON valid.
- Stream: `generate` berjalan di thread device (`iterate_in_thread`) dengan streamer callback
  yang mengirim potongan teks ke antrean dan mengembalikan `StreamingStatus.CANCEL` bila `cancel`
  diset, sehingga generasi berhenti pada token berikutnya. `finish_reason="cancelled"` dicatat di
  runtime.
- Usage: `prompt_tokens` = panjang `tokenizer.encode(prompt)`, `completion_tokens` =
  `perf_metrics.get_num_generated_tokens()`.
- Batas NPU: prompt > `MAX_PROMPT_LEN` → 400 `context_length_exceeded` (non-FIM) atau dipangkas
  (FIM, lihat bawah).

### Tool calling (Qwen = Hermes)
- Definisi tools disisipkan template native (`apply_chat_template(..., tools=...)`); pesan `tool` dan
  `assistant.tool_calls` dari caller diteruskan ke template apa adanya.
- Output di-parse `runtime/backends/tool_parsers.py::parse_hermes`
  (`<tool_call>{"name","arguments"}</tool_call>`, bisa berulang) → `tool_calls` OpenAI
  (`id = call_<uuid8>`, `arguments` string JSON). Blok rusak tetap dikembalikan sebagai teks.
- Streaming dengan tools: buffer sejak `<tool_call>` sampai `</tool_call>`, lalu kirim
  `delta.tool_calls` lengkap per call. Teks di luar blok tetap di-stream sebagai `delta.content`.
- Test kontrak: percakapan multi-turn yang sama dengan TASK-08 lulus untuk `qwen2.5-7b` dan
  `qwen2.5-coder-7b`.

### Completion & FIM (`qwen2.5-coder-1.5b`, NPU)
- `/v1/completions` tanpa `suffix` → `generate(prompt)` mentah (`apply_chat_template=False`).
- Dengan `suffix` dan `supports_fim` → prompt = `cfg.fim_template.format(prefix=..., suffix=...)`,
  `stop_strings` += `cfg.fim_stop`, default `max_tokens=128`; token FIM dibuang dari hasil.
- Prompt FIM > `max_prompt_len`: pangkas awal `prefix` dan akhir `suffix` (bagian terjauh dari
  kursor) sampai muat, laporkan di `x_runtime.warnings`.
- Support `stream=true` untuk autocomplete. Target TTFT p50 < 300 ms (model pinned, tanpa load).

## Spesifikasi — `runtime/backends/ov_vlm_backend.py` (`kind="openvino_vlm"`)
- Load: `openvino_genai.VLMPipeline(spec.artifact_path, device, CACHE_DIR=...)`.
- Input: content part `image_url` berupa data URL base64 atau URL http(s), diproses
  `runtime/backends/image_input.py`:
  - URL http diunduh runtime dengan batas 10 MB dan timeout 10 detik; host privat ditolak
    (anti-SSRF: `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`).
  - Resize agar sisi terpanjang ≤ `cfg.max_image_px` (default 1280), maksimal `cfg.max_images`
    (default 4) per request.
  - Gambar → `ov.Tensor` uint8 `[1, H, W, 3]`.
- `generate(prompt, images=[...], generation_config=cfg)`; template chat diterapkan pipeline
  (menyisipkan token gambar). Streaming & cancel sama dengan LLM.

### Catatan implementasi (hasil uji hardware)
- **TTFT FIM di NPU**: prefill NPU berjalan per chunk statis. `prefill_chunk_size: 256`
  (`NPUW_LLM_PREFILL_CHUNK_SIZE`) + `fim_max_prompt_tokens: 256` → TTFT 1,6 s → **0,25 s**.
  Streamer per token buatan sendiri (TextStreamer bawaan menahan ±3 token) dan stop FIM satu-token
  lewat `stop_token_ids` (bukan `stop_strings`, yang menahan stream 1 token) memangkas sisa ±150 ms.
- **Qwen2.5-Coder-7B** kadang memanggil tool dengan format menyimpang
  (```` ```xml <tools>{…}</tools>``` ````). `parse_tool_output` menerima format ini hanya bila
  seluruh output adalah objek JSON dengan `name` dari tools caller; di stream, awal output yang
  mungkin tool call ditahan sampai jelas (jawaban kode biasa tetap mengalir).

## Deliverables
- [x] `ov_llm_backend.py`, `ov_vlm_backend.py`, `image_input.py`
- [x] `tool_parsers.py` (`parse_hermes`, `parse_lenient`, `StreamToolParser`) + unit test
- [x] Validator device config (tolak `CPU`/`AUTO`/`HETERO`/`MULTI`) — `ov_common.validate_device`
- [x] Unit test dengan pipeline palsu: pemetaan parameter, JSON mode, stream, cancel, FIM pangkas,
      stop string, vision, SSRF (`tests/unit/runtime/test_ov_llm.py`, `test_image_input.py`,
      `test_tool_stream_parser.py`)
- [x] Test hardware (`pytest --hardware tests/hardware/test_llm.py`): tools multi-turn
      (Qwen2.5-7B & Coder-7B, stream & non-stream), stream, cancel, JSON ×100, FIM TTFT, vision —
      semua lulus

## Acceptance Criteria
1. Keempat model Qwen dapat dipanggil via runtime di device katalognya (GPU/NPU); tidak ada
   inferensi di CPU (device eksplisit, `cpu_ratio` rendah seperti pengukuran TASK-09).
2. Tool calling multi-turn lulus untuk Qwen2.5-7B dan Qwen2.5-Coder-7B (non-stream & stream).
3. FIM Coder-1.5B di NPU: TTFT p50 < 300 ms untuk prompt ≤ 512 token; hasil tanpa token FIM.
4. Vision Qwen2-VL-2B menjawab pertanyaan tentang gambar uji.
5. Cancel di tengah stream menghentikan generasi < 500 ms, dan model siap melayani request berikutnya.
6. `response_format=json_object` selalu menghasilkan JSON valid (100 percobaan).
