"""Centralized environment variable validation."""

import os

DEFAULT_DATABASE_URL = "postgresql://localhost/grid_signals"


class ConfigError(Exception):
    """Raised when a required configuration value is missing or invalid."""


def require_env(name: str) -> str:
    """Return the value of an environment variable, or raise ConfigError if missing."""
    value = os.environ.get(name)
    if not value:
        msg = (
            f"Required environment variable {name!r} is not set. "
            f"Set it in your environment or .env file."
        )
        raise ConfigError(msg)
    return value


def get_database_url() -> str:
    """Return DATABASE_URL from the environment, or the default."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_entsoe_api_key() -> str:
    """Validate and return the ENTSO-E API key."""
    return require_env("ENTSOE_API_KEY")


def get_anthropic_api_key() -> str:
    """Validate and return the Anthropic API key."""
    return require_env("ANTHROPIC_API_KEY")
