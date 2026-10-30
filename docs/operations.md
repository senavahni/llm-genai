# Operasional

Panduan menjalankan, merawat, dan memulihkan gateway. Semua perintah dijalankan dari root project
tanpa hak admin; `scripts\*.bat` memuat `.env` lewat `scripts\env.bat`.

## Start / stop

```bat
scripts\start-all.bat            :: Mode A (detail & opsi: docs\deployment.md)
scripts\start-all-traefik.bat    :: Mode B
scripts\stop-all.bat [--keep-db]
```
Status cepat: `curl http://127.0.0.1:8000/health/ready` (dari localhost menampilkan detail
provider, runtime, device, RAM sistem). Status runtime rinci: `GET /admin/runtime/status`.

## Log

Semua log JSON satu baris per event di `logs\` (daftar file: `docs\deployment.md` → Log). Setiap
baris request membawa `request_id` (= header `X-Request-ID`), `key_prefix`, `project_slug`.

```bat
:: semua baris satu request (dari X-Request-ID yang dikirim klien)
findstr /c:"01a1815e-f956-72ed-9010-babe68714881" logs\app.log logs\runtime.log logs\access.log
:: error 1 jam terakhir: buka logs\error.log (hanya level ERROR)
:: jq dari Git portable bila tersedia (D:\...\PortableDev\Git\usr\bin), contoh:
type logs\app.log | jq -c "select(.level==\"error\") | {ts, event, code, request_id}"
```
Key API, `Authorization`, dan token runtime selalu diredaksi di log (`lgw_xxxxxxxx_***`).

## Key & akses

- **Rotasi key provider** (OpenAI/Anthropic/Gemini): ubah nilai di `.env` → restart gateway
  (`stop-all.bat --keep-db` lalu `start-all.bat`, atau tutup jendela `llm-gateway` lalu
  `start-gateway.bat`). Nilai key tidak pernah disimpan di DB.
- **Revoke key client**: `POST /admin/keys/{id}/revoke` (`docs/admin-api.http`); berlaku
  seketika (cache auth di-invalidasi). **Rotasi**: `POST /admin/keys/{id}/rotate` → key baru
  tampil sekali, key lama dicabut.
- **Admin key hilang**: `scripts\conda-run.bat python scripts\manage.py create-admin-key --name ops2`
  (butuh akses ke mesin & `.env`), lalu cabut yang lama lewat Admin API.

## Troubleshooting

| Gejala | Penyebab / tindakan |
|---|---|
| `DLL load failed` / `ImportError` OpenVINO, numpy | jalankan lewat `scripts\*.bat` / `conda-run.bat` (PATH `Library\bin` conda diatur `env.bat`), jangan `python` langsung |
| Port terpakai (`[Errno 10048]`) | `netstat -ano \| findstr :8000` → PID → tutup proses itu (`taskkill /PID <pid>` untuk proses milik sendiri) |
| `start-all.bat` berhenti di langkah runtime | lihat `logs\runtime.log` (`warmup_failed`), `logs\runtime-error.log`; `/health/ready` runtime menampilkan `warmup_errors` |
| Model lokal lambat | cek header `X-Gateway-Device` (harus gpu/npu); `GET /admin/runtime/swap-stats` (swap berlebihan → satu model 7B per alur agent, route `prefer_loaded`); `requests.load_ms/queue_ms` di `docs\database.md` |
| Load model GPU gagal: `[GPU] ProgramBuilder build failed`, `CL_INVALID_EVENT`, `CL_OUT_OF_RESOURCES` | **RAM sistem habis** (iGPU memakai RAM). Cek `/health/ready` → `runtime.system_ram.low`, log `low_system_ram`. Tutup aplikasi berat; bila model GPU masih gagal setelah RAM cukup, restart runtime (`runtime_ctl.py shutdown` lalu `start-all.bat`). Detail: `docs\perf-report.md` → RAM sistem |
| NPU / GPU tidak muncul di `available_devices` | driver NPU/GPU Intel belum terpasang/terlalu lama (`scripts\probe_devices.py` → `logs\device_probe.json`) |
| Compile lama setiap start (SD > 1 menit) | cache `local_models\ov_cache` hilang / tidak bisa ditulis, atau versi OpenVINO/driver berubah → jalankan `smoke_local.py` + `test_sd.py` sekali untuk menghangatkan cache |
| `oom` di `runtime_events` | `vram_mb` model terlalu kecil dibanding pemakaian nyata atau budget terlalu besar untuk RAM: ukur ulang `measure_models.py`, periksa total pinned ≤ budget NPU |
| Runtime restart berulang | `logs\runtime-supervisor.log` + `logs\runtime-error.log`; setelah 5 restart beruntun supervisor berhenti → perbaiki penyebab lalu `start-all.bat` |
| Request `pending` menumpuk | gateway mati di tengah request; orphan sweeper menandainya `error` (`orphaned`) setelah 10 menit |
| Usage tidak tercatat saat DB mati | baris di `logs\usage_fallback.jsonl` → `manage.py replay-usage` setelah DB hidup |
| Stream tertahan di Traefik (chunk datang sekaligus) | middleware `buffering` di `deploy\traefik\dynamic.yml`: pastikan hanya `maxRequestBodyBytes`; bila tetap tertahan hapus `body-limit` dari router publik |
| `403` dari Traefik di `/admin` | IP klien tidak ada di `admin-allowlist.sourceRange` (`dynamic.yml`, reload otomatis) |

## Retensi data (TASK-19)

Berjalan otomatis setiap hari **00:30 UTC** (task di dalam gateway) dan bisa dijalankan manual.

| Data | Aturan | Setting `.env` |
|---|---|---|
| `request_payloads` | dihapus setelah `expires_at` (retensi payload per project) | `projects.payload_retention_days` |
| `generated_images` + file PNG | file & baris dihapus setelah `expires_at`; URL lama → 404; folder tanggal kosong ikut dihapus | `projects.image_retention_days` |
| `requests` (+ attempts, payload) | dihapus bila lebih tua dari N hari | `REQUEST_RETENTION_DAYS` (180) |
| `audit_logs` | | `AUDIT_RETENTION_DAYS` (730) |
| `runtime_events` | | `RUNTIME_EVENT_RETENTION_DAYS` (90) |
| File gambar yatim (tanpa baris DB, > 1 hari) | disapu mingguan (Minggu) & saat retensi manual | – |
| `usage_daily` | **tidak pernah dihapus** (laporan biaya jangka panjang) | – |

Penghapusan berjalan per batch (5.000 baris, gambar 500) dengan commit per batch, jadi request
baru tetap tercatat selama purge. Setelah ≥ 10.000 request terhapus dijalankan `ANALYZE requests`
(VACUUM ditangani autovacuum). Setiap run tercatat di log (`retention.done`) dan audit
(`maintenance.retention`).

```bat
scripts\conda-run.bat python scripts\manage.py retention          :: manual
```
atau `POST /admin/maintenance/retention` (key admin).

**Cache compile OpenVINO** (`local_models\ov_cache`, ±12 GB) tidak dibersihkan otomatis karena
compile ulang mahal (SD ±2 menit, Qwen 7B ±30 detik + lonjakan memori 2×). Bersihkan hanya setelah
ganti versi OpenVINO atau driver GPU/NPU:
```bat
scripts\conda-run.bat python scripts\manage.py clear-ov-cache --yes
scripts\conda-run.bat python scripts\smoke_local.py      :: hangatkan ulang cache (±5 menit)
scripts\conda-run.bat python scripts\test_sd.py
```

## Backup & restore

```bat
scripts\backup-db.bat              :: backups\llm_gateway_YYYY-MM-DD.dump (7 terakhir disimpan)
scripts\backup-db.bat --verify     :: + restore uji ke llm_gateway_test & bandingkan jumlah baris
```
- Kredensial diambil dari `DATABASE_URL` di `.env` (dikirim lewat `PGPASSWORD`, tidak muncul di
  daftar proses). Lokasi `pg_dump.exe`: env `PG_BIN` atau default
  `D:\Data.Fahrul\Documents\PortableDev\postgres\pgsql\bin`.
- Jadwalkan harian lewat Task Scheduler (akun sendiri, tanpa admin): Action
  `scripts\backup-db.bat`, "Start in" = folder project.
- `--verify` **menimpa** DB `llm_gateway_test` (DB untuk test otomatis; test memigrasinya ulang).

Restore ke DB yang sudah ada (hentikan gateway dulu):
```bat
set PGPASSWORD=...
"%PG_BIN%\pg_restore.exe" -h 127.0.0.1 -U llm_gateway -d llm_gateway -c --if-exists backups\llm_gateway_2026-10-28.dump
scripts\migrate.bat                :: pastikan skema di versi terbaru
```

**Tidak di-backup otomatis:**
- `local_models\` (±12 GB model + ±12 GB cache): bisa dibuat ulang dari `scripts/seed_models.yaml`
  (`download_models.py` + `convert_openvino.py`), lalu diverifikasi sha256-nya.
- `storage\images\`: sementara, punya retensi; anggap hilang bila mesin rusak.

## Verifikasi model lokal

```bat
scripts\conda-run.bat python scripts\manage.py verify-models --quick   :: hanya keberadaan file
scripts\conda-run.bat python scripts\manage.py verify-models           :: + sha256 (±1–2 menit)
```
Keluaran `HILANG` / `BERUBAH` → unduh/konversi ulang model tersebut (lihat `docs/hardware.md`).

## Ekspor usage

```bat
scripts\conda-run.bat python scripts\manage.py export-usage --from 2026-10-01 --to 2026-10-31 --out usage-okt.csv
scripts\conda-run.bat python scripts\manage.py export-usage --from 2026-10-01 --to 2026-10-31 --project agent-a --out a.csv
```
Kolom: `day, project, model_alias, provider_code, request_count, success_count, error_count,
prompt_tokens, completion_tokens, image_count, cost_usd`.

## Konsistensi pencatatan

- `GET /admin/usage/verify?day=YYYY-MM-DD` → selisih `requests` vs `usage_daily` per project
  harus 0.
- Bila DB sempat mati, pencatatan yang gagal ada di `logs\usage_fallback.jsonl`; tulis ulang dengan
  `scripts\conda-run.bat python scripts\manage.py replay-usage`.
