# Daftar Task — LLM Gateway (PRD v2.0)

Urutan pengerjaan mengikuti dependensi. Total estimasi ±36 hari kerja (1 developer), termasuk waktu unduh/konversi model dan benchmark di hardware target.

| ID | Task | Milestone | Prio | Est. | Dependensi |
|---|---|---|---|---|---|
| [TASK-01](TASK-01-setup-environment.md) | Setup environment & skeleton | M1 Fondasi | P0 | 0.5 h | — |
| [TASK-02](TASK-02-config-core.md) | Config, error hierarchy, app factory | M1 | P0 | 0.5 h | 01 |
| [TASK-03](TASK-03-logger-request-context.md) | Logger, request context, helper | M1 | P0 | 1 h | 02 |
| [TASK-04](TASK-04-database-models-migrations.md) | PostgreSQL, ORM, Alembic, seed | M1 | P0 | 1.5 h | 02 |
| [TASK-05](TASK-05-auth-api-key.md) | Autentikasi API key | M1 | P0 | 1 h | 03, 04 |
| [TASK-06](TASK-06-provider-base-registry-streaming.md) | Provider base, registry, streaming | M2 Provider Remote | P0 | 1.5 h | 02, 04 |
| [TASK-07](TASK-07-provider-openai.md) | Adapter OpenAI | M2 | P0 | 0.5 h | 06 |
| [TASK-08](TASK-08-provider-anthropic-gemini.md) | Adapter Anthropic & Gemini | M2 | P0 | 2 h | 06 |
| [TASK-09](TASK-09-hardware-model-acquisition.md) | **Hardware probe, akselerator, unduh/konversi & ukur model** | M3 Local Runtime | P0 | 2 h | 01, 04 |
| [TASK-10](TASK-10-local-runtime-device-manager.md) | **Local Runtime + Device/VRAM Manager + adapter gateway** | M3 | P0 | 3 h | 03, 04, 06, 09 |
| [TASK-11](TASK-11-runtime-backend-llamacpp.md) | **Backend llama-cpp-python: teks, kode/FIM, vision, embedding** | M3 | P0 | 3 h | 09, 10 |
| [TASK-12](TASK-12-runtime-backend-openvino.md) | **Backend OpenVINO: SD v1.5 & bge-m3 di NPU** | M3 | P0 | 2 h | 09, 10 |
| [TASK-13](TASK-13-routing-fallback.md) | Router & fallback (termasuk lokal) | M4 Core API | P0 | 2 h | 06–08, 10 |
| [TASK-14](TASK-14-public-api-v1.md) | Public API v1 (+ images, FIM, vision) | M4 | P0 | 3 h | 05, 11, 12, 13, 15 |
| [TASK-15](TASK-15-usage-accounting.md) | Usage, cost & akuntabilitas device | M4 | P0 | 1.5 h | 04, 13 |
| [TASK-16](TASK-16-ratelimit-quota.md) | Rate limit & kuota (+ gambar) | M5 Governance | P0 | 1 h | 05, 15 |
| [TASK-17](TASK-17-admin-api-audit.md) | Admin API, runtime admin & audit | M5 | P0 | 2.5 h | 05, 10, 13, 15 |
| [TASK-18](TASK-18-health-metrics.md) | Health & metrics (+ GPU/NPU) | M5 | P1 | 1 h | 06, 10, 15 |
| [TASK-19](TASK-19-retention-maintenance.md) | Retensi (+ file gambar), maintenance, backup | M5 | P1 | 0.5 h | 15, 17 |
| [TASK-20](TASK-20-testing-qa.md) | Testing, uji hardware, benchmark, load test | M6 Kualitas & Rilis | P0 | 3 h | semua |
| [TASK-21](TASK-21-deployment-without-traefik.md) | Deployment tanpa Traefik (+ runtime) | M6 | P0 | 1 h | 04, 10, 18 |
| [TASK-22](TASK-22-deployment-with-traefik.md) | Deployment dengan Traefik | M6 | P1 | 1 h | 21 |
| [TASK-23](TASK-23-docs-client-integration.md) | Dokumentasi & integrasi klien | M6 | P1 | 1 h | 09, 14, 17, 20, 21, 22 |

## Perubahan dari versi task sebelumnya
| Lama | Baru |
|---|---|
| TASK-09 Adapter llama.cpp (llama-server) | Diganti **TASK-09** (hardware & model), **TASK-10** (runtime), **TASK-11** (llama-cpp-python) |
| TASK-10 Adapter Hugging Face (torch, CPU) | Diganti **TASK-12** (OpenVINO di NPU). Model HF dijalankan via `optimum[openvino]`, bukan torch. |
| TASK-11 … TASK-21 | Dinomori ulang menjadi TASK-13 … TASK-23, isinya diperluas untuk model lokal, gambar, FIM, dan device |

## Alur dependensi

```
01 → 02 ─┬→ 03 ─┐
         ├→ 04 ─┴→ 05
         └→ 06 → 07
               └→ 08
01,04 → 09 ─┐
03,04,06 ───┴→ 10 ─┬→ 11
                   └→ 12
06..08,10 → 13 → 15 ─┐
05,11,12,13,15 → 14  │
05,15 → 16           │
05,10,13,15 → 17 → 19
06,10,15 → 18 → 21 → 22 → 23
semua → 20
```

Jalur kritis: 01 → 02 → 04 → 09 → 10 → 11 → 13 → 15 → 14 → 20. TASK-09 bisa dimulai paralel dengan M2 karena unduhan model memakan waktu lama.

## Definition of Done (berlaku untuk setiap task)
1. Kode mengikuti layering PRD §7.2 (route → controller → service → model/provider/backend), baik di `app/` maupun `runtime/`.
2. Type hints lengkap, `ruff check` bersih.
3. Test unit/integrasi untuk acceptance criteria task tersebut ada dan lulus. Test hardware diberi marker `gpu`/`npu`.
4. Tidak ada secret di log/DB (secret scan TASK-20).
5. Model lokal tidak berjalan di CPU (kecuali test dengan `ALLOW_CPU_FALLBACK=true` yang eksplisit).
6. Dokumentasi/`.env.example`/`seed_models.yaml` diperbarui jika ada konfigurasi baru.
7. Commit dengan pesan `TASK-XX: <ringkasan>` via Git portable.
