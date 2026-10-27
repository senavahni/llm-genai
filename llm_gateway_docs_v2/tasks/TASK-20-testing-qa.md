# TASK-20 — Testing, QA & Load Test

| Item | Nilai |
|---|---|
| Milestone | M6 Kualitas & Rilis |
| Prioritas | P0 |
| Estimasi | 3 hari (berjalan sepanjang proyek; task ini merapikan, menutup gap, dan menjalankan benchmark hardware) |
| Dependensi | TASK-01 s.d. TASK-19 |
| Referensi PRD | §7.5, §13 (NF1–NF11), §19 |

## Tujuan
Membuktikan acceptance criteria rilis (PRD §19) secara otomatis dan terukur.

## Spesifikasi

### Struktur test
```
tests/
├── conftest.py            # settings test, DB llm_gateway_test, app fixture, admin/client key
├── fakes/fake_provider.py # skenario: ok, slow, fail_before_first_token, fail_mid_stream, 400, 429
├── fakes/fake_backend.py  # backend runtime palsu: vram_mb, delay load, OOM, model_busy, device=cpu
├── unit/                  # utils, translators, router, ratelimit, quota, cost
├── integration/           # API + DB nyata (fake provider)
├── contract/              # SDK openai resmi → app (uvicorn di port acak)
├── live/                  # provider asli, marker @pytest.mark.live (dijalankan manual)
├── hardware/              # model lokal asli: @pytest.mark.gpu / @pytest.mark.npu (manual, di mesin target)
├── bench/                 # benchmark NF11 & uji swap (scripts\bench.bat)
└── load/locustfile.py     # atau script asyncio + httpx
```

### Fixture DB
- Database `llm_gateway_test` di PostgreSQL portable yang sama.
- Per sesi: `alembic upgrade head`; per test: transaksi + rollback atau `TRUNCATE ... CASCADE`.

### Daftar test wajib
| Area | Kasus |
|---|---|
| Auth | tanpa key, key salah, revoked, expired, scope, admin vs client |
| Routing | priority, round robin, glob allow, kapabilitas, circuit breaker |
| Fallback | sebelum token pertama (fallback), setelah token pertama (tidak), 400 (tidak) |
| Streaming | `[DONE]`, include_usage, client disconnect → `cancelled` + usage parsial |
| Accounting | konsistensi `requests` ↔ `usage_daily`, biaya Decimal, orphan sweeper |
| Rate/Quota | 429 + Retry-After, reset periode |
| Admin | audit atomic, 409 delete model terpakai, cursor pagination |
| Security | **secret scan**: setelah suite, grep `logs/*.log` dan dump tabel untuk pola `sk-`, `sk-ant-`, `AIza`, `lgw_<prefix>_<secret>` → harus 0 temuan |
| Translator | Anthropic & Gemini: multi system, gambar, tool multi-turn, tool_choice |
| Device Manager | budget, pinned tidak di-evict, LRU, min residency, antrean → `model_busy`, OOM → `ctx_fallback`, tolak `cpu` |
| Runtime API | token wajib, bind localhost, cancel stream, `x_runtime` selalu ada |
| Local adapter | mapping error runtime → retryable, `runtime_meta` → `requests.device/load_ms/queue_ms` |
| Images | validasi size/steps/n, b64 vs url, akses file lintas project → 404, retensi file |
| FIM | prompt FIM tersusun benar, stop token, tidak bocor token khusus |
| Tool parser lokal | `hermes` & `llama3_json`: non-stream, stream, multi tool call, teks campuran |

### Test hardware (mesin target, manual sebelum rilis)
Dijalankan dengan `scripts\test-hardware.bat` saat runtime hidup:
1. **Smoke 11 model katalog**: setiap model lokal dipanggil via gateway (chat/FIM/vision/embedding/image sesuai tipe). Assert `X-Gateway-Device` ∈ {gpu, npu}.
2. **Anti-CPU**: query `SELECT count(*) FROM requests WHERE device='cpu' AND created_at > <mulai test>` = 0. Log llama.cpp menunjukkan semua layer offloaded.
3. **Uji swap 100×**: urutan acak request ke `qwen2.5-7b`, `qwen2.5-coder-7b`, `llama-3.1-8b`, `deepseek-r1-qwen-7b`, `llama-3.2-3b`, `qwen2-vl-2b`, dengan 4 klien paralel dan autocomplete berjalan terus di latar.
   - Assert 0 `oom` di `runtime_events`.
   - Memori GPU puncak ≤ 7200 MB + toleransi 3%.
   - Autocomplete (pinned) tidak pernah gagal.
   - Request yang ditolak hanya `model_busy` dan ter-fallback.
4. **Kontensi GPU+NPU**: SD 512² berjalan bersamaan dengan chat 7B di GPU → keduanya sukses dan latensi tercatat.
5. **Restart runtime** di tengah beban → gateway fallback ke remote / 503, tidak ada `requests` tertinggal `pending` setelah sweeper.

### Benchmark lokal (NF11)
`tests/bench/bench_local.py` mengukur dan menulis tabel ke `docs/perf-report.md`:

| Model | Metrik |
|---|---|
| Coder-1.5B FIM | TTFT p50/p95, token/s |
| Qwen2.5-7B, Coder-7B, Llama-3.1-8B, DeepSeek-R1-7B | TTFT, token/s (prompt 1k, output 256), waktu load/swap |
| Llama-3.2-3B, Phi-3.5, Qwen2-VL-2B | TTFT, token/s; VL juga waktu encode gambar |
| SD v1.5 (FP16 vs INT8) | detik per gambar 512², 25 step; waktu compile tanpa/dengan cache |
| bge-m3 NPU, nomic GPU | kalimat/detik (batch 8, 512 token) |

Hasil dibandingkan dengan target NF11. Deviasi ditulis beserta penyebab dan rekomendasi (mis. turunkan `n_ctx`, KV q4_0, ganti INT8, `replicas`).

### Load test
- Skenario A: 50 stream bersamaan × 2 menit ke fake provider (latency 20 ms/chunk) → ukur overhead gateway.
- Skenario B: 200 RPS non-stream ke fake provider → p95 overhead < 30 ms (NF1).
- Skenario C (hardware): 10 klien autocomplete (FIM) + 2 klien chat `code` selama 5 menit → p95 TTFT autocomplete dan jumlah `model_busy`.
- Laporkan hasil di `docs/perf-report.md`.

### Kualitas kode
- `ruff check .` & `ruff format --check .`
- `mypy app` (mode moderat; `disallow_untyped_defs` untuk `app/services` & `app/utils`)
- Coverage `pytest --cov=app --cov=runtime --cov-report=term-missing` ≥ 70% untuk `app/services`, `app/utils`, `runtime/device`, `runtime/services`.
- `mypy runtime` dengan aturan yang sama.
- `scripts/check.bat` menjalankan semuanya berurutan.

## Deliverables
- [ ] Seluruh suite test di atas
- [ ] `scripts/check.bat`, `scripts/test.bat`, `scripts/test-hardware.bat`, `scripts/bench.bat`
- [ ] `docs/perf-report.md`

## Acceptance Criteria
1. `scripts/check.bat` hijau.
2. Secret scan 0 temuan.
3. Target NF1 & NF2 tercapai atau deviasi terdokumentasi beserta penyebabnya.
4. Smoke test live per provider (manual) terdokumentasi di `docs/perf-report.md` bagian "Live smoke".
5. Ke-11 model lokal lulus smoke test hardware; 0 request lokal dengan `device='cpu'` (NF9).
6. Uji swap 100× lulus tanpa OOM, dengan memori GPU ≤ budget (NF10).
7. Tabel benchmark NF11 terisi, dan setiap target yang tidak tercapai punya penjelasan dan rencana tindak lanjut.
