"""Configuration loading: YAML files, deep-merged, validated with pydantic."""

import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from renewable_forecast import paths


class TaskConfig(BaseModel):
    """The forecast task definition, frozen once the evaluation protocol is set."""

    zone: str = "SE3"
    fuel_types: list[str] = Field(default_factory=lambda: ["wind_onshore"])
    resolution: str = "1h"
    issue_hour_utc: int = 9
    nwp_run_hour_utc: int = 0
    quantiles: list[float] = Field(
        default_factory=lambda: [round(0.05 * i, 2) for i in range(1, 20)]
    )


class SplitConfig(BaseModel):
    """Rolling-origin backtest geometry. The resampling unit is the delivery day."""

    embargo_days: int = 7
    origin_freq: str = "MS"
    holdout_months: int = 6
    holdout_start: date | None = None
    holdout_end: date | None = None


class Config(BaseModel):
    """Top-level resolved configuration for one experiment."""

    name: str = "base"
    task: TaskConfig = Field(default_factory=TaskConfig)
    splits: SplitConfig = Field(default_factory=SplitConfig)
    sources: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        """Return a stable hash of the resolved config, used as the run id prefix."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base`, returning a new dict."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(experiment: str | None = None, config_dir: Path | None = None) -> Config:
    """Load `base.yaml`, optionally deep-merged with an experiment override."""
    directory = config_dir or paths.CONFIGS
    resolved = yaml.safe_load((directory / "base.yaml").read_text()) or {}
    if experiment:
        override_path = directory / "experiments" / f"{experiment}.yaml"
        resolved = deep_merge(resolved, yaml.safe_load(override_path.read_text()) or {})
        resolved["name"] = experiment
    return Config.model_validate(resolved)
