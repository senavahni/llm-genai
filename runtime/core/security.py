import hmac

from fastapi import Header, Request

from app.utils.errors import AuthenticationError


async def require_runtime_token(
    request: Request, x_runtime_token: str | None = Header(default=None)
) -> None:
    expected = request.app.state.settings.runtime_token.get_secret_value()
    if not x_runtime_token or not hmac.compare_digest(x_runtime_token.encode(), expected.encode()):
        raise AuthenticationError("X-Runtime-Token tidak ada atau salah")
