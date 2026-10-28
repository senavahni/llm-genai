# TASK-19 — Retensi Data, Maintenance & Backup

| Item | Nilai |
|---|---|
| Milestone | M5 Governance |
| Prioritas | P1 |
| Estimasi | 0.5 hari |
| Dependensi | TASK-15, TASK-17 |
| Referensi PRD | §9.3 |

## Tujuan
Menjaga ukuran database tetap sehat di PostgreSQL portable dan memastikan data bisa dipulihkan.

## Spesifikasi

### Retensi (`app/services/maintenance_service.py`)
- `purge_payloads()`: `DELETE FROM request_payloads WHERE expires_at < now()` (batch 5.000 baris per loop).
- `purge_requests(days=REQUEST_RETENTION_DAYS default 180)`: hapus `requests` lama dalam batch (cascade ke attempts & payloads). `usage_daily` **tidak** dihapus.
- `purge_audit(days=AUDIT_RETENTION_DAYS default 730)`.
- `purge_images()`: ambil `generated_images` dengan `expires_at < now()` per batch 500 → hapus file di `STORAGE_DIR` (thread) → hapus baris. File yang tidak ditemukan tetap menghapus baris dan dicatat WARNING. Folder tanggal kosong ikut dihapus.
- `purge_orphan_image_files()` (mingguan): file di `storage/images/` tanpa baris DB dan berumur > 1 hari → hapus.
- `purge_runtime_events(days=RUNTIME_EVENT_RETENTION_DAYS default 90)`.
- `purge_ov_cache()` **tidak** otomatis. Cache kompilasi OpenVINO hanya dibersihkan manual (`manage.py clear-ov-cache`) setelah ganti versi OpenVINO/driver, karena compile ulang NPU memakan waktu.
- Dijalankan: otomatis setiap hari pukul 00:30 UTC oleh task di lifespan **dan** manual via `POST /admin/maintenance/retention` atau `manage.py retention`.
- Setiap run dicatat di log (`event=retention.done`, jumlah baris per tabel) dan audit (`maintenance.retention`).
- Setelah purge besar → `ANALYZE requests;` (VACUUM otomatis oleh autovacuum).

### Backup
- `scripts/backup-db.bat`:
```bat
@echo off
call "%~dp0env.bat"
set "PG_BIN=D:\Data.Fahrul\Documents\PortableDev\pgsql\bin"
for /f %%i in ('"%PY%" -c "import datetime;print(datetime.date.today())"') do set TODAY=%%i
"%PG_BIN%\pg_dump.exe" -h 127.0.0.1 -U llm_gateway -F c -f "%PROJECT_ROOT%\backups\llm_gateway_%TODAY%.dump" llm_gateway
```
  (sesuaikan `PG_BIN` dengan lokasi bin PostgreSQL portable; password via file `%APPDATA%\postgresql\pgpass.conf` atau `PGPASSWORD` di env lokal).
- Simpan 7 backup terakhir (hapus yang lebih tua di script).
- **Yang tidak di-backup otomatis:** `local_models/` (besar, bisa diunduh/konversi ulang dari `seed_models.yaml` + sha256) dan `storage/images/` (sementara, ada retensi). Dokumentasikan di `docs/operations.md`.
- `manage.py verify-models`: cek keberadaan dan sha256 semua `artifact_path` model lokal enabled. Laporkan yang hilang/berubah.
- Dokumentasi restore: `pg_restore -h 127.0.0.1 -U llm_gateway -d llm_gateway -c <file>`.

### Ekspor
- `manage.py export-usage --from 2026-10-01 --to 2026-10-31 --out usage.csv` (dari `usage_daily`).

## Deliverables
- [x] `maintenance_service.py` + jadwal di lifespan
- [x] `scripts/backup-db.bat`, perintah CLI `retention`, `export-usage`, `verify-models`, `clear-ov-cache`
- [x] `docs/operations.md` (backup, restore, retensi)

## Acceptance Criteria
1. Payload kedaluwarsa terhapus pada run berikutnya; `usage_daily` tetap utuh.
1b. Gambar kedaluwarsa: file **dan** baris `generated_images` terhapus; URL lamanya → 404.
2. Purge 1 juta baris dummy tidak mengunci tabel `requests` lebih dari beberapa detik per batch (request baru tetap tercatat).
3. Backup → restore ke DB baru menghasilkan jumlah baris identik.
