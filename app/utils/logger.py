import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.config import settings


def setup_logger() -> logging.Logger:
    """
    Setup root logger dengan console dan file handler
    """
    # Create root logger
    logger = logging.getLogger(settings.APP_NAME)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (rotating)
    if settings.LOG_FILE:
        log_path = Path(settings.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Get logger instance
    
    Usage:
        logger = get_logger(__name__)
        logger.info("Message")
    """
    if name:
        return logging.getLogger(f"{settings.APP_NAME}.{name}")
    return logging.getLogger(settings.APP_NAME)


# Convenience functions
def log_info(message: str, **kwargs):
    """Log info message"""
    logger = get_logger()
    if kwargs:
        message = f"{message} | {kwargs}"
    logger.info(message)


def log_error(message: str, **kwargs):
    """Log error message"""
    logger = get_logger()
    if kwargs:
        message = f"{message} | {kwargs}"
    logger.error(message)


def log_warning(message: str, **kwargs):
    """Log warning message"""
    logger = get_logger()
    if kwargs:
        message = f"{message} | {kwargs}"
    logger.warning(message)


def log_debug(message: str, **kwargs):
    """Log debug message"""
    logger = get_logger()
    if kwargs:
        message = f"{message} | {kwargs}"
    logger.debug(message)