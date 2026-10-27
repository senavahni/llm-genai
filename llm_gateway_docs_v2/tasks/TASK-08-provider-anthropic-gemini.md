# TASK-08 — Provider Adapter: Anthropic (Claude) & Google Gemini

| Item | Nilai |
|---|---|
| Milestone | M2 Provider Remote |
| Prioritas | P0 |
| Estimasi | 2 hari |
| Dependensi | TASK-06 |
| Referensi PRD | §8.5, F5 |

## Tujuan
Menerjemahkan format OpenAI ↔ format native Claude dan Gemini, termasuk tool calling dan streaming.

---

## A. Anthropic — `anthropic_provider.py`, `code="anthropic"`
SDK: `anthropic.AsyncAnthropic(api_key=..., http_client=shared, max_retries=0)`. Cek dokumentasi resmi untuk nama model & fitur terbaru saat implementasi.

### Request mapping
| OpenAI (unified) | Anthropic Messages API |
|---|---|
| message `system` (bisa >1) | digabung ke param `system` (string atau list text block) |
| `user`/`assistant` content string | `content` string |
| content part `image_url` (data URL base64 / http URL) | block `{"type":"image","source":{"type":"base64"|"url",...}}` |
| assistant `tool_calls[]` | assistant content block `tool_use {id, name, input(json.loads(arguments))}` |
| message `tool` (`tool_call_id`, content) | **user** message berisi block `tool_result {tool_use_id, content}`; beberapa tool result berurutan digabung ke satu user message |
| `tools[].function{name, description, parameters}` | `tools[]{name, description, input_schema}` |
| `tool_choice`: `"auto"` / `"required"` / `"none"` / `{"function":{"name"}}` | `{"type":"auto"}` / `{"type":"any"}` / `{"type":"none"}` / `{"type":"tool","name"}` |
| `max_tokens` (opsional) | **wajib** → `req.max_tokens or model.max_output_tokens or 4096` |
| `stop` | `stop_sequences` |
| `response_format: json_object` | tidak native: jika `models.config.json_mode_strategy="prefill"`, tambahkan prefill `{`; default → teruskan saja (caller atur via prompt) dan log DEBUG |
| `provider_options` | merge ke payload (mis. `thinking`, `metadata`, `top_k`) |

Pesan berurutan dengan role sama digabung (Anthropic mensyaratkan alternasi user/assistant).

### Response mapping
- Block `text` → `content` (concat).
- Block `tool_use` → `tool_calls[{id, type:"function", function:{name, arguments: json.dumps(input)}}]`.
- Block `thinking` → tidak dimasukkan ke `content`; disimpan di field ekstensi `reasoning_content` bila caller meminta via `provider_options.include_reasoning=true`.
- `stop_reason`: `end_turn`→`stop`, `max_tokens`→`length`, `tool_use`→`tool_calls`, `stop_sequence`→`stop`.
- Usage: `input_tokens` (+ `cache_read_input_tokens` → `cached_tokens`, `cache_creation_input_tokens` dijumlahkan ke prompt), `output_tokens`.

### Streaming
Event → chunk:
- `message_start` → simpan `usage.input_tokens`, id.
- `content_block_start` tipe `tool_use` → `delta_tool_calls[{index, id, name, arguments:""}]`.
- `content_block_delta` `text_delta` → `delta_content`; `input_json_delta` → `delta_tool_calls[{index, arguments: partial_json}]`.
- `message_delta` → `finish_reason` + `output_tokens`.
- `message_stop` → chunk usage final.
- `error` event (mis. `overloaded_error`) sebelum chunk pertama → `UpstreamError` (retryable).
Index tool call OpenAI = urutan tool_use block (bukan index content block mentah).

### Error mapping
`APITimeoutError`→Timeout, `RateLimitError`→UpstreamRateLimited, `InternalServerError`/status 529 overloaded→UpstreamError, `BadRequestError`→UpstreamBadRequest.

Embeddings: tidak didukung → `CapabilityNotSupported`.

---

## B. Gemini — `gemini_provider.py`, `code="gemini"`
SDK: `google-genai` (`genai.Client(api_key=...)`, gunakan `client.aio`). Verifikasi nama method di versi SDK terbaru saat implementasi.

### Request mapping
| Unified | Gemini |
|---|---|
| message `system` | `config.system_instruction` |
| `user` | `Content(role="user", parts=[...])` |
| `assistant` | `Content(role="model", ...)`; `tool_calls` → `Part(function_call={name, args})` |
| `tool` | `Content(role="user", parts=[Part(function_response={name, response})])` — `name` diambil dari pemetaan `tool_call_id → name` pada riwayat sebelumnya |
| image (base64) | `Part(inline_data={mime_type, data})` |
| `tools` | `Tool(function_declarations=[{name, description, parameters}])` — bersihkan keyword JSON Schema yang tidak didukung (mis. `$schema`, `additionalProperties`) |
| `tool_choice` | `tool_config.function_calling_config.mode`: AUTO/ANY/NONE (+ `allowed_function_names`) |
| `temperature`, `top_p`, `max_tokens`, `stop`, `seed` | `temperature`, `top_p`, `max_output_tokens`, `stop_sequences`, `seed` |
| `response_format: json_object` / `json_schema` | `response_mime_type="application/json"` (+ `response_schema`) |

Gemini tidak memberi id tool call → generate `call_<uuid8>` dan simpan mapping.

### Response mapping
- `candidates[0].content.parts`: text → content; `function_call` → tool_calls.
- `finish_reason`: STOP→`stop`, MAX_TOKENS→`length`, SAFETY/RECITATION/BLOCKLIST→`content_filter`; ada function_call → `tool_calls`.
- Usage: `usage_metadata.prompt_token_count`, `candidates_token_count` (+ `thoughts_token_count` dijumlahkan ke completion), `cached_content_token_count`.

### Streaming
`generate_content_stream` → setiap response parsial → `delta_content`; function_call biasanya datang utuh → kirim sebagai satu `delta_tool_calls` lengkap. Usage dari chunk terakhir.

### Embeddings
`embed_content(model, contents=list, config={"output_dimensionality": dims})` → list vektor. Token usage tidak dikembalikan → estimasi (`estimated=True`).

### Error mapping
`google.genai.errors.APIError` berdasarkan `code`: 429→RateLimited, ≥500→UpstreamError, 400→BadRequest; timeout httpx → UpstreamTimeout.

---

## Deliverables
- [ ] `anthropic_provider.py`, `gemini_provider.py`
- [ ] Modul translator terpisah & dapat diuji: `app/services/providers/translate/anthropic_map.py`, `gemini_map.py`
- [ ] Test kontrak tool-calling (fixture percakapan multi-turn dengan 2 tool call paralel + tool result)

## Acceptance Criteria
1. Percakapan agent multi-turn (user → assistant tool_calls ×2 → tool ×2 → assistant final) berhasil di Claude dan Gemini via SDK OpenAI pemanggil.
2. Stream tool call menghasilkan argumen JSON valid setelah digabung caller.
3. `finish_reason` & usage terpetakan sesuai tabel.
4. Unit test translator mencakup: multiple system, gambar base64, role berurutan sama, tool_choice semua varian.
