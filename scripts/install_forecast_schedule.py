"""Install the local, user-owned forecast timers; no system-wide services."""

import argparse
import json
import shlex
import subprocess  # noqa: S404 -- fixed systemctl commands
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
JOBS = {"capture": "08:55:00", "forecast": "09:00:00", "score": "15:00:00"}


def units(project: Path, python: Path) -> dict[str, str]:
    files = {}
    for mode, clock in JOBS.items():
        name = f"grid-signals-{mode}"
        files[f"{name}.service"] = f"""[Unit]
Description=Grid Signals {mode}
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={project}
Environment="MPLCONFIGDIR=/tmp/grid-signals-matplotlib"
Environment="OMP_NUM_THREADS=4"
Environment="LOKY_MAX_CPU_COUNT=4"
Environment="OPENBLAS_NUM_THREADS=4"
ExecStart={shlex.quote(str(python))} -m grid_signals workflow {mode}
TimeoutStartSec=27min
Nice=10
"""
        files[f"{name}.timer"] = f"""[Unit]
Description=Grid Signals daily {mode} at {clock} UTC

[Timer]
OnCalendar=*-*-* {clock} UTC
Persistent=true
AccuracySec=1s

[Install]
WantedBy=timers.target
"""
    return files


def install(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in units(PROJECT, PROJECT / ".venv/bin/python").items():
        (directory / name).write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(  # noqa: S603 -- fixed service names and systemctl executable
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            *[f"grid-signals-{mode}.timer" for mode in JOBS],
        ],
        check=True,
    )
    operational = PROJECT / "research/data/operational"
    operational.mkdir(parents=True, exist_ok=True)
    trial = operational / "trial.json"
    if not trial.exists():
        now = datetime.now(UTC)
        first = now.date() if now.hour < 9 else now.date() + timedelta(days=1)
        trial.write_text(
            json.dumps(
                {
                    "installed_at": now.isoformat(),
                    "first_issue_day": first.isoformat(),
                    "timezone": "UTC",
                    "jobs": JOBS,
                },
                indent=2,
            )
        )
    print(
        "Installed local forecast timers; missed/later executions remain labelled late."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".config/systemd/user"
    )
    args = parser.parse_args()
    install(args.directory)
