# TASK-22 — Deployment Mode B: Dengan Traefik (Portable)

| Item | Nilai |
|---|---|
| Milestone | M6 Kualitas & Rilis |
| Prioritas | P1 |
| Estimasi | 1 hari |
| Dependensi | TASK-21 |
| Referensi PRD | §15.2, §11 |

## Tujuan
Menempatkan Traefik sebagai satu-satunya pintu masuk: pembatasan IP untuk `/admin`, rate limit global, header keamanan, access log, dan opsional TLS — semuanya dengan binary portable tanpa admin & tanpa Docker.

## Topologi
```
Client ──► Traefik :8080 (web)  ─┬─ /v1/*, /health/*  ──► gateway 127.0.0.1:8000 ──► runtime 127.0.0.1:8100
           Traefik :8443 (opsional TLS)  └─ /admin/*  (ipAllowList) ──►
           Dashboard 127.0.0.1:8081
```
**Traefik tidak pernah merutekan ke Local Runtime (8100).** Tidak ada router/service Traefik yang menunjuk ke port runtime; runtime hanya diakses gateway lewat localhost dengan `X-Runtime-Token`.

## Langkah

### 1. Unduh Traefik
- Ambil `traefik_v3.x_windows_amd64.zip` dari GitHub release resmi `traefik/traefik` → ekstrak `traefik.exe` ke `D:\Data.Fahrul\Documents\PortableDev\traefik\`.
- Verifikasi: `traefik.exe version`. Konfigurasi di bawah untuk **Traefik v3** (nama middleware `ipAllowList`; v2 memakai `ipWhiteList`) — cek dokumentasi versi yang diunduh.

### 2. `deploy/traefik/traefik.yml` (static)
```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

entryPoints:
  web:
    address: ":8080"
    transport:
      respondingTimeouts:
        readTimeout: 300s      # upload body besar (gambar base64)
        writeTimeout: 0s       # 0 = tanpa batas, wajib untuk stream SSE panjang
        idleTimeout: 180s
    forwardedHeaders:
      insecure: false
  dashboard:
    address: "127.0.0.1:8081"
  # websecure:
  #   address: ":8443"
  #   http:
  #     tls: {}

api:
  dashboard: true

providers:
  file:
    filename: "deploy/traefik/dynamic.yml"
    watch: true

log:
  level: INFO
  filePath: "logs/traefik.log"
  format: json

accessLog:
  filePath: "logs/traefik-access.log"
  format: json
  bufferingSize: 50
  fields:
    headers:
      defaultMode: drop
      names:
        X-Request-ID: keep
        User-Agent: keep
        X-Caller-Task: keep
```

### 3. `deploy/traefik/dynamic.yml` (dynamic)
```yaml
http:
  routers:
    gateway-public:
      rule: "PathPrefix(`/v1`) || PathPrefix(`/health`)"
      entryPoints: [web]
      service: gateway
      middlewares: [sec-headers, global-ratelimit, body-limit]

    gateway-admin:
      rule: "PathPrefix(`/admin`) || PathPrefix(`/metrics`) || PathPrefix(`/docs`) || PathPrefix(`/openapi.json`)"
      entryPoints: [web]
      service: gateway
      priority: 100
      middlewares: [admin-allowlist, sec-headers]

    dashboard:
      rule: "PathPrefix(`/api`) || PathPrefix(`/dashboard`)"
      entryPoints: [dashboard]
      service: api@internal

  middlewares:
    admin-allowlist:
      ipAllowList:
        sourceRange: ["127.0.0.1/32", "192.168.1.0/24"]   # sesuaikan subnet LAN
    global-ratelimit:
      rateLimit:
        average: 50        # req/detik per IP sumber
        burst: 100
    body-limit:
      buffering:
        maxRequestBodyBytes: 20971520   # 20 MB; response TIDAK dibuffer (maxResponseBodyBytes tidak diset)
        memRequestBodyBytes: 2097152
    sec-headers:
      headers:
        frameDeny: true
        contentTypeNosniff: true
        referrerPolicy: "no-referrer"
        customResponseHeaders:
          Server: ""

  services:
    gateway:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8000"
        passHostHeader: true
        healthCheck:
          path: /health/live
          interval: 10s
          timeout: 3s

# tls:
#   certificates:
#     - certFile: deploy/traefik/certs/gateway.crt
#       keyFile:  deploy/traefik/certs/gateway.key
```
Catatan:
- `readTimeout: 300s` dan `writeTimeout: 0s` juga mencakup request model lokal yang menunggu swap 7B (≤ 120 detik sebelum token pertama) dan pembuatan beberapa gambar SD dalam satu request non-stream (`n=4` bisa > 60 detik).
- Rate limit Traefik (`average: 50`) adalah batas kasar per IP. Batas pemakaian GPU/NPU ditangani antrean runtime + kuota gateway.
- `/v1/images/files/*` ikut router publik (butuh API key di gateway).
- Middleware `buffering` hanya dipakai untuk membatasi ukuran **request**; pastikan pengaturan respons tidak menyebabkan SSE dibuffer. Verifikasi stream tetap real-time (lihat AC 2). Bila ternyata mengganggu streaming di versi Traefik yang dipakai, hapus `body-limit` dan andalkan batas `MAX_BODY_MB` di gateway.
- Traefik mem-flush `text/event-stream` segera; gateway tetap mengirim `X-Accel-Buffering: no`.

### 4. Gateway di belakang proxy
- Jalankan `run_server.py --behind-proxy` (bind 127.0.0.1, `proxy_headers=True`, `forwarded_allow_ips=127.0.0.1`) sehingga `client_ip` di DB = IP client asli dari `X-Forwarded-For`.
- Settings `TRUST_PROXY=true` agar helper `client_ip()` (TASK-03) membaca header forwarded.

### 5. Script
`scripts/start-traefik.bat`
```bat
@echo off
call "%~dp0env.bat"
set "TRAEFIK_EXE=D:\Data.Fahrul\Documents\PortableDev\traefik\traefik.exe"
"%TRAEFIK_EXE%" --configFile="%PROJECT_ROOT%\deploy\traefik\traefik.yml"
```
`scripts/start-all-traefik.bat` = `start-all.bat` dengan gateway `--behind-proxy`, lalu `start "traefik" /min cmd /c ""%~dp0start-traefik.bat""`, lalu healthcheck ke `http://127.0.0.1:8080/health/ready`.
`stop-all.bat` ditambah `taskkill /FI "WINDOWTITLE eq traefik*" /T /F`.

### 6. TLS opsional (self-signed, tanpa admin)
```bat
"D:\Data.Fahrul\Documents\PortableDev\Git\usr\bin\openssl.exe" req -x509 -newkey rsa:2048 -nodes -days 825 ^
  -keyout deploy\traefik\certs\gateway.key -out deploy\traefik\certs\gateway.crt ^
  -subj "/CN=llm-gateway.local"
```
(OpenSSL tersedia di dalam Git portable.) Aktifkan entrypoint `websecure` dan blok `tls`. Klien perlu mempercayai sertifikat atau memakai opsi verify custom.

## Deliverables
- [ ] `deploy/traefik/traefik.yml`, `deploy/traefik/dynamic.yml`
- [ ] `scripts/start-traefik.bat`, `scripts/start-all-traefik.bat`, update `stop-all.bat`
- [ ] Dukungan `--behind-proxy` & `TRUST_PROXY`
- [ ] `docs/deployment.md` bagian Mode B

## Acceptance Criteria
1. `http://127.0.0.1:8080/v1/models` berfungsi via Traefik; port 8000 tidak dapat diakses dari mesin lain.
2. Stream chat lewat Traefik: chunk tiba bertahap (jeda antar-chunk terlihat, bukan sekaligus di akhir) dan stream > 5 menit tidak terputus. Request lokal yang memicu swap model 7B tetap berhasil lewat Traefik.
2b. `http://<ip-mesin>:8100` tidak dapat diakses dari mesin lain, dan Traefik tidak punya route ke port tersebut.
3. `/admin/*` dari IP di luar `sourceRange` → 403 dari Traefik.
4. `requests.client_ip` mencatat IP client asli, bukan 127.0.0.1.
5. Dashboard hanya bisa dibuka dari `127.0.0.1:8081`.
6. Seluruh langkah tanpa admin & tanpa Docker.
