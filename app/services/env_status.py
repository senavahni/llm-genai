"""Status variabel `.env` untuk Admin Console: hanya NAMA + keadaan, nilai secret tidak keluar.

Nilai non-secret (port, URL, CORS) boleh ditampilkan agar operator bisa mencocokkan konfigurasi.
"""

from typing import Any, Literal

from app.core.config import MIN_SECRET_LEN, Settings

PLACEHOLDER = "CHANGE_ME"
EnvState = Literal["ok", "missing", "placeholder", "weak"]


def secret_state(raw: str | None, *, min_len: int = 0) -> EnvState:
    if not raw:
        return "missing"
    if PLACEHOLDER in raw:
        return "placeholder"
    if min_len and len(raw) < min_len:
        return "weak"
    return "ok"


def _secret(settings: Settings, field: str) -> str | None:
    value = getattr(settings, field)
    return value.get_secret_value() if value is not None else None


def _var(
    name: str, group: str, help_text: str, *, state: EnvState, required: bool, value: Any = None
) -> dict[str, Any]:
    return {
        "name": name,
        "group": group,
        "required": required,
        "secret": value is None,
        "state": state,
        "value": value,
        "help": help_text,
    }


def env_vars(settings: Settings) -> list[dict[str, Any]]:
    core, prov = "Inti & keamanan", "API key provider"
    return [
        _var(
            "APP_ENV", core, "dev / test / prod.", state="ok", required=True, value=settings.app_env
        ),
        _var(
            "APP_PORT",
            core,
            "Port Gateway (MCP memakai LLM_GATEWAY_URL ke port ini).",
            state="ok",
            required=True,
            value=settings.app_port,
        ),
        _var(
            "CORS_ORIGINS",
            core,
            "Origin browser yang boleh memanggil API (dipisah koma).",
            state="ok",
            required=False,
            value=",".join(settings.cors_origins) or "-",
        ),
        _var(
            "DATABASE_URL",
            core,
            "Koneksi PostgreSQL Gateway (berisi password).",
            state=secret_state(settings.database_url),
            required=True,
        ),
        _var(
            "GATEWAY_KEY_PEPPER",
            core,
            "Pepper hash semua API key lgw_. JANGAN diganti: semua key yang ada jadi tidak valid.",
            state=secret_state(_secret(settings, "gateway_key_pepper"), min_len=MIN_SECRET_LEN),
            required=True,
        ),
        _var(
            "RUNTIME_TOKEN",
            core,
            "Token Gateway <-> runtime model lokal. Ganti = restart Gateway & runtime bersamaan.",
            state=secret_state(_secret(settings, "runtime_token"), min_len=MIN_SECRET_LEN),
            required=True,
        ),
        _var(
            "OPENAI_API_KEY",
            prov,
            "Dipakai provider 'openai' (route fast/smart default).",
            state=secret_state(_secret(settings, "openai_api_key")),
            required=False,
        ),
        _var(
            "ANTHROPIC_API_KEY",
            prov,
            "Dipakai provider 'anthropic'.",
            state=secret_state(_secret(settings, "anthropic_api_key")),
            required=False,
        ),
        _var(
            "GEMINI_API_KEY",
            prov,
            "Dipakai provider 'gemini'.",
            state=secret_state(_secret(settings, "gemini_api_key")),
            required=False,
        ),
        _var(
            "OPENAI_ADMIN_KEY",
            prov,
            "Admin key organisasi OpenAI (sk-admin-...) untuk biaya & usage aktual di menu Usage.",
            state=secret_state(_secret(settings, "openai_admin_key")),
            required=False,
        ),
        _var(
            "ANTHROPIC_ADMIN_KEY",
            prov,
            "Admin key Anthropic (sk-ant-admin01-...) untuk biaya & usage aktual di menu Usage.",
            state=secret_state(_secret(settings, "anthropic_admin_key")),
            required=False,
        ),
    ]


def provider_key_states(
    settings: Settings, providers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per provider: apakah env API key-nya terisi (`not_needed` = lokal / auth none)."""
    out = []
    for p in providers:
        env = p.get("api_key_env")
        no_auth = (p.get("config") or {}).get("auth") == "none"
        if not env or no_auth:
            state = "not_needed"
        else:
            state = secret_state(settings.provider_secret(env))
        out.append(
            {
                "code": p["code"],
                "display_name": p["display_name"],
                "kind": p.get("kind"),
                "is_enabled": p["is_enabled"],
                "api_key_env": env,
                "key_state": state,
            }
        )
    return out
