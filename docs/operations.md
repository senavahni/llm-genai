# Operasional

Panduan menjalankan, merawat, dan memulihkan gateway. Semua perintah dijalankan dari root project
tanpa hak admin; `scripts\*.bat` memuat `.env` lewat `scripts\env.bat`.

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
