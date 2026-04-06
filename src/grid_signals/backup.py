"""DuckDB backup: checkpoint and upload to S3."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def backup_database(
    db_path: Path,
    s3_bucket: str,
    prefix: str = "grid-signals/backups",
) -> str:
    """Checkpoint the DB and upload to S3 with a date-stamped key.

    Returns the S3 URI of the uploaded backup.
    """
    # Checkpoint to flush WAL to main DB file
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        con.execute("CHECKPOINT")
    finally:
        con.close()

    today = datetime.now(tz=UTC).date().isoformat()
    s3_uri = f"s3://{s3_bucket}/{prefix}/{today}.duckdb"

    logger.info("Uploading backup to %s", s3_uri)
    subprocess.run(  # noqa: S603
        ["aws", "s3", "cp", str(db_path), s3_uri],
        check=True,
    )
    logger.info("Backup complete: %s", s3_uri)
    return s3_uri
