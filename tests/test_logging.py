"""Tests for structured logging configuration."""

import json
import logging

from grid_signals.logging_config import JSONFormatter, configure_logging


class TestJSONFormatter:
    def test_produces_valid_json(self) -> None:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        formatter = JSONFormatter()
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert "timestamp" in parsed

    def test_includes_exception(self) -> None:
        import sys

        try:
            msg = "boom"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        formatter = JSONFormatter()
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert any("ValueError: boom" in line for line in parsed["exception"])


class TestConfigureLogging:
    def test_json_mode(self) -> None:
        configure_logging(json_output=True)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_text_mode(self) -> None:
        configure_logging(json_output=False)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)
