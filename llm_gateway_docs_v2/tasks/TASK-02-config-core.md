# TASK-02 — Core: Config, Error Hierarchy, App Factory

| Item | Nilai |
|---|---|
| Milestone | M1 Fondasi |
| Prioritas | P0 |
| Estimasi | 0.5 hari |
| Dependensi | TASK-01 |
| Referensi PRD | §7.2, §10.1, §14 |

## Tujuan
Menyediakan konfigurasi terpusat, hierarki error yang dipetakan ke format error OpenAI, serta app factory dengan lifespan.

## Spesifikasi

### `app/core/config.py`
```python
from functools import lru_cache
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    log_dir: str = "./logs"

    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 10

    gateway_key_pepper: SecretStr
    default_rpm_limit: int = 120
    default_tpm_limit: int = 200_000
    max_body_mb: int = 20
    cors_origins: list[str] = Field(default_factory=list)

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    trust_proxy: bool = False
    storage_dir: str = "./storage"

    # --- Local Runtime (dipakai gateway & runtime) ---
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 8100
    runtime_url: str = "http://127.0.0.1:8100/v1"
    runtime_token: SecretStr
    models_dir: str = "./local_models"
    ov_cache_dir: str = "./local_models/ov_cache"
    hf_home: str = "./local_models/hf_cache"
    llama_gpu_backend: Literal["cuda", "vulkan"] = "cuda"
    gpu_total_mb: int = 8192
    gpu_reserve_mb: int = 1000
    npu_total_mb: int = 8192
    npu_reserve_mb: int = 700
    allow_cpu_fallback: bool = False
    runtime_queue_timeout_s: int = 30
    runtime_min_residency_s: int = 60
    local_first_token_timeout_s: int = 120
    llama_server_exe: str | None = None      # backend cadangan

    @property
    def gpu_budget_mb(self) -> int: return self.gpu_total_mb - self.gpu_reserve_mb
    @property
    def npu_budget_mb(self) -> int: return self.npu_total_mb - self.npu_reserve_mb

    def provider_secret(self, env_name: str | None) -> str | None:
        """Ambil nilai secret berdasarkan nama env yang tersimpan di tabel providers."""
        ...

@lru_cache
def get_settings() -> Settings:
    return Settings()
```
- Validasi startup: `gateway_key_pepper` dan `runtime_token` minimal 32 karakter; tolak nilai `CHANGE_ME`.
- `allow_cpu_fallback=true` saat `app_env=prod` → log WARNING besar saat start.
- `provider_secret()` membaca `os.environ`/settings berdasarkan nama variabel (mis. `ANTHROPIC_API_KEY`).

### `app/utils/errors.py`
```python
class GatewayError(Exception):
    http_status = 500
    error_type = "server_error"
    code = "internal_error"
    retryable = False          # boleh fallback ke kandidat berikutnya?
    def __init__(self, message: str, *, param: str | None = None, headers: dict | None = None): ...

class InvalidRequestError(GatewayError):   400, "invalid_request_error", "invalid_request"
class CapabilityNotSupported(GatewayError):400, "invalid_request_error", "capability_not_supported"
class AuthenticationError(GatewayError):   401, "authentication_error", "invalid_api_key"
class PermissionDenied(GatewayError):      403, "permission_error", "scope_denied"
class ModelNotAllowed(PermissionDenied):   code="model_not_allowed"
class ModelNotFound(GatewayError):         404, "invalid_request_error", "model_not_found"
class RateLimited(GatewayError):           429, "rate_limit_error", "rate_limited"
class QuotaExceeded(GatewayError):         429, "rate_limit_error", "quota_exceeded"
class UpstreamError(GatewayError):         502, "upstream_error", "upstream_error", retryable=True
class UpstreamTimeout(UpstreamError):      504, code="upstream_timeout"
class UpstreamRateLimited(UpstreamError):  429 dari provider, retryable=True
class UpstreamBadRequest(GatewayError):    400 dari provider, retryable=False
class ServiceUnavailable(GatewayError):    503 (mis. DB down)
# --- model lokal (dipakai runtime & dipetakan ulang oleh adapter gateway) ---
class ModelBusy(UpstreamError):            503, code="model_busy", retryable=True        # antrean/VRAM penuh
class DeviceOOM(UpstreamError):            503, code="device_oom", retryable=True
class DeviceUnavailable(UpstreamError):    503, code="device_unavailable", retryable=True # GPU/NPU tidak ada / CPU ditolak
class UnsupportedSize(InvalidRequestError): code="unsupported_size", param="size"
class ImageNotFound(GatewayError):         404, "invalid_request_error", "image_not_found"
```
- Method `to_openai_dict(request_id)` → `{"error": {...}}` sesuai PRD §10.1.

### `app/middlewares/error_handler.py`
- Handler `GatewayError` → JSONResponse sesuai `http_status`, sertakan header (mis. `Retry-After`).
- Handler `RequestValidationError` → 400 `invalid_request` dengan `param` = lokasi field pertama.
- Handler `Exception` → 500 generik (pesan internal tidak dibocorkan), log ERROR dengan stack.

### `app/core/lifespan.py`
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings)          # TASK-03
    await init_db(app)               # TASK-04
    app.state.http = httpx.AsyncClient(timeout=None, limits=httpx.Limits(max_connections=200))
    await registry.load(app)         # TASK-06
    yield
    await registry.close()
    await app.state.http.aclose()
    await dispose_db()
```

### `app/main.py`
- `create_app()` memasang: lifespan, middleware (request context, CORS bila diisi, body size limit), exception handler, router (`health`, `v1`, `admin`).
- `docs_url` hanya aktif bila `app_env == "dev"` atau diatur eksplisit.

## Deliverables
- [ ] `app/core/config.py`, `app/core/lifespan.py`
- [ ] `app/utils/errors.py`, `app/middlewares/error_handler.py`
- [ ] `app/main.py` dengan app factory

## Acceptance Criteria
1. App gagal start dengan pesan jelas bila `DATABASE_URL` atau `GATEWAY_KEY_PEPPER` kosong/lemah.
2. Raise `ModelNotFound("x")` di route uji → respons 404 berformat OpenAI error dengan `request_id`.
3. Body > `MAX_BODY_MB` → 413.
4. Unit test untuk mapping error lulus.
