"""Logging system for ACE - Layer 0 immutable audit trail"""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(
    log_dir: str = "logs",
    level: int = logging.INFO,
    deterministic_mode: bool = False,
) -> logging.Logger:
    """
    Set up comprehensive logging system for ACE.
    
    Args:
        log_dir: Directory for log files
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        deterministic_mode: If True, use fixed timestamp for reproducibility
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("ACE")
    logger.setLevel(level)
    
    # File handler - System log
    system_log_file = log_path / "system.log"
    file_handler = logging.handlers.RotatingFileHandler(
        system_log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(levelname)s | %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    if not logger.handlers:  # Avoid duplicate handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    logger.info(f"ACE Logging initialized - Level: {logging.getLevelName(level)}")
    logger.info(f"Log directory: {system_log_file.absolute()}")
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with given name."""
    return logging.getLogger(f"ACE.{name}")
