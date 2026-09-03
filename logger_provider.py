from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import loguru
from loguru import logger
from opentelemetry import trace

from config import ConfigProvider
from telemetry import cycle_id_ctx, request_id_ctx

if TYPE_CHECKING:
    from loguru import Record

config = ConfigProvider.get_config()
_LOG_DIR = Path(config.LOG_DIR)


def _patch_record(record: Record) -> None:
    """Enrich log records with OpenTelemetry trace context and request/cycle correlation IDs."""
    extra = record["extra"]

    # 1. OpenTelemetry Span Context
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            extra["trace_id"] = f"{ctx.trace_id:032x}"
            extra["span_id"] = f"{ctx.span_id:016x}"

    # 2. HTTP Request Correlation ID
    req_id = request_id_ctx.get()
    if req_id and "request_id" not in extra:
        extra["request_id"] = req_id

    # 3. Pipeline Cycle Correlation ID
    cycle_id = cycle_id_ctx.get()
    if cycle_id and "cycle_id" not in extra:
        extra["cycle_id"] = cycle_id


def _stdout_format(record: Record) -> str:
    """Format console output with timestamp, level, context tags, and message."""
    fmt = "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
    extra = record["extra"]
    context_tags: list[str] = []

    if "request_id" in extra:
        context_tags.append(f"req={str(extra['request_id'])[:8]}")
    if "cycle_id" in extra:
        context_tags.append(f"cycle={str(extra['cycle_id'])[:8]}")
    if "trace_id" in extra:
        context_tags.append(f"trace={str(extra['trace_id'])[:8]}")

    if context_tags:
        fmt += f"<cyan>[{', '.join(context_tags)}]</cyan> "

    fmt += "<level>{message}</level>\n"
    if record["exception"]:
        fmt += "{exception}\n"
    return fmt


class LoggerProvider:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(patcher=_patch_record)

    log_level = "DEBUG" if config.DEBUG_MODE else "INFO"
    logger.add(sys.stdout, level=log_level, colorize=True, format=_stdout_format)
    logger.add(
        _LOG_DIR / "INFO.log",
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
        _LOG_DIR / "DEBUG.log",
        level="DEBUG",
        rotation="50 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,
        backtrace=True,
        diagnose=config.DEBUG_MODE,
        serialize=True,
    )
    __logger = logger.bind(app="job-aggregator")

    @classmethod
    def get_logger(cls) -> loguru.Logger:
        return logger
