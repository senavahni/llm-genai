"""Logging terstruktur JSON, non-blocking (QueueHandler → QueueListener), dengan redaksi secret."""

import atexit
import logging
import queue
import re
import sys
from collections.abc import Mapping
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import orjson
import structlog

if TYPE_CHECKING:
    from app.core.config import Settings

REDACTED = "***REDACTED***"
ACCESS_LOGGER = "gateway.access"
RUNTIME_NATIVE_LOGGER = "runtime.native"

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "x_api_key",
        "x_runtime_token",
        "runtime_token",
        "api_key",
        "password",
        "secret",
        "token",
        "key_hash",
    }
)
_SENSITIVE_SUFFIXES = ("_api_key", "_password", "_secret", "_pepper")

_VALUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(lgw_[A-Za-z0-9]{8})_[A-Za-z0-9_\-]+"), r"\1_" + REDACTED),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]+"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), REDACTED),
    # bearer token selain lgw_ (yang sudah ditangani di atas dengan prefix tetap terlihat)
    (re.compile(r"(?i)\b(bearer\s+)(?!lgw_)[A-Za-z0-9._~+/\-]{8,}=*"), r"\1" + REDACTED),
]


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    norm = key.lower().replace("-", "_")
    return norm in _SENSITIVE_KEYS or norm.endswith(_SENSITIVE_SUFFIXES)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        for pattern, repl in _VALUE_PATTERNS:
            value = pattern.sub(repl, value)
        return value
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if _is_sensitive_key(k) and v is not None else redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(redact_value(v) for v in value)
    return value


def redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return redact_value(event_dict)  # type: ignore[no-any-return]


def _orjson_dumps(obj: Any, **_: Any) -> str:
    return orjson.dumps(obj, default=str, option=orjson.OPT_NON_STR_KEYS).decode()


_SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
    redact_processor,
]


class _InProcessQueueHandler(QueueHandler):
    """QueueHandler bawaan memformat record ke string di prepare(); itu merusak event dict
    structlog. Antrean ini in-process, jadi record cukup diteruskan apa adanya."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


class _LoggingState:
    listeners: list[QueueListener] = []
    queue_handlers: list[tuple[logging.Logger, logging.Handler]] = []


def _json_formatter() -> logging.Formatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(serializer=_orjson_dumps),
        ],
    )


def _console_formatter(dev: bool) -> logging.Formatter:
    if not dev:
        return _json_formatter()
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty(), timestamp_key="ts"),
        ],
    )


def _file_handler(
    path: Path, level: int, backup_count: int, when: str, formatter: logging.Formatter
) -> logging.Handler:
    handler = TimedRotatingFileHandler(
        path, when=when, backupCount=backup_count, encoding="utf-8", utc=True, delay=True
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _attach(logger: logging.Logger, handlers: list[logging.Handler]) -> None:
    q: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    qh = _InProcessQueueHandler(q)
    logger.addHandler(qh)
    listener = QueueListener(q, *handlers, respect_handler_level=True)
    listener.start()
    _LoggingState.listeners.append(listener)
    _LoggingState.queue_handlers.append((logger, qh))


def shutdown_logging() -> None:
    """Flush antrean dan tutup file log. Aman dipanggil berkali-kali."""
    for listener in _LoggingState.listeners:
        listener.stop()
        for h in listener.handlers:
            h.close()
    for logger, qh in _LoggingState.queue_handlers:
        logger.removeHandler(qh)
    _LoggingState.listeners = []
    _LoggingState.queue_handlers = []


def setup_logging(
    settings: "Settings",
    component: Literal["gateway", "runtime"] = "gateway",
    *,
    rotate_when: str = "midnight",
    console: bool = True,
) -> None:
    shutdown_logging()

    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    dev = settings.app_env == "dev"
    json_fmt = _json_formatter()

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if component == "gateway":
        main_file, error_file = "app.log", "error.log"
    else:
        main_file, error_file = "runtime.log", "runtime-error.log"

    root_handlers = [
        _file_handler(log_dir / main_file, level, 14, rotate_when, json_fmt),
        _file_handler(log_dir / error_file, logging.ERROR, 30, rotate_when, json_fmt),
    ]
    console_handler: logging.Handler | None = None
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(_console_formatter(dev))
        root_handlers.append(console_handler)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)
    _attach(root, root_handlers)

    if component == "gateway":
        access = logging.getLogger(ACCESS_LOGGER)
        access.handlers.clear()
        access.setLevel(logging.INFO)
        access.propagate = False
        access_handlers: list[logging.Handler] = [
            _file_handler(log_dir / "access.log", logging.INFO, 14, rotate_when, json_fmt)
        ]
        if console:
            ch = logging.StreamHandler(sys.stderr)
            ch.setLevel(level)
            ch.setFormatter(_console_formatter(dev))
            access_handlers.append(ch)
        _attach(access, access_handlers)
    else:
        # log native OpenVINO ditulis level DEBUG → muncul di runtime.log bila
        # LOG_LEVEL=DEBUG, tersaring otomatis pada level lebih tinggi.
        logging.getLogger(RUNTIME_NATIVE_LOGGER).setLevel(logging.DEBUG)

    # uvicorn: lewat root (format kita); access log bawaan dimatikan, diganti middleware.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    uv_access = logging.getLogger("uvicorn.access")
    uv_access.handlers.clear()
    uv_access.propagate = False
    uv_access.disabled = True

    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


atexit.register(shutdown_logging)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)  # type: ignore[no-any-return]
