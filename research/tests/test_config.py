"""Config loading and merge semantics."""

from pathlib import Path

from grid_signals.forecast import config


def test_base_config_loads_and_matches_the_frozen_task() -> None:
    cfg = config.load()
    assert cfg.task.zone == "SE3"
    assert cfg.task.issue_hour_utc == 9
    assert cfg.task.nwp_run_hour_utc == 0
    assert cfg.task.resolution == "1h"
    assert len(cfg.task.quantiles) == 19


def test_deep_merge_overrides_leaves_not_whole_branches() -> None:
    base = {"task": {"zone": "SE3", "resolution": "1h"}, "model": {"lr": 0.1}}
    merged = config.deep_merge(base, {"task": {"zone": "DE_LU"}})
    assert merged["task"] == {"zone": "DE_LU", "resolution": "1h"}
    assert merged["model"] == {"lr": 0.1}
    assert base["task"]["zone"] == "SE3", "deep_merge must not mutate its input"


def test_experiment_override_is_applied(tmp_path: Path) -> None:
    (tmp_path / "experiments").mkdir()
    (tmp_path / "base.yaml").write_text("task:\n  zone: SE3\n  resolution: 1h\n")
    (tmp_path / "experiments" / "exp_001.yaml").write_text(
        "task:\n  resolution: 15min\n"
    )
    cfg = config.load("exp_001", config_dir=tmp_path)
    assert (cfg.name, cfg.task.zone, cfg.task.resolution) == ("exp_001", "SE3", "15min")


def test_fingerprint_is_stable_and_sensitive() -> None:
    a = config.load()
    b = config.load()
    assert a.fingerprint() == b.fingerprint()
    b.task.zone = "DE_LU"
    assert a.fingerprint() != b.fingerprint()
