"""Checked local backups and restoration of forecast data and public evidence."""

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from grid_signals.forecast import live, paths, saved_models
from grid_signals.forecast.storage import sync_directory, sync_file


def backup(
    destination: Path,
    *,
    data: Path = paths.DATA,
    public: Path = paths.OUTPUT,
    prefect_db: Path | None = None,
    already_locked: bool = False,
) -> dict:
    """Snapshot data under the lifecycle lock; use SQLite's online backup API."""
    destination = destination.resolve()
    if destination.is_relative_to(data.resolve()) or destination.is_relative_to(
        public.resolve()
    ):
        raise ValueError(
            "backups must be stored outside the data and exported-result directories"
        )
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        nullcontext() if already_locked else live.lock(),
        tempfile.TemporaryDirectory(prefix="grid-signals-backup-") as temporary,
    ):
        directory = Path(temporary)
        db = prefect_db or (
            Path(os.environ["GRID_SIGNALS_PREFECT_DB"])
            if os.environ.get("GRID_SIGNALS_PREFECT_DB")
            else None
        )
        roots = {"data": data, "public": public}
        if db is not None:
            with (
                sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as original,
                sqlite3.connect(directory / "prefect.db") as target,
            ):
                original.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(
                        "Prefect metadata backup failed its integrity check"
                    )
            roots["prefect.db"] = directory / "prefect.db"
        if paths.MLRUNS.exists() and not paths.MLRUNS.resolve().is_relative_to(
            data.resolve()
        ):
            roots["tracking"] = paths.MLRUNS
        checksums = {}
        inodes = {}
        for name, root in roots.items():
            for file in [root] if root.is_file() else sorted(root.rglob("*")):
                if not file.is_file():
                    continue
                if file.is_symlink():
                    raise ValueError("backup inputs must not contain symbolic links")
                stat = file.stat()
                key = (stat.st_dev, stat.st_ino)
                if key not in inodes:
                    inodes[key] = saved_models.digest(file)
                relative = name if file == root else f"{name}/{file.relative_to(root)}"
                checksums[relative] = inodes[key]
        metadata = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "files": checksums,
            "prefect_database_included": db is not None,
        }
        (directory / "backup.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        pending = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with tarfile.open(pending, "w:gz") as archive:
                for name, root in roots.items():
                    archive.add(root, arcname=name)
                archive.add(directory / "backup.json", arcname="backup.json")
            sync_file(pending)
            pending.replace(destination)
            sync_directory(destination.parent)
        finally:
            pending.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "sha256": saved_models.digest(destination),
        "files": len(checksums),
        "prefect_database_included": db is not None,
    }


def restore(archive_path: Path, destination: Path) -> dict:
    """Restore into a new directory and verify every saved file before use."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".restoring-", dir=destination.parent))
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(temporary, filter="data")
        metadata = json.loads((temporary / "backup.json").read_text())
        actual_files = {
            str(file.relative_to(temporary))
            for file in temporary.rglob("*")
            if file.is_file() and file.relative_to(temporary) != Path("backup.json")
        }
        if actual_files != set(metadata["files"]):
            raise ValueError("backup file index does not match restored files")
        for name, checksum in metadata["files"].items():
            file = temporary / name
            if (
                not file.resolve().is_relative_to(temporary.resolve())
                or saved_models.digest(file) != checksum
            ):
                raise ValueError("restored file checksum mismatch")
        if (temporary / "public/current.json").exists():
            live.current(temporary / "public")
        for file in temporary.rglob("*"):
            if file.is_file():
                sync_file(file)
        temporary.rename(destination)
        sync_directory(destination.parent)
        return {"path": str(destination), "verified_files": len(metadata["files"])}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def seed(archive_path: Path, *, destination: Path = paths.DATA) -> dict:
    """Import a checked input backup into an empty producer data volume."""
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("seed requires an empty data directory")
    stage = Path(tempfile.mkdtemp(prefix=".seeding-", dir=destination))
    try:
        checked = stage / "checked"
        restored = restore(archive_path, checked)
        if (checked / "tracking").exists() and (checked / "data/mlruns").exists():
            raise ValueError(
                "backup has two tracking directories; resolve them before seeding"
            )
        for source in (checked / "data").iterdir():
            source.rename(destination / source.name)
        if (checked / "tracking").exists():
            (checked / "tracking").rename(destination / "mlruns")
        record = {
            "seeded_at": datetime.now(UTC).isoformat(),
            "archive_sha256": saved_models.digest(archive_path),
            "verified_files": restored["verified_files"],
            "meaning": "Inputs and historical evidence imported; daily activation is a separate command.",
        }
        from grid_signals.forecast.storage import atomic_json

        atomic_json(destination / "seed.json", record)
        return record
    finally:
        # The original checked archive remains the recovery source if seeding is interrupted.
        if stage.exists():
            shutil.rmtree(stage)
