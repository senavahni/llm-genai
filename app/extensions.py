from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from app.config import settings


# SQLAlchemy Base
Base = declarative_base()

# Database Engine
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,  # Verify connections before using
    echo=settings.DEBUG,  # SQL logging in debug mode
)

# Session Factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)


# Dependency: Get Database Session
def get_db() -> Generator:
    """
    Dependency untuk mendapatkan database session.
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Create all tables (untuk development)
def init_db():
    """Initialize database - create all tables"""
    from app.models import Client, RequestLog, GeneratedAsset  # Import models
    Base.metadata.create_all(bind=engine)


# Security: API Key Header
api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False
)