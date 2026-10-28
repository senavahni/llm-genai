"""Hierarki error gateway, dipetakan ke format error OpenAI (PRD §10.1)."""

from typing import Any


class GatewayError(Exception):
    http_status = 500
    error_type = "server_error"
    code = "internal_error"
    retryable = False  # boleh fallback ke kandidat berikutnya?
    default_param: str | None = None

    def __init__(
        self,
        message: str,
        *,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.param = param if param is not None else self.default_param
        self.headers = headers or {}

    def to_openai_dict(self, request_id: str | None = None) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "code": self.code,
                "param": self.param,
                "request_id": request_id,
            }
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class InvalidRequestError(GatewayError):
    http_status = 400
    error_type = "invalid_request_error"
    code = "invalid_request"


class CapabilityNotSupported(GatewayError):
    http_status = 400
    error_type = "invalid_request_error"
    code = "capability_not_supported"


class PayloadTooLarge(GatewayError):
    http_status = 413
    error_type = "invalid_request_error"
    code = "payload_too_large"


class AuthenticationError(GatewayError):
    http_status = 401
    error_type = "authentication_error"
    code = "invalid_api_key"


class PermissionDenied(GatewayError):
    http_status = 403
    error_type = "permission_error"
    code = "scope_denied"


class ModelNotAllowed(PermissionDenied):
    code = "model_not_allowed"


class ProjectSuspended(PermissionDenied):
    code = "project_suspended"


class ModelNotFound(GatewayError):
    http_status = 404
    error_type = "invalid_request_error"
    code = "model_not_found"
    default_param = "model"


class NotFound(GatewayError):
    http_status = 404
    error_type = "invalid_request_error"
    code = "not_found"


class RateLimited(GatewayError):
    http_status = 429
    error_type = "rate_limit_error"
    code = "rate_limited"


class QuotaExceeded(GatewayError):
    http_status = 429
    error_type = "rate_limit_error"
    code = "quota_exceeded"


class UpstreamError(GatewayError):
    http_status = 502
    error_type = "upstream_error"
    code = "upstream_error"
    retryable = True


class UpstreamTimeout(UpstreamError):
    http_status = 504
    code = "upstream_timeout"


class UpstreamRateLimited(UpstreamError):
    """429 dari provider."""

    http_status = 429
    error_type = "rate_limit_error"
    code = "upstream_rate_limited"


class UpstreamBadRequest(GatewayError):
    """400 dari provider: kesalahan request, tidak di-fallback."""

    http_status = 400
    error_type = "invalid_request_error"
    code = "upstream_bad_request"


class ServiceUnavailable(GatewayError):
    """Mis. database down."""

    http_status = 503
    error_type = "server_error"
    code = "service_unavailable"


# --- model lokal (dipakai runtime & dipetakan ulang oleh adapter gateway) ---
class ModelBusy(UpstreamError):
    """Antrean/VRAM penuh."""

    http_status = 503
    code = "model_busy"


class DeviceOOM(UpstreamError):
    http_status = 503
    code = "device_oom"


class DeviceUnavailable(UpstreamError):
    """GPU/NPU tidak ada atau load ke CPU ditolak."""

    http_status = 503
    code = "device_unavailable"


class ModelLoadFailed(UpstreamError):
    """Load model lokal gagal (file hilang, konfigurasi melebihi budget, backend error)."""

    http_status = 503
    code = "model_load_failed"


class UnsupportedSize(InvalidRequestError):
    code = "unsupported_size"
    default_param = "size"


class UnsupportedParameter(InvalidRequestError):
    """Parameter valid secara OpenAI tetapi tidak didukung model/backend ini (mis. mask)."""

    code = "unsupported_parameter"


class ContextLengthExceeded(InvalidRequestError):
    code = "context_length_exceeded"


class RequestCancelled(GatewayError):
    """Client memutus koneksi / membatalkan di tengah inferensi (status ala nginx 499)."""

    http_status = 499
    error_type = "request_cancelled"
    code = "cancelled"


class ImageNotFound(GatewayError):
    http_status = 404
    error_type = "invalid_request_error"
    code = "image_not_found"
