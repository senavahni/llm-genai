# To-Do (diperbarui 28 Oktober 2026)

## Status TASK-06 s/d TASK-12

| Task | Status | Catatan |
|---|---|---|
| 06 Provider base, registry, streaming | ✅ | |
| 07 Provider OpenAI | ✅ kode | smoke test dengan API key asli belum (`.env` tanpa key) |
| 08 Provider Anthropic & Gemini | ✅ kode | sama |
| 09 Hardware & model | ✅ | OpenVINO saja; 4 Qwen + SD di GPU/NPU, semua diukur & lolos smoke test (`docs/hardware.md`) |
| 10 Local runtime & Device Manager | ✅ | daftar backend & pola OOM sudah disesuaikan OpenVINO; endpoint embeddings dihapus, `/v1/images/edits` ditambah |
| 11 Backend OpenVINO GenAI (Qwen) | 📝 spesifikasi direvisi | `tool_parsers.py` (Hermes) + test sudah ada; backend belum |
| 12 Backend SD (t2i + i2i) | 📝 spesifikasi direvisi | jalur GenAI terbukti di `scripts/test_sd.py`; backend belum |

## Berikutnya

1. **TASK-12** (paling siap): `runtime/backends/ov_diffusion_backend.py` dari `scripts/test_sd.py`
   (satu set model untuk t2i + i2i, cancel per step, event compile + cache_hit).
2. **TASK-11**: `ov_llm_backend.py`, `ov_vlm_backend.py`, `image_input.py`, parser stream tool call,
   validator device (tolak CPU/AUTO), test dengan pipeline palsu + test hardware.
3. Ukur ulang FIM Coder-1.5B dengan prompt pendek (128–256 token) untuk target TTFT < 300 ms.
4. Sesuaikan task yang masih menyebut llama.cpp/embedding lokal saat sampai di sana:
   TASK-18 (metrics), TASK-20 (QA), TASK-21 (deployment), TASK-23 (docs klien). PRD belum diubah;
   keputusan tercatat di TASK-09/11/12 dan `docs/hardware.md`.

## Perlu keputusan pemilik proyek

- **Coder-1.5B tetap di NPU?** NPU dipakai bersama SD: autocomplete bisa menunggu ±20 s saat SD
  generate. Alternatif: Coder-1.5B di GPU (27 token/s, berbagi GPU dengan model 7B).
- API key OpenAI/Anthropic/Gemini (opsional) untuk smoke test TASK-07/08.
