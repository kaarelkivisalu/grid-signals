"""Resume weather backfills and write an explicit coverage manifest.

Example: python -m grid_signals.forecast.pipelines.refresh_archives 2026-03-01 2026-10-16
Date ranges are half-open. This downloads inputs only; it never scores the holdout.
"""

import argparse
import json
import logging
import tarfile
from datetime import UTC, date, datetime, timedelta

from grid_signals.forecast import paths
from grid_signals.forecast.features import sites, solar
from grid_signals.forecast.sources import ifs_runs, meps, openmeteo

logger = logging.getLogger(__name__)


def coverage(start: date, end: date) -> dict:
    """Parsed-run coverage by cycle; missing runs remain explicit, never zero wind."""
    now = datetime.now(UTC)
    result = {
        "checked_at": now.isoformat(),
        "start": str(start),
        "end_exclusive": str(end),
        "sources": {},
    }
    for source, hour in (("meps", 0), ("ifs_runs", 0), ("ifs_runs", 18)):
        missing, available = [], []
        day = start
        while day < end:
            run = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
            # Current-day 18z is not missing before it has even been initialised.
            if (
                run
                + (
                    ifs_runs.AVAILABILITY_LAG
                    if source == "ifs_runs"
                    else timedelta(hours=4)
                )
                <= now
            ):
                path = paths.PARSED / source / f"run={run:%Y%m%dT%H}Z" / "data.parquet"
                (available if path.exists() else missing).append(str(day))
            day += timedelta(days=1)
        result["sources"][f"{source}_{hour:02d}z"] = {
            "available": len(available),
            "latest": max(available) if available else None,
            "missing": missing,
        }
    return result


def backup() -> None:
    """Preserve a timestamped copy before replacing parsed weather rows."""
    directory = paths.DATA / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"nwp-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        if paths.PARSED.exists():
            archive.add(paths.PARSED, arcname="parsed")
    logger.info("backup: %s", path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "start", nargs="?", type=date.fromisoformat, default=date(2026, 3, 1)
    )
    parser.add_argument(
        "end",
        nargs="?",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() + timedelta(days=1),
    )
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("start must precede end")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    paths.ensure_data_dirs()
    if not args.status_only:
        backup()
        points = sites.build("SE3")
        meps.pull(points, args.start, args.end, newest_first=True)
        now = datetime.now(UTC)
        for hour in (0, 18):
            last_available = now - ifs_runs.AVAILABILITY_LAG
            stop = min(
                args.end,
                last_available.date()
                + timedelta(days=int(last_available.hour >= hour)),
            )
            ifs_runs.pull(points, args.start, stop, hour)
        openmeteo.pull(points, args.start, args.end + timedelta(days=2), merge=True)
        openmeteo.pull(
            solar.sites(),
            args.start,
            args.end + timedelta(days=2),
            models=(solar.MODEL,),
            variables=solar.VARIABLES,
            merge=True,
        )
    manifest = coverage(args.start, args.end)
    path = paths.INTERIM / "weather_archive_status.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return int(any(source["missing"] for source in manifest["sources"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
