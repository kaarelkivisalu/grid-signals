"""Structured logging configuration using stdlib only."""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            if isinstance(record.exc_info, tuple) and record.exc_info[1] is not None:
                entry["exception"] = traceback.format_exception(*record.exc_info)
            elif record.exc_text:
                entry["exception"] = record.exc_text
        return json.dumps(entry, default=str)


def configure_logging(*, json_output: bool | None = None) -> None:
    """Set up root logging.

    Args:
        json_output: True for JSON lines, False for human-readable text.
            Defaults to True when stderr is not a TTY.
    """
    if json_output is None:
        json_output = not sys.stderr.isatty()

    handler = logging.StreamHandler()

    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
