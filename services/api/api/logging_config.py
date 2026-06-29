"""Shared structlog configuration for API and CLI."""

from __future__ import annotations

import os
import sys
from typing import Any

import structlog

from api.redaction import sanitize_runtime_value

_LOG_LEVELS = {"critical": 50, "error": 40, "warning": 30, "info": 20, "debug": 10}
# This can drift over time, but it is less disruptive than reading image refs
# through Helm chart changes while we need a quick production log marker.
_LOG_VERSION_UUID = "013ca634-6a30-4047-8511-8e5483f313ea"


def _sanitize_log_value(value: Any, *, field_name: str | None = None) -> Any:
    return sanitize_runtime_value(value, field_name=field_name)


def _add_default_service(logger, method_name, event_dict):
    """Ensure API logs always carry a service name for downstream queries."""
    event_dict.setdefault("service", os.getenv("CENTAUR_SERVICE_NAME", "api"))
    return event_dict


def _add_log_version(logger, method_name, event_dict):
    """Attach a manually rotated log version marker to every structured log line."""
    event_dict.setdefault("log_version_uuid", _LOG_VERSION_UUID)
    return event_dict


def _scrub_sensitive_fields(logger, method_name, event_dict):
    """Redact obvious PII and secrets before any renderer emits the log line."""
    return {k: _sanitize_log_value(v, field_name=str(k)) for k, v in event_dict.items()}


def _add_vlogs_msg(logger, method_name, event_dict):
    """Copy event to _msg for VictoriaLogs compatibility."""
    event_dict.setdefault("_msg", event_dict.get("msg") or event_dict.get("event", ""))
    return event_dict


def configure_structlog() -> int:
    """Configure structlog with JSON (prod) or console (dev) rendering.

    Returns the resolved log level integer.
    """
    log_level = _LOG_LEVELS.get(
        (os.getenv("CENTAUR_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "info").lower(), 20
    )
    is_dev = sys.stderr.isatty()
    processors = [
        structlog.contextvars.merge_contextvars,
        _add_default_service,
        _add_log_version,
        _scrub_sensitive_fields,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
    ]
    if is_dev:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(_add_vlogs_msg)
        processors.append(structlog.processors.JSONRenderer())
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        processors=processors,
    )
    return log_level
