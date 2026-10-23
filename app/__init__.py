from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.config import settings
from app.extensions import init_db
from app.utils.logger import setup_logger


# Setup logger
logger = setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events - dijalankan saat startup dan shutdown
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info(f"Storage: {settings.STORAGE_PATH}")
    
    # Initialize database
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="LLM Gateway API - Unified interface for local and external LLMs",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    
    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure properly in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
                "details": str(exc) if settings.DEBUG else None
            }
        )
    """
    # Register routers
    from app.routes import chat, image, vision, files
    
    app.include_router(
        chat.router,
        prefix="/api/v1",
        tags=["Chat"]
    )
    app.include_router(
        image.router,
        prefix="/api/v1",
        tags=["Image Generation"]
    )
    app.include_router(
        vision.router,
        prefix="/api/v1",
        tags=["Vision"]
    )
    app.include_router(
        files.router,
        prefix="/api/v1",
        tags=["Files"]
    )
    """
    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION
        }
    
    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "message": f"Welcome to {settings.APP_NAME}",
            "version": settings.APP_VERSION,
            "docs": "/docs"
        }
    
    return app


# Create app instance
app = create_app()