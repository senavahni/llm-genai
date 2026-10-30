# Katalog model

Sumber kebenaran katalog adalah tabel `models` + `model_routes` di DB. Awalnya diisi dari
`scripts/seed_models.yaml` (`manage.py seed`), lalu dikelola lewat Admin API tanpa mengubah kode.
Runtime lokal membaca model `device ∈ {gpu, npu}` dari DB (`POST /admin/cache/reload` setelah
perubahan).

Sejak 28 Okt 2026 model lokal hanya keluarga **Qwen + Stable Diffusion v1.5**, semuanya OpenVINO
IR di GPU/NPU (keputusan & pengukuran: `docs/hardware.md`). Tidak ada embedding lokal; embedding
dilayani provider remote.

> **Status saat ini (30 Okt 2026): profil `remote-only`.** Semua model lokal nonaktif agar mesin
> ringan; gateway hanya memakai API remote. Lihat [Profil operasional](#profil-operasional) untuk
> mengaktifkan kembali, dan [Menambah API pihak ketiga](#menambah-api-pihak-ketiga-provider-custom)
> untuk provider selain OpenAI/Anthropic/Gemini.

## Model lokal

| Alias | Device | Kuantisasi | Memori (`vram_mb`, terukur) | Konteks / output maks | Kapabilitas | Kegunaan |
|---|---|---|---|---|---|---|
| `local/qwen2.5-7b` | GPU | INT4 (IR resmi OpenVINO) | 4900 | 8192 / 4096 | chat, stream, tools, JSON | asisten umum, agent ringan, data privat |
| `local/qwen2.5-coder-7b` | GPU | INT4 (IR resmi OpenVINO) | 5000 | 8192 / 4096 | chat, stream, tools, JSON | chat/agent kode |
| `local/qwen2.5-coder-1.5b` | NPU, pinned | INT4 sym per-channel | 2800 | 4096 / 1024 (FIM ±256 token konteks) | completion, **FIM** | tab-autocomplete |
| `local/qwen2-vl-2b` | GPU | INT4 | 2100 | 4096 / 2048, ≤ 4 gambar ≤ 1280 px | chat, stream, **vision** | OCR/deskripsi gambar ringan |
| `local/sd-1.5` | NPU, pinned | INT8 | 3300 | 512×512, 25 step default (maks 50) | text→image, image→image | ilustrasi, draft gambar |

`vram_mb` diukur dengan `scripts/measure_models.py` (puncak memori proses di GPU/NPU, cache compile
hangat). GPU & NPU di mesin target memakai **RAM sistem** (UMA), lihat
[perf-report](perf-report.md#ram-sistem).

### Sumber, integritas & lisensi

| Alias | Sumber (Hugging Face) | Artefak lokal | Lisensi | Catatan penggunaan |
|---|---|---|---|---|
| `local/qwen2.5-7b` | `OpenVINO/Qwen2.5-7B-Instruct-int4-ov` (dari `Qwen/Qwen2.5-7B-Instruct`) | `local_models/openvino/qwen2.5-7b-int4` | Apache-2.0 | bebas, cantumkan atribusi |
| `local/qwen2.5-coder-7b` | `OpenVINO/Qwen2.5-Coder-7B-Instruct-int4-ov` | `local_models/openvino/qwen2.5-coder-7b-int4` | Apache-2.0 | bebas, cantumkan atribusi |
| `local/qwen2.5-coder-1.5b` | `Qwen/Qwen2.5-Coder-1.5B-Instruct`, dikonversi lokal | `local_models/openvino/qwen2.5-coder-1.5b-int4-npu` | Apache-2.0 | bebas, cantumkan atribusi |
| `local/qwen2-vl-2b` | `Qwen/Qwen2-VL-2B-Instruct`, dikonversi lokal | `local_models/openvino/qwen2-vl-2b-int4` | Apache-2.0 | bebas, cantumkan atribusi |
| `local/sd-1.5` | `stable-diffusion-v1-5/stable-diffusion-v1-5`, dikonversi lokal | `local_models/openvino/sd15-int8` | CreativeML OpenRAIL-M | larangan penggunaan (lampiran A lisensi) wajib diteruskan ke pengguna; pipeline tanpa safety checker → kebijakan konten tanggung jawab project pemanggil |

Ringkasan lisensi bukan nasihat hukum; baca teks lengkap di halaman repo masing-masing.
Integritas: `artifact_sha256` = digest folder IR (sha256 tiap file, path terurut;
`runtime/core/artifacts.py`). Nilainya ada di `seed_models.yaml`, diverifikasi saat load pertama
dan oleh `manage.py verify-models`.

## Model remote (seed awal)

| Alias | Upstream | Tier | Kapabilitas |
|---|---|---|---|
| `anthropic/claude-sonnet` | `claude-sonnet-5-5` | heavy | tools, vision, JSON, konteks 200K |
| `anthropic/claude-haiku` | `claude-haiku-5-5` | light | tools, vision, JSON, konteks 200K |
| `openai/gpt-heavy` | `gpt-5` | heavy | tools, vision, JSON |
| `openai/gpt-light` | `gpt-5-mini` | light | tools, vision, JSON |
| `openai/text-embedding-3-small` | `text-embedding-3-small` | – | embedding 1536 dimensi |
| `gemini/flash` | `gemini-2.5-flash` | light | tools, vision, JSON |

Provider aktif hanya bila key-nya diisi di `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`). **Harga di seed = 0**. Isi `input_cost_per_mtok` / `output_cost_per_mtok`
(USD per 1 juta token) lewat Admin API agar laporan biaya benar. Nama model & harga berubah dari
waktu ke waktu: cek dokumentasi resmi provider, lalu perbarui lewat Admin API (tanpa ubah kode).

## Route default

| Route | Kandidat (urutan) | Kapan dipakai |
|---|---|---|
| `fast` | qwen2.5-7b → gemini/flash | task ringan; gratis bila lokal sanggup |
| `smart` | claude-sonnet → gpt-heavy → qwen2.5-7b | task berat / agent; lokal hanya cadangan terakhir |
| `local` | qwen2.5-7b → qwen2.5-coder-7b | data yang tidak boleh keluar mesin |
| `code` | qwen2.5-coder-7b → claude-sonnet → qwen2.5-7b | chat/agent kode |
| `autocomplete` | qwen2.5-coder-1.5b | FIM editor (latensi rendah, NPU) |
| `vision` | qwen2-vl-2b → gpt-light | gambar → teks |
| `image` | sd-1.5 | text→image, image→image |
| `embed-default` | openai/text-embedding-3-small | embeddings |

Fallback terjadi sebelum token pertama (error upstream, timeout, `model_busy`, provider nonaktif).
Kandidat yang tidak punya kapabilitas yang diminta (tools, vision, JSON, FIM) dilewati.

## Memilih model untuk project

- **Ringan vs berat**: tier `light` cukup untuk klasifikasi, ekstraksi, ringkasan pendek; `heavy`
  untuk penalaran multi-langkah, agent dengan banyak tool, kode kompleks.
- **Lokal vs remote**: lokal = gratis, privat, tetapi 7B di iGPU ±7–8 token/s (jawaban 300 token
  ±40 detik) dan konteks 8K. Remote = cepat & konteks panjang, berbayar. Gunakan route agar
  fallback otomatis.
- **Dampak swap GPU**: hanya satu model 7B muat di GPU. Bolak-balik `qwen2.5-7b` ↔
  `qwen2.5-coder-7b` dalam satu alur = swap setiap kali (±3–10 detik, lebih lama saat RAM sempit)
  dan model yang baru dimuat dikunci 60 detik (min residency) sehingga request ke model lain
  menunggu/`model_busy`. **Pilih satu model 7B per alur agent**, atau buat route dengan
  `"config": {"prefer_loaded": true}` agar kandidat yang sedang termuat didahulukan.
- **NPU dipakai bersama** Coder-1.5B dan SD: autocomplete bisa tertunda selama SD membuat gambar
  (±20–30 detik).
- Batasi `max_tokens`: gateway memotong ke `max_output_tokens` model (header `X-Gateway-Warning`).

## Menambah model lokal baru

Checklist budget (PRD §7.5): total `vram_mb` model pinned per device ≤ budget device (`.env`:
budget = `GPU_TOTAL_MB − GPU_RESERVE_MB`, `NPU_TOTAL_MB − NPU_RESERVE_MB`; saat ini 5300 / 6200); model GPU non-pinned terbesar ≤ budget GPU; dan karena UMA,
budget GPU + NPU harus menyisakan RAM untuk OS & aplikasi lain.

1. **Artefak OpenVINO IR**: unduh IR siap pakai (`OpenVINO/*-ov` di Hugging Face) atau konversi
   (`optimum-cli export openvino ...`; untuk NPU wajib INT4 simetris per-channel
   `--weight-format int4 --sym --group-size -1 --ratio 1.0`). Tambahkan entri ke
   `scripts/seed_models.yaml` lalu `download_models.py --write-yaml` / `convert_openvino.py
   --write-yaml` (mengisi `artifact_sha256`).
2. **Hangatkan cache & ukur**: `smoke_local.py` (compile pertama ±2× memori), lalu
   `measure_models.py --update-yaml` mengisi `vram_mb`.
3. **Daftarkan**: `manage.py seed --update-local`, atau `POST /admin/models` dengan `provider:
   "openvino"`, `device` gpu/npu (cpu ditolak), `runtime_backend` (`openvino_llm`,
   `openvino_vlm`, `openvino_diffusion`), `artifact_path`, `vram_mb`. Admin API menolak (422) bila
   artefak tidak ada atau total pinned melebihi budget.
4. Katalog gateway & runtime di-reload otomatis setelah perubahan lewat Admin API (setelah `seed`
   CLI: `POST /admin/cache/reload`). Uji: `scripts\test-hardware.bat
   tests\hardware\test_gateway_e2e.py` (smoke otomatis untuk semua model lokal di katalog).
5. Tambahkan ke route bila perlu (`PATCH /admin/routes/{alias}`) dan izinkan di project
   (`PUT /admin/projects/{id}/allowed-models`).

## Menambah API pihak ketiga (provider custom)

Selain OpenAI, Anthropic, dan Gemini, **API lain berapa pun jumlahnya** bisa ditambahkan tanpa
mengubah kode, selama formatnya kompatibel dengan salah satu **adapter**:

| Adapter | Untuk | Contoh layanan |
|---|---|---|
| `openai` | API OpenAI-compatible (`/chat/completions`, `/embeddings`) | DeepSeek, Groq, OpenRouter, Mistral, Together, Fireworks, xAI, Perplexity, Ollama / vLLM / LM Studio (lokal di LAN) |
| `anthropic` | API format Anthropic Messages | proxy / gateway Anthropic |
| `gemini` | API format Google Gemini | endpoint Gemini lain |

Langkah (contoh lengkap di `docs/admin-api.http`, bagian providers):
1. **Isi key di `.env`** dengan nama berpola `NAMA_API_KEY`, mis. `DEEPSEEK_API_KEY=...`.
   Restart gateway agar terbaca. Nilai key tidak pernah disimpan di DB, tidak tampil di log, dan
   tidak dikirim lewat Admin API.
2. **Daftarkan provider**: `POST /admin/providers`
   ```json
   {"code": "deepseek", "display_name": "DeepSeek", "adapter": "openai",
    "base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"}
   ```
   - Tanpa key (server di LAN): `"config": {"auth": "none"}` dan `api_key_env` dikosongkan.
   - Header tambahan non-secret (mis. OpenRouter): `"config": {"headers": {"X-Title": "gateway"}}`.
     Header kredensial (`Authorization`, `x-api-key`, ...) ditolak.
   - Uji koneksi: `POST /admin/providers/deepseek/test`.
3. **Daftarkan model**: `POST /admin/models` dengan `alias` (konvensi `<provider>/<nama>`, mis.
   `deepseek/chat`), `provider`, `upstream_name` (nama model persis di provider), `model_type`,
   `tier` (`light`/`heavy`, label untuk memilih & laporan), kapabilitas (`supports_tools`,
   `supports_vision`, `supports_json_mode`), `context_window`, `max_output_tokens`, dan harga
   `input_cost_per_mtok` / `output_cost_per_mtok` (USD per 1 juta token). Bila provider memakai
   `max_completion_tokens` alih-alih `max_tokens`, isi `"config": {"max_tokens_param":
   "max_completion_tokens"}` pada model.
4. **Pakai di route**: `PATCH /admin/routes/{alias}` (mis. tambahkan `deepseek/chat` ke `smart`)
   atau buat route baru `POST /admin/routes`.
5. **Izinkan di project**: `PUT /admin/projects/{id}/allowed-models` harus mencakup route
   **dan** model kandidatnya (mis. `["smart", "deepseek/*"]`).

Mengubah provider: `PATCH /admin/providers/{code}` (`display_name`, `is_enabled`, `base_url`,
`api_key_env`, `timeout_seconds`, `max_concurrency`, `config`). Menghapus:
`DELETE /admin/providers/{code}` (409 bila masih ada model; hapus/pindahkan modelnya dulu).
Semua perubahan tercatat di audit log dan katalog di-reload otomatis tanpa restart.

**Keamanan:** `api_key_env` provider remote wajib berpola `*_API_KEY`. Secret internal gateway
(`GATEWAY_KEY_PEPPER`, `RUNTIME_TOKEN`, `DATABASE_URL`) tidak mungkin dikirim ke API pihak ketiga,
walau pemegang key admin membuat provider dengan `base_url` sembarang.

## Profil operasional

Model mana yang aktif dan ke mana route menunjuk diatur **profil** (`scripts/profiles/*.yaml`),
bukan dengan mengedit katalog. Nama route tidak berubah antar profil, jadi klien tidak perlu
diubah.

```bat
scripts\conda-run.bat python scripts\manage.py apply-profile remote-only
```

| Profil | Model lokal | Route | Menjalankan |
|---|---|---|---|
| `remote-only` (**aktif sejak 30 Okt 2026**) | semua nonaktif, provider `openvino` mati | `fast`, `smart`, `code`, `vision` = kandidat remote; `local`, `autocomplete`, `image` dimatikan | `start-all.bat --no-runtime` |
| `ram16` | Coder-1.5B (NPU) + VL-2B (GPU) | kandidat lokal kecil + remote | `start-all.bat` |
| `full` | semua (butuh RAM ≥ 32 GB) | sama dengan `seed_models.yaml` | `start-all.bat` |

Model nonaktif tidak memakai RAM sama sekali, dan file model + cache compile OpenVINO tetap di
disk, jadi pindah profil tidak perlu unduh/compile ulang. Setiap perubahan profil tercatat di
audit log. Setelah menerapkan profil: restart (`stop-all.bat --keep-db` lalu `start-all.bat`,
dengan `--no-runtime` untuk `remote-only`).
