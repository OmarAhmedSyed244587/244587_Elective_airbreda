"""Create the sensor_readings table (Day 1, Lab 2). Safe to run more than once."""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()  # reads the PG* settings from your .env file

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    station_id  VARCHAR(20)   NOT NULL,
    timestamp   TIMESTAMPTZ   NOT NULL,
    component   VARCHAR(10)   NOT NULL,
    value       FLOAT,
    PRIMARY KEY (station_id, timestamp, component)
);
"""

conn = psycopg2.connect(
    host=os.environ["PGHOST"],
    port=os.environ.get("PGPORT", "5432"),
    dbname=os.environ.get("PGDATABASE", "postgres"),
    user=os.environ["PGUSER"],
    password=os.environ["PGPASSWORD"],
    sslmode=os.environ.get("PGSSLMODE", "require"),
    connect_timeout=15,
)
with conn, conn.cursor() as cur:
    cur.execute(SCHEMA)
    cur.execute("SELECT COUNT(*) FROM sensor_readings;")
    print("Table ready. Rows currently stored:", cur.fetchone()[0])
conn.close()