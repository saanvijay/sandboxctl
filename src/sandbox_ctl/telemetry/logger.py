"""Structured logging setup.

Configures the root ``logging`` module with a JSON formatter (prod) or a
human-readable text formatter (dev). All modules use ``logging.getLogger(
__name__)`` directly and must never call ``print``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from sandbox_ctl.config import Settings

_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — no third-party dep required."""

    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self._service = service
        self._env = env

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": self._service,
            "env": self._env,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=_safe_default)


def _safe_default(obj: Any) -> str:
    return repr(obj)


def configure_logging(settings: Settings) -> None:
    """Install the configured formatter on the root logger.

    Safe to call more than once — replaces existing handlers so test runs stay
    deterministic.
    """
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter(settings.service_name, settings.service_env))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s - %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
