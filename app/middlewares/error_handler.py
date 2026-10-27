from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.errors import GatewayError, InvalidRequestError, NotFound
from app.utils.logger import get_logger

log = get_logger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def gateway_error_response(exc: GatewayError, request_id: str | None) -> JSONResponse:
    headers = dict(exc.headers)
    if request_id:
        headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        exc.to_openai_dict(request_id), status_code=exc.http_status, headers=headers
    )


async def _handle_gateway_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GatewayError)
    level = "error" if exc.http_status >= 500 else "info"
    getattr(log, level)("gateway_error", code=exc.code, status=exc.http_status, error=exc.message)
    return gateway_error_response(exc, _request_id(request))


def _loc_to_param(loc: tuple[object, ...]) -> str | None:
    parts = [str(p) for p in loc]
    if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
        parts = parts[1:]
    return ".".join(parts) or None


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    first = errors[0] if errors else {}
    param = _loc_to_param(tuple(first.get("loc", ())))
    message = first.get("msg", "Invalid request")
    if param:
        message = f"{param}: {message}"
    return gateway_error_response(InvalidRequestError(message, param=param), _request_id(request))


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        err: GatewayError = NotFound(f"Path {request.url.path} tidak ditemukan")
    else:
        err = GatewayError(str(exc.detail))
        err.http_status = exc.status_code
        err.error_type = "invalid_request_error" if exc.status_code < 500 else "server_error"
        err.code = "invalid_request" if exc.status_code < 500 else "internal_error"
    if exc.headers:
        err.headers.update(exc.headers)
    return gateway_error_response(err, _request_id(request))


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    log.error("unhandled_exception", request_id=request_id, exc_info=exc)
    return gateway_error_response(GatewayError("Internal server error"), request_id)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GatewayError, _handle_gateway_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)
