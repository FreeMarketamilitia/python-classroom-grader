"""Logging configuration for the application."""

import logging
import sys
import os
from typing import Optional

# Assuming config.py is in the parent directory relative to utils/
# Adjust the path manipulation if your structure is different.
try:
    # This approach tries to make it work whether run from root or utils/
    import config
except ImportError:
    # If run directly or structure is different, adjust path
    # This adds the parent directory (classroom_ai_grader) to the path
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config

_logger: Optional[logging.Logger] = None

def setup_logger() -> logging.Logger:
    """Sets up and returns the application logger.

    Configures a logger that outputs to both console and a file,
    with the level determined by the DEBUG flag in config.

    Returns:
        logging.Logger: The configured application logger.
    """
    global _logger
    if _logger:
        return _logger

    logger = logging.getLogger("ClassroomGrader")
    logger.setLevel(config.LOG_LEVEL)

    # Prevent adding multiple handlers if called again
    if not logger.handlers:
        formatter = logging.Formatter(config.LOG_FORMAT)

        # Console Handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(config.LOG_LEVEL)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File Handler
        try:
            # Ensure the log directory exists if LOG_FILE includes directories
            log_dir = os.path.dirname(config.LOG_FILE)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            fh = logging.FileHandler(config.LOG_FILE, mode='a', encoding='utf-8')
            fh.setLevel(config.LOG_LEVEL)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except (OSError, IOError) as e:
            logger.error(f"Failed to create file handler for {config.LOG_FILE}: {e}", exc_info=config.DEBUG)
            # Continue without file logging if it fails

    _logger = logger

    if config.DEBUG:
        logger.debug("Logger initialized in DEBUG mode.")
    else:
        logger.info("Logger initialized.")

    return logger

def get_logger() -> logging.Logger:
    """Returns the singleton logger instance, setting it up if necessary."""
    if _logger is None:
        return setup_logger()
    return _logger

# Example usage (for testing purposes)
if __name__ == "__main__":
    logger = get_logger()
    logger.debug("This is a debug message.")
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    logger.critical("This is a critical message.")

    # Test logging exception info in debug mode
    try:
        1 / 0
    except ZeroDivisionError:
        logger.error("Caught an exception!", exc_info=config.DEBUG)
