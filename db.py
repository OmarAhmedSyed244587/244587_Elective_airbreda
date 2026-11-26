"""
db.py - write readings to PostgreSQL idempotently.

Connection settings come from environment variables (never hard-code them,
the repo is public): PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE.
"""

import os

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    station_id  VARCHAR(20)   NOT NULL,
    timestamp   TIMESTAMPTZ   NOT NULL,
    component   VARCHAR(10)   NOT NULL,
    value       FLOAT,
    PRIMARY KEY (station_id, timestamp, component)
);
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE;
"""

# Duplicates are harmless: the same (station, hour, component) is simply skipped.
INSERT = """
INSERT INTO sensor_readings (station_id, timestamp, component, value, is_flagged)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;
"""


def rows_from_dataframe(df, station_id):
    """DataFrame (component, value, timestamp[, is_flagged]) -> list of tuples.

    NaN becomes NULL. Rows are never dropped here: a flagged row is still
    stored, with is_flagged = TRUE.
    """
    rows = []
    for rec in df.itertuples(index=False):
        value = None if rec.value != rec.value else float(rec.value)  # NaN != NaN
        flagged = bool(getattr(rec, "is_flagged", False))
        rows.append((station_id, rec.timestamp.to_pydatetime(), rec.component, value, flagged))
    return rows


def connect():
    import psycopg2  # imported lazily so tests do not need it

    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        sslmode=os.environ.get("PGSSLMODE", "require"),
        connect_timeout=15,
    )


def save_readings(rows):
    """Insert rows; returns how many were actually new."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        new = 0
        for row in rows:
            cur.execute(INSERT, row)
            new += cur.rowcount if cur.rowcount > 0 else 0
        return new