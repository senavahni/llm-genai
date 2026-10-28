# TASK-16 — Service: Rate Limit & Kuota

| Item | Nilai |
|---|---|
| Milestone | M5 Governance |
| Prioritas | P0 |
| Estimasi | 1 hari |
| Dependensi | TASK-05, TASK-15 |
| Referensi PRD | F8, F9, §17 (risiko rate limit) |

## Tujuan
Mencegah satu project/key menghabiskan resource atau biaya, tanpa Redis.

## Spesifikasi

### Rate limit — `app/services/ratelimit_service.py`
- Sliding window log per key, in-memory (`dict[key_id, deque[timestamps]]`) untuk RPM.
- TPM: token bucket per key; konsumsi awal = estimasi token input + `max_tokens` (atau 512 default); setelah respons, koreksi dengan usage aktual (refund / tambah).
- Limit = `api_keys.rpm_limit/tpm_limit` atau `DEFAULT_RPM_LIMIT/DEFAULT_TPM_LIMIT`.
- Pelanggaran → `RateLimited` 429 dengan header `Retry-After` (detik, dibulatkan ke atas), `X-RateLimit-Limit-Requests`, `X-RateLimit-Remaining-Requests`, `X-RateLimit-Reset-Requests`.
- Header remaining juga dikirim pada respons sukses.
- Pembersihan entri key idle > 10 menit (task periodik) agar memori tidak bocor.
- `asyncio.Lock` per key tidak diperlukan selama operasi sinkron tanpa `await` di antaranya (satu event loop) — pastikan implementasi tidak menyisipkan `await`.
- Catatan desain: state per proses, sehingga `APP_WORKERS` harus 1 (PRD §17). Abstraksikan via interface `RateLimiterBackend` agar v2 dapat diganti backend PostgreSQL.

### Kuota — `app/services/quota_service.py`
- Ambil `quotas` aktif project (cache 60 detik).
- Pemakaian berjalan dari `usage_daily`:
  - daily: `day = current_date (UTC)`
  - monthly: `day >= date_trunc('month', now())`
- Cache hasil agregat 30 detik per project + penambahan in-memory dari request yang selesai sejak cache dibuat (agar tidak kebobolan banyak dalam 30 detik).
- `check(project_id, images: int = 0)`: untuk endpoint gambar, `max_images` dicek terhadap `image_count` berjalan + `n` yang diminta.
- Bila salah satu `max_requests` / `max_tokens` / `max_images` / `max_cost_usd` terlampaui → `QuotaExceeded` 429, `Retry-After` = detik hingga reset periode (UTC), pesan menyebut periode & dimensi yang habis.
- Kuota dicek **sebelum** memanggil provider; request yang sedang berjalan boleh selesai meski melewati batas (soft limit), dan didokumentasikan.

### Pertimbangan model lokal
- Rate limit/kuota berlaku sama untuk model lokal. Biaya lokal 0 tidak berarti tanpa batas: `max_requests`, `max_tokens`, dan `max_images` tetap membatasi pemakaian GPU/NPU yang terbatas.
- Opsional per key: `rpm_limit_local` di `api_keys` **tidak** ditambahkan di v1. Pembatasan beban perangkat ditangani antrean runtime (`model_busy`) + kuota project.
- TPM untuk endpoint gambar: estimasi 0 token; dibatasi oleh RPM dan `max_images`.

## Deliverables
- [x] `ratelimit_service.py` (+ interface `RateLimiterBackend`, `InMemoryRateLimiter`)
- [x] `quota_service.py`
- [x] Integrasi di semua controller v1 (`admit_and_start`: rate limit → kuota → `usage.start`;
      reservasi dikembalikan bila ditolak; koreksi TPM & penambahan kuota di `usage_service.finish`)
- [x] Unit test dengan waktu di-mock (`tests/unit/test_ratelimit.py`) + integrasi kuota DB
      (`tests/integration/test_quota.py`)

Catatan: admission dilakukan setelah resolve model (request ke model yang tidak ada/tidak diizinkan
tidak memakan jatah). Header `X-RateLimit-*` juga memuat dimensi token (`*-Tokens`).

## Acceptance Criteria
1. Key dengan `rpm_limit=5`: request ke-6 dalam 60 detik → 429 + `Retry-After` benar.
2. Koreksi TPM: request dengan usage aktual kecil mengembalikan sisa token ke bucket.
3. Project dengan `max_cost_usd=0.01/daily` ditolak setelah biaya tercapai; esok hari (UTC) kembali aktif.
3b. Project dengan `max_images=10/daily` yang sudah membuat 9 gambar dan meminta `n=2` → 429 `quota_exceeded` (dimensi `images`).
4. Respons sukses menyertakan header `X-RateLimit-Remaining-Requests`.
5. Memori rate limiter stabil pada simulasi 10.000 key berbeda setelah pembersihan.
