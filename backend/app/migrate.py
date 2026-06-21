"""Apply schema patches for columns added after initial deploy."""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _json_type(engine: Engine) -> str:
    return "JSONB" if engine.dialect.name == "postgresql" else "JSON"


def apply_migrations(engine: Engine) -> None:
    insp = inspect(engine)
    dialect = engine.dialect.name

    patches = [
        ("site_scans", "dmca_site_data", _json_type(engine)),
        ("site_scans", "scan_options", _json_type(engine)),
        ("copyright_checks", "dmca_evidence", _json_type(engine)),
        ("site_scans", "user_id", "INTEGER"),
    ]

    with engine.begin() as conn:
        for table, column, col_type in patches:
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            if dialect == "postgresql":
                ddl = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
            else:
                ddl = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}'
            logger.info("migration: %s.%s", table, column)
            conn.execute(text(ddl))

        if dialect == "postgresql":
            _fix_pg_sequences(conn)


def _fix_pg_sequences(conn) -> None:
    """Resync serial sequences after manual imports or failed transactions."""
    tables = ("users", "site_scans", "pages", "images", "copyright_checks", "exif_data")
    for table in tables:
        conn.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
        )
        logger.info("migration: sequence synced for %s", table)
