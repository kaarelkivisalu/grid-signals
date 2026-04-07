"""PostgreSQL backup: pg_dump and upload to S3."""

from __future__ import annotations

import logging
import subprocess  # noqa: S404
import tempfile
from datetime import UTC, datetime

from grid_signals.config import get_database_url

logger = logging.getLogger(__name__)


def backup_database(
    dsn: str | None = None,
    *,
    s3_bucket: str,
    prefix: str = "grid-signals/backups",
) -> str:
    """Dump the database and upload to S3 with a date-stamped key.

    Returns the S3 URI of the uploaded backup.
    """
    if dsn is None:
        dsn = get_database_url()

    today = datetime.now(tz=UTC).date().isoformat()
    s3_uri = f"s3://{s3_bucket}/{prefix}/{today}.sql.gz"

    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=True) as tmp:
        dump_path = tmp.name

    logger.info("Dumping database to %s", dump_path)
    subprocess.run(  # noqa: S603
        ["pg_dump", "--format=custom", "-f", dump_path, dsn],
        check=True,
    )

    logger.info("Uploading backup to %s", s3_uri)
    subprocess.run(  # noqa: S603
        ["aws", "s3", "cp", dump_path, s3_uri],
        check=True,
    )
    logger.info("Backup complete: %s", s3_uri)
    return s3_uri
