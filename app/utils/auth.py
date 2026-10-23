from fastapi import Depends, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
from app.extensions import get_db, api_key_header
from app.config import settings
from app.models.client import Client
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = {}  # {client_id: [(timestamp, ...), ...]}
    
    def is_rate_limited(self, client_id: int, limit_per_minute: int, limit_per_day: int) -> bool:
        """Check if client exceeded rate limit"""
        if not settings.RATE_LIMIT_ENABLED:
            return False
        
        now = datetime.utcnow()
        
        if client_id not in self.requests:
            self.requests[client_id] = []
        
        # Clean old entries (older than 1 day)
        self.requests[client_id] = [
            ts for ts in self.requests[client_id]
            if ts > now - timedelta(days=1)
        ]
        
        # Check minute limit
        minute_ago = now - timedelta(minutes=1)
        minute_requests = [ts for ts in self.requests[client_id] if ts > minute_ago]
        if len(minute_requests) >= limit_per_minute:
            return True
        
        # Check day limit
        if len(self.requests[client_id]) >= limit_per_day:
            return True
        
        # Add current request
        self.requests[client_id].append(now)
        return False


rate_limiter = RateLimiter()


async def get_current_client(
    api_key: Optional[str] = Depends(api_key_header),
    db: Session = Depends(get_db)
) -> Client:
    """
    Dependency untuk validasi API key dan mendapatkan client.
    
    Usage:
        @router.post("/endpoint")
        async def endpoint(client: Client = Depends(get_current_client)):
            ...
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {settings.API_KEY_HEADER} header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Query client by API key
    client = db.query(Client).filter(
        Client.api_key == api_key,
        Client.is_active == True
    ).first()
    
    if not client:
        logger.warning(f"Invalid API key attempt: {api_key[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Check rate limit
    if rate_limiter.is_rate_limited(
        client.id,
        client.rate_limit_per_minute,
        client.rate_limit_per_day
    ):
        logger.warning(f"Rate limit exceeded for client: {client.project_name}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit-Minute": str(client.rate_limit_per_minute),
                "X-RateLimit-Limit-Day": str(client.rate_limit_per_day),
            }
        )
    
    return client


def require_api_key(
    client: Client = Depends(get_current_client)
) -> Client:
    """
    Alias untuk get_current_client - lebih eksplisit.
    
    Usage:
        @router.post("/endpoint")
        async def endpoint(client: Client = Depends(require_api_key)):
            ...
    """
    return client


def log_request(
    db: Session,
    client: Client,
    endpoint: str,
    method: str,
    model_used: str,
    status_code: int,
    latency_ms: Optional[int] = None,
    tokens_used: Optional[int] = None,
    error_message: Optional[str] = None,
    metadata: Optional[dict] = None
):
    """
    Log request ke database
    """
    from app.models.request_log import RequestLog
    
    try:
        log = RequestLog(
            client_id=client.id,
            endpoint=endpoint,
            method=method,
            model_used=model_used,
            status_code=status_code,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            error_message=error_message,
            metadata_json=metadata
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log request: {e}")
        db.rollback()