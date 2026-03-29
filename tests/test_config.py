"""Tests for environment variable validation."""

import pytest

from grid_signals.config import (
    ConfigError,
    get_anthropic_api_key,
    get_entsoe_api_key,
    require_env,
)


class TestRequireEnv:
    def test_returns_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "test-value")
        assert require_env("TEST_VAR") == "test-value"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_VAR", raising=False)
        with pytest.raises(ConfigError, match="TEST_VAR"):
            require_env("TEST_VAR")

    def test_raises_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "")
        with pytest.raises(ConfigError, match="TEST_VAR"):
            require_env("TEST_VAR")


class TestGetEntsoeApiKey:
    def test_returns_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENTSOE_API_KEY", "my-key")
        assert get_entsoe_api_key() == "my-key"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="ENTSOE_API_KEY"):
            get_entsoe_api_key()


class TestGetAnthropicApiKey:
    def test_returns_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "my-key")
        assert get_anthropic_api_key() == "my-key"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            get_anthropic_api_key()
