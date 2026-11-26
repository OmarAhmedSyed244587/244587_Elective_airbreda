"""db.py - write air-quality readings to PostgreSQL idempotently."""

import os

import psycopg2

INSERT = """
INSERT INTO sensor_readings (station_id, timestamp, component, value)
VALUES (%s, %s, %s, %s)
ON CONFLICT DO NOTHING;
"""


def rows_from_dataframe(df, station_id):
    """DataFrame (component, value, timestamp) -> list of tuples. NaN becomes NULL."""
    rows = []
    for rec in df.itertuples(index=False):
        value = None if rec.value != rec.value else float(rec.value)  # NaN != NaN
        rows.append((station_id, rec.timestamp.to_pydatetime(), rec.component, value))
    return rows


def save_readings(rows):
    """Insert rows. Returns how many were new (duplicates are skipped)."""
    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        sslmode=os.environ.get("PGSSLMODE", "require"),
        connect_timeout=15,
    )
    new = 0
    with conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(INSERT, row)
            new += max(cur.rowcount, 0)
    conn.close()
    return new