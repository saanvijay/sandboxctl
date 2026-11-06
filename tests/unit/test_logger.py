from __future__ import annotations

import json
import logging

from sandbox_ctl.config import Settings
from sandbox_ctl.telemetry.logger import JsonFormatter, configure_logging


def test_json_formatter_includes_extra() -> None:
    fmt = JsonFormatter("svc", "dev")
    record = logging.LogRecord("x", logging.INFO, "x", 1, "hello", None, None)
    record.session_id = "s_abc"
    out = json.loads(fmt.format(record))
    assert out["msg"] == "hello"
    assert out["service"] == "svc"
    assert out["session_id"] == "s_abc"


def test_configure_logging_replaces_handlers(settings: Settings, capsys: object) -> None:
    configure_logging(settings)
    root = logging.getLogger()
    first_handlers = list(root.handlers)
    configure_logging(settings)
    assert len(root.handlers) == 1
    assert first_handlers != root.handlers


def test_json_formatter_handles_exceptions() -> None:
    fmt = JsonFormatter("svc", "dev")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, "x", 1, "oops", None, sys.exc_info())
    out = json.loads(fmt.format(record))
    assert "boom" in out["exc"]
