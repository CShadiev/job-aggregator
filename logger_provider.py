from __future__ import annotations
import os
import sys
from config import ConfigProvider
import loguru
from loguru import logger

config = ConfigProvider.get_config()


class LoggerProvider:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logger.remove()
    log_level = "DEBUG" if config.DEBUG_MODE else "INFO"
    format = "<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}"
    logger.add(sys.stdout, level=log_level, colorize=True, format=format)
    logger.add(
        f'{config.LOG_DIR}/INFO.log',
        level="INFO",
        rotation="50 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,
        backtrace=True,
        diagnose=config.DEBUG_MODE,
        serialize=True,
    )
    logger.add(
        f'{config.LOG_DIR}/DEBUG.log',
        level="DEBUG",
        rotation="50 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,
        backtrace=True,
        diagnose=config.DEBUG_MODE,
        serialize=True,
    )
    __logger = logger

    @classmethod
    def get_logger(cls) -> loguru.Logger:
        return logger
