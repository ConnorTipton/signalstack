from collections.abc import Generator

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_LOCALHOST_CLIENTS = {"127.0.0.1", "::1", "localhost"}


def require_api_key(
    request: Request,
    key: str | None = Security(_api_key_header),
) -> None:
    """Require X-API-Key header when API_KEY is configured.

    Bypasses:
    - API_KEY is not set (local dev).
    - Request came from a loopback client (the bundled web UI on the same box).
      Loopback is enforced by the OS kernel, so it can't be spoofed over the
      network — external callers still need the header.
    """
    if settings.api_key is None:
        return
    if request.client is not None and request.client.host in _LOCALHOST_CLIENTS:
        return
    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
