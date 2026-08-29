"""Structured logging and metrics export for production operation.

Logging is JSON lines (no external dependency) so it ships cleanly to any log aggregator.
Metrics follow the Prometheus text exposition format and are served at /metrics; this lets
Grafana/Prometheus scrape the service without a sidecar.

Everything here is process-local and lock-free for the hot path: counters use
``atomic``-style increments on plain ints (GIL protects them in CPython) and are rendered
on demand. Horizontal replicas each export their own /metrics; an aggregator scrapes all.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any


class JSONFormatter(logging.Formatter):
    """Render log records as single-line JSON with a stable field set."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Attach any structured context the caller stashed on the record.
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(env: str, level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Safe to call once at startup."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Quiet noisy libraries unless debugging.
    if env != "development":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@dataclass
class Metrics:
    """In-process counters and gauges exported in Prometheus text format.

    Intentionally minimal: a flat namespace of named counters. Concurrency safety comes from
    CPython's GIL for single increments; the values are only ever read under a scrape, so no
    lock is needed for correctness of the rendered snapshot.
    """

    _counters: dict[str, int] = field(default_factory=dict)
    _gauges: dict[str, float] = field(default_factory=dict)

    def inc(self, name: str, amount: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def to_prometheus(self) -> str:
        lines: list[str] = []
        for name, value in sorted(self._counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for name, value in sorted(self._gauges.items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


# A single process-wide instance, attached to app.state in create_app.
metrics = Metrics()
