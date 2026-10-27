# TASK-05 — Utils & Service: Autentikasi API Key

| Item | Nilai |
|---|---|
| Milestone | M1 Fondasi |
| Prioritas | P0 |
| Estimasi | 1 hari |
| Dependensi | TASK-03, TASK-04 |
| Referensi PRD | §11, F7 |

## Tujuan
Autentikasi API key per project yang aman, cepat (cache), dan mendukung scope serta role admin.

## Spesifikasi

### Format key
```
lgw_<prefix 8 char [a-z0-9]>_<secret 43 char token_urlsafe(32)>
contoh: lgw_k3m9x2qa_Vt0p...
```
- DB menyimpan `key_prefix` (unik) dan `key_hash = HMAC_SHA256(pepper, full_key).hexdigest()`.

### `app/utils/crypto.py`
- `generate_api_key() -> tuple[str, str, str]` → `(full_key, prefix, hash)`.
- `hash_api_key(full_key) -> str`.
- `verify(full_key, stored_hash) -> bool` dengan `hmac.compare_digest`.

### `app/services/key_service.py`
- `create_key(project_id, name, scopes, role, rpm_limit, tpm_limit, expires_at, created_by)` → mengembalikan `full_key` sekali + entitas.
- `revoke_key(key_id, reason)`, `rotate_key(key_id)` (buat baru dengan atribut sama, revoke lama).
- `authenticate(raw_key) -> AuthContext`:
  1. Parse format; jika salah → `AuthenticationError`.
  2. Lookup cache in-memory `prefix → (ApiKeyRow, ProjectRow)` TTL 60 detik; miss → query DB (join project).
  3. Verifikasi hash; cek `status=active`, `expires_at`, `project.status=active` (`project_suspended` → 403).
  4. Update `last_used_at` secara throttled (maks 1x/menit per key, via background task).
- `invalidate(prefix)` dipanggil saat revoke/rotate/update project.

### `AuthContext` (dataclass, `app/schemas/common.py`)
```python
key_id, key_prefix, role, scopes: frozenset[str], project_id, project_slug,
log_payloads, payload_retention_days, rpm_limit, tpm_limit
```

### `app/utils/auth.py` (FastAPI dependencies)
```python
async def get_auth(request: Request) -> AuthContext:
    raw = bearer dari Authorization  ATAU  header x-api-key
    ctx = await key_service.authenticate(raw)
    request.state.auth = ctx
    structlog.contextvars.bind_contextvars(project_slug=ctx.project_slug, key_prefix=ctx.key_prefix)
    return ctx

def require_scope(scope: str):  -> dependency, 403 scope_denied jika tidak punya
# scope valid: chat, completions, embeddings, images, models:read, usage:read
def require_admin():            -> dependency, 403 jika role != admin
```

### CLI bootstrap (`scripts/manage.py`)
- `create-admin-key --name "bootstrap"` → cetak key ke stdout sekali.
- `create-project --slug ... --name ...` dan `create-key --project ... --name ...` (memudahkan sebelum Admin API jadi).

## Deliverables
- [ ] `app/utils/crypto.py`, `app/utils/auth.py`
- [ ] `app/services/key_service.py` dengan cache TTL
- [ ] Perintah CLI di `scripts/manage.py`
- [ ] `tests/unit/test_crypto.py`, `tests/integration/test_auth.py`

## Acceptance Criteria
1. Tanpa header / key salah / key revoked / key expired → 401 `invalid_api_key`.
2. Key valid tanpa scope `chat` memanggil `/v1/chat/completions` → 403 `scope_denied`.
3. Client key memanggil `/admin/*` → 403.
4. Revoke key → ditolak paling lambat 60 detik (segera jika pada instance yang sama karena `invalidate`).
5. Kolom `key_hash` tidak pernah muncul di log maupun respons API.
6. Lookup key ter-cache: < 1 ms (tanpa query DB) pada cache hit.
