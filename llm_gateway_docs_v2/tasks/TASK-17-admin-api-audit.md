# TASK-17 — Admin API & Audit Log

| Item | Nilai |
|---|---|
| Milestone | M5 Governance |
| Prioritas | P0 |
| Estimasi | 2.5 hari |
| Dependensi | TASK-05, TASK-10, TASK-13, TASK-15 |
| Referensi PRD | §10.3, F13, F14 |

## Tujuan
Mengelola project, key, provider, model, route, kuota, dan menelusuri request secara terkontrol dengan jejak audit lengkap.

## Spesifikasi

### Struktur
- Routes: `app/routes/admin/{projects,keys,providers,models,routes,quotas,requests,usage,audit,maintenance}.py`, semua `dependencies=[Depends(require_admin())]`, prefix `/admin`, tag `admin`.
- Controllers: `app/controllers/admin/*.py`.
- Services: `project_service`, `key_service`, `model_service` (provider/model/route), `quota_service`, `audit_service`.
- Schemas: `app/schemas/admin.py` — `*Create`, `*Update` (semua field opsional), `*Out`. `ApiKeyOut` **tidak** pernah memuat hash; `ApiKeyCreatedOut` memuat `key` (sekali).

### Endpoint & aturan bisnis
| Endpoint | Aturan |
|---|---|
| `POST /admin/projects` | `slug` regex `^[a-z0-9][a-z0-9-]{1,62}$`, unik |
| `DELETE /admin/projects/{id}` | soft: `status='archived'` + revoke semua key |
| `PATCH /admin/projects/{id}` (`status=suspended`) | invalidate cache auth semua key project |
| `PUT /admin/projects/{id}/allowed-models` | ganti seluruh daftar pola; validasi pola tidak kosong |
| `POST /admin/projects/{id}/keys` | scopes ⊆ daftar scope valid; role client |
| `POST /admin/keys/{id}/revoke` | wajib `reason` |
| `POST /admin/keys/{id}/rotate` | kembalikan key baru sekali |
| `PATCH /admin/providers/{code}` | `is_enabled`, `timeout_seconds`, `max_concurrency`, `base_url`, `config` → `registry.reload()` |
| `POST /admin/providers/{code}/test` | panggil `provider.health()`, kembalikan latency & detail |
| `POST/PATCH/DELETE /admin/models` | alias tidak bentrok dengan alias route; delete ditolak jika masih dipakai route (409) → sarankan disable |
| `POST/PATCH/DELETE /admin/routes` | targets `[{model_alias, priority, weight}]`; minimal 1 target enabled |
| `PUT /admin/projects/{id}/quotas` | upsert daily/monthly |
| `GET /admin/requests` | filter PRD §10.3; paginasi **cursor** (`created_at,id`) `limit ≤ 200` |
| `GET /admin/requests/{id}` | gabung attempts + payload (jika belum kedaluwarsa) |
| `GET /admin/usage` | `from`, `to`, `group_by=day|project|model|provider` |
| `GET /admin/audit-logs` | filter `entity_type`, `entity_id`, `actor`, waktu |
| `POST /admin/cache/reload` | reload registry gateway + `POST /runtime/catalog/reload` + kosongkan cache auth/kuota |
| `PATCH /admin/models/{alias}` (model lokal) | field tambahan: `is_pinned`, `vram_mb`, `device`, `runtime_backend`, `artifact_path`, `config`. Validasi: total `vram_mb` model pinned per device ≤ budget device (`GPU 7200`, `NPU 7500`), `device` lokal ≠ `cpu` kecuali `ALLOW_CPU_FALLBACK`, dan `artifact_path` ada di disk. Setelah commit → reload katalog runtime. |
| `GET /admin/runtime/status` | proksi ke `/runtime/status`: per device `total/budget/used_mb`, model termuat (`pinned`, `in_flight`, `last_used`, `loaded_at`), panjang antrean |
| `POST /admin/runtime/models/{alias}/load` | load manual (warmup sebelum jam sibuk); `?pin=true` hanya sampai restart runtime |
| `POST /admin/runtime/models/{alias}/unload` | tolak (409) bila model pinned atau sedang `in_flight` > 0, kecuali `?force=true` (menunggu request selesai, maks 60 detik) |
| `GET /admin/runtime/events` | filter `model`, `device`, `event`, `from`, `to`; paginasi cursor |
| `GET /admin/runtime/swap-stats?from=&to=` | agregat `runtime_events`: jumlah load/evict per model, rata-rata `duration_ms`, top model pemicu thrashing |

### Audit (`app/services/audit_service.py`)
- `record(actor: AuthContext, action, entity_type, entity_id, before, after, ip, request_id)` dipanggil di **service layer** dalam transaksi yang sama dengan perubahan data (atomic).
- `before/after` = snapshot dict hasil `*Out` schema (otomatis tanpa secret).
- Daftar action: `project.create|update|archive`, `project.allowed_models.set`, `key.create|revoke|rotate`, `provider.update`, `model.create|update|delete`, `route.create|update|delete`, `quota.set`, `cache.reload`, `maintenance.retention`, `runtime.load`, `runtime.unload`, `model.pin`, `model.unpin`.

### Konvensi respons
- List: `{"data": [...], "next_cursor": "..."|null}`.
- Error memakai format error yang sama (PRD §10.1).
- Concurrency edit: `PATCH` menerima `If-Match` berupa `updated_at` ISO (opsional) → 409 jika berbeda.

## Deliverables
- [ ] Seluruh route/controller/service/schema admin
- [ ] `audit_service.py` + integrasi di setiap operasi tulis
- [ ] Koleksi request contoh `docs/admin-api.http` (format REST Client / bisa dipakai di VS Code)
- [ ] Test integrasi alur: buat project → set allowed models → buat key → pakai key → revoke → ditolak

## Acceptance Criteria
1. Setiap operasi tulis admin menghasilkan tepat 1 baris `audit_logs` dalam transaksi yang sama (rollback → audit ikut batal).
2. Respons dan audit log tidak pernah memuat `key_hash` atau secret provider.
3. Perubahan model/route berlaku tanpa restart.
4. `GET /admin/requests?caller_task=research-42` mengembalikan request yang sesuai dengan paginasi cursor stabil.
5. Hapus model yang dipakai route → 409.
6. Pin model yang membuat total pinned GPU > 7200 MB → 422 dengan rincian budget.
7. `POST /admin/runtime/models/local/qwen2.5-7b/load` → tercatat di `audit_logs` (`runtime.load`) **dan** `runtime_events` (`load`); status runtime menampilkan model termuat.
