# Katalog model lokal & lisensi

Sumber kebenaran runtime adalah tabel `models` (diisi dari `scripts/seed_models.yaml`). Dokumen
ini mencatat asal dan lisensi tiap model (PRD §7.4) sebelum dipakai project lain. Baca teks
lisensi lengkap di halaman repo masing-masing; ringkasan di bawah bukan nasihat hukum.

Sejak 28 Okt 2026 model lokal hanya keluarga Qwen + Stable Diffusion v1.5, semuanya OpenVINO IR
di GPU/NPU (lihat `docs/hardware.md`). Embedding dilayani provider remote.

| Alias | Model asal | Artefak OpenVINO | Lisensi | Catatan penggunaan |
|---|---|---|---|---|
| local/qwen2.5-7b | Qwen/Qwen2.5-7B-Instruct | OpenVINO/Qwen2.5-7B-Instruct-int4-ov | Apache-2.0 | bebas, cantumkan atribusi |
| local/qwen2.5-coder-7b | Qwen/Qwen2.5-Coder-7B-Instruct | OpenVINO/Qwen2.5-Coder-7B-Instruct-int4-ov | Apache-2.0 | bebas, cantumkan atribusi |
| local/qwen2.5-coder-1.5b | Qwen/Qwen2.5-Coder-1.5B-Instruct | dikonversi lokal (INT4 sym per-channel, NPU) | Apache-2.0 | bebas, cantumkan atribusi |
| local/qwen2-vl-2b | Qwen/Qwen2-VL-2B-Instruct | dikonversi lokal (INT4) | Apache-2.0 | bebas, cantumkan atribusi |
| local/sd-1.5 | stable-diffusion-v1-5/stable-diffusion-v1-5 | dikonversi lokal (INT8/FP16) | CreativeML OpenRAIL-M | larangan penggunaan tertentu (lampiran A lisensi) wajib diteruskan ke pengguna; pipeline GenAI tanpa safety checker, kebijakan konten tanggung jawab project pemanggil |

Integritas file: `artifact_sha256` di tabel `models` = digest folder IR (sha256 tiap file, path
terurut; `runtime/core/artifacts.py`), diisi `download_models.py --write-yaml` →
`manage.py seed --update-local`, diverifikasi runtime saat load pertama (TASK-11).
