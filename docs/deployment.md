# Deployment

Gateway berjalan di satu mesin Windows (Intel Core Ultra: iGPU + NPU) **tanpa hak admin dan
tanpa Docker**. Ada dua mode:

| Mode | Kapan | Entry point |
|---|---|---|
| **A — tanpa Traefik** | dipakai dari mesin yang sama (agen lokal, IDE), atau LAN sederhana | `scripts\start-all.bat` |
| **B — dengan Traefik** | diakses dari mesin lain dan `/admin` perlu dibatasi IP, TLS opsional | `scripts\start-all-traefik.bat` |

## Topologi

```
Client ──► gateway 127.0.0.1:8000   (Mode A --lan: 0.0.0.0:8000; Mode B: di belakang Traefik)
           ├── PostgreSQL portable 127.0.0.1:5432
           └── Local Runtime 127.0.0.1:8100   (SELALU localhost, header X-Runtime-Token)
                ├── GPU (iGPU Intel): OpenVINO GenAI — qwen2.5-7b, qwen2.5-coder-7b, qwen2-vl-2b
                │                      (di-swap sesuai budget GPU_TOTAL_MB − GPU_RESERVE_MB)
                └── NPU (Intel AI Boost): OpenVINO — qwen2.5-coder-1.5b (FIM, pinned),
                                       sd-1.5 (text→image & image→image, pinned)
```
Semua inferensi lokal berjalan di GPU/NPU; runtime menolak device `cpu` (NF9).

## Persiapan sekali jalan

1. **Conda env** `llm-genai` (Python 3.11) — lokasi diatur di `scripts\env.bat` (`CONDA_ENV`):
   ```bat
   scripts\conda-run.bat pip install -r requirements.txt -r requirements-local.txt
   ```
2. **`.env`** dari `.env.example`. Wajib diisi: `DATABASE_URL`, `GATEWAY_KEY_PEPPER` (≥ 32
   karakter acak), `RUNTIME_TOKEN` (≥ 32 karakter acak); key provider remote bila dipakai.
   Jangan memberi komentar di akhir baris (`env.bat` membaca `KEY=VALUE` apa adanya).
3. **PostgreSQL portable** (`D:\Data.Fahrul\Documents\PortableDev\postgres\pgsql`, data di
   `PortableDev\pgdata`, port 5432): buat user & database `llm_gateway` (dan `llm_gateway_test`
   untuk test; perintah `psql` ada di README), lalu:
   ```bat
   scripts\migrate.bat
   scripts\conda-run.bat python scripts\manage.py seed
   scripts\conda-run.bat python scripts\manage.py create-admin-key --name ops
   ```
   Full key hanya tampil sekali — simpan di password manager.
4. **Model lokal** (±12 GB, lihat `docs/hardware.md`): `scripts\download_models.py` +
   `scripts\convert_openvino.py`, lalu `manage.py verify-models` dan `manage.py seed` ulang untuk
   mengisi sha256.
5. **Warmup cache compile** (sekali, ±5 menit): `scripts\conda-run.bat python
   scripts\smoke_local.py` — tanpa ini start pertama runtime lebih lama (compile NPU).

## Mode A — tanpa Traefik

```bat
scripts\start-all.bat              :: localhost saja (default)
scripts\start-all.bat --lan        :: gateway bind 0.0.0.0:8000
scripts\start-all.bat --no-runtime :: hanya provider remote; /health/ready = degraded
scripts\stop-all.bat               :: gateway -> runtime -> PostgreSQL
scripts\stop-all.bat --keep-db     :: PostgreSQL dibiarkan hidup
```

`start-all.bat` menjalankan berurutan (komponen yang sudah hidup dilewati):

| Langkah | Detail |
|---|---|
| 1. PostgreSQL | `scripts\start-postgres.bat` (script PortableDev, `pg_ctl start`) |
| 2. Migrasi | `alembic upgrade head` |
| 3. Verifikasi model | `manage.py verify-models --quick` (peringatan saja, tidak menghentikan start) |
| 4. Local Runtime | jendela `llm-runtime` (minimized) menjalankan `start-runtime.bat` = supervisor; ditunggu sampai `/health/ready` runtime 200 (model pinned termuat), maks 15 menit |
| 5. Gateway | jendela `llm-gateway` (minimized) menjalankan `start-gateway.bat` → `run_server.py` (uvicorn, **1 worker**); ditunggu sampai `/health/ready` 200 |

Durasi terukur di mesin target (Core Ultra 5 225, cache OpenVINO sudah ada): lihat tabel
"Waktu start" di bawah.

`stop-all.bat`:
1. Gateway: `taskkill /FI "WINDOWTITLE eq llm-gateway*" /T /F`. Request yang sedang berjalan
   tercatat `pending` lalu ditandai `error` oleh orphan sweeper saat gateway start berikutnya.
2. Runtime: `scripts\runtime_ctl.py shutdown` → `POST /runtime/shutdown` (unload semua model,
   event `runtime_stop`, exit 0 sehingga supervisor tidak me-restart). Bila port 8100 belum
   tertutup dalam 15 detik → `taskkill` jendela `llm-runtime` (cadangan).
3. PostgreSQL: `stop-postgres.bat` PortableDev (`pg_ctl stop -m fast`) — **jangan** `taskkill`
   proses postgres.

### Supervisor runtime
`start-runtime.bat` me-restart runtime bila keluar dengan kode ≠ 0 (crash native / driver),
maksimal 5 kali beruntun (penghitung di-reset bila runtime sempat hidup ≥ 10 menit). Riwayat ada di
`logs\runtime-supervisor.log`. Selama runtime mati, gateway tetap hidup: model lokal gagal cepat
(circuit breaker) dan route dengan kandidat remote fallback ke remote.

### Akses LAN
`--lan` membuat gateway bind `0.0.0.0`. Windows Firewall mungkin meminta izin; bila tidak bisa
diizinkan tanpa admin, pakai localhost saja. Untuk akses dari mesin lain **disarankan Mode B**
agar `/admin` dibatasi IP. Runtime tidak pernah bind selain `127.0.0.1`.

### Autostart (tanpa admin)
Task Scheduler → *Create Task* (akun sendiri) → Trigger *At log on* → Action
`D:\...\llm-genai\scripts\start-all.bat`, *Start in* = folder project → *Run only when user is
logged on*.

### Log
| File | Isi |
|---|---|
| `logs\app.log`, `logs\error.log` | gateway (JSON, rotasi harian, 14/30 hari) |
| `logs\access.log` | access log gateway (tanpa body/key) |
| `logs\runtime.log`, `logs\runtime-error.log` | Local Runtime + log native OpenVINO (DEBUG) |
| `logs\runtime-supervisor.log` | restart runtime oleh supervisor |
| `logs\usage_fallback.jsonl` | pencatatan usage saat DB mati (`manage.py replay-usage`) |
| `PortableDev\postgres.log` | PostgreSQL |

## Mode B — dengan Traefik

```
Client ──► Traefik :8080 (web) ─┬─ /v1/*, /health/*  ──► gateway 127.0.0.1:8000 ──► runtime 127.0.0.1:8100
                                └─ /admin/*, /metrics, /docs (ipAllowList) ──►
           Dashboard 127.0.0.1:8081 (hanya dari mesin ini)
```
Traefik satu-satunya pintu masuk dari jaringan. Gateway tetap bind `127.0.0.1:8000`; runtime
`127.0.0.1:8100` **tidak punya** router/service di Traefik.

### 1. Traefik portable
Unduh `traefik_v3.x_windows_amd64.zip` dari rilis resmi
[github.com/traefik/traefik/releases](https://github.com/traefik/traefik/releases), cocokkan
sha256 dengan `traefik_v3.x_checksums.txt`, ekstrak `traefik.exe` ke
`D:\Data.Fahrul\Documents\PortableDev\traefik\` (lokasi lain: set `TRAEFIK_EXE` di `.env`).
Terpasang & diuji: **v3.7.16**. Konfigurasi memakai sintaks v3 (`ipAllowList`; v2 = `ipWhiteList`).

### 2. Konfigurasi (`deploy\traefik\`)
- `traefik.yml` (statis): entrypoint `web` `:8080` (`readTimeout 300s` untuk upload gambar,
  `writeTimeout 0` agar stream SSE panjang tidak diputus, `forwardedHeaders.insecure: false`),
  entrypoint `dashboard` `127.0.0.1:8081`, log `logs\traefik.log` & `logs\traefik-access.log`
  (JSON; header dibuang kecuali `X-Request-ID`, `User-Agent`, `X-Caller-Task` →
  `Authorization` tidak pernah tercatat).
- `dynamic.yml` (di-reload otomatis saat disimpan):
  - router `gateway-public`: `/v1`, `/health` + middleware `sec-headers`, `global-ratelimit`
    (50 req/detik rata-rata, burst 100 per IP), `body-limit` (request maks 20 MB; respons tidak
    dibuffer).
  - router `gateway-admin` (prioritas 100): `/admin`, `/metrics`, `/docs`, `/openapi.json` +
    `admin-allowlist`. **Isi `sourceRange` dengan IP/subnet admin** (default hanya
    `127.0.0.1/32`, `::1/128`).
  - service `gateway` → `http://127.0.0.1:8000` dengan health check `/health/live`.

### 3. Menjalankan
```bat
scripts\start-all-traefik.bat     :: start-all.bat --behind-proxy, lalu Traefik
scripts\stop-all.bat              :: ikut mematikan Traefik
```
`--behind-proxy` = `run_server.py` dengan `proxy_headers`, `forwarded_allow_ips=127.0.0.1`, dan
`TRUST_PROXY=true`, sehingga `requests.client_ip`, rate limit & audit memakai IP klien asli dari
`X-Forwarded-For` (yang diisi Traefik; header kiriman klien dibuang Traefik). Jangan menjalankan
gateway `--behind-proxy` tanpa Traefik di depannya, karena klien bisa memalsukan IP.

Bila gateway sudah berjalan dalam Mode A, matikan dulu (`stop-all.bat --keep-db`):
`start-all.bat` melewati komponen yang sudah hidup.

### 4. TLS opsional (self-signed, tanpa admin)
```bat
mkdir deploy\traefik\certs
"D:\Data.Fahrul\Documents\PortableDev\Git\usr\bin\openssl.exe" req -x509 -newkey rsa:2048 -nodes -days 825 ^
  -keyout deploy\traefik\certs\gateway.key -out deploy\traefik\certs\gateway.crt ^
  -subj "/CN=llm-gateway.local"
```
Aktifkan entrypoint `websecure` (`traefik.yml`) dan blok `tls` (`dynamic.yml`), tambahkan
`websecure` ke `entryPoints` kedua router. `deploy\traefik\certs\` ada di `.gitignore` (private
key tidak boleh di-commit). Klien harus mempercayai sertifikat (Python: `httpx.Client(verify=
"gateway.crt")` / env `SSL_CERT_FILE`).

### Hasil uji Mode B
_Diisi setelah pengujian._

### Waktu start
| Kondisi | Hasil |
|---|---|
| `start-all.bat`, semua mati, cache OpenVINO ada | _diisi setelah pengukuran_ |
| Start runtime pertama tanpa cache (`clear-ov-cache`) | _diisi setelah pengukuran_ |
