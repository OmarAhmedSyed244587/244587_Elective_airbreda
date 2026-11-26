"""
ingest_air.py - fetch live air-quality readings for RIVM Luchtmeetnet station
NL10240 (Breda-Tilburgseweg), keep only NO2, and print the most recent value.

Builds on get_latest_no2() from helper_scripts/getNO2readings.py.
No API key required. Fair use limit: 100 requests / 5 minutes.

CAP trade-off (required comment)
--------------------------------
The sensor network behaves like an AP system (Availability + Partition
tolerance). When a station loses connectivity the API still answers, but the
hour may be missing, null, or carry a stale value from the last successful
measurement. We get a response (available) but not necessarily the latest
truth (not consistent).

Production handling of a missing/null value:
  * Never silently drop it: keep the row with value = NULL so the gap is
    visible and auditable (the unit test checks this).
  * Never fill it with 0 - that would look like perfectly clean air.
  * Flag it (is_flagged = TRUE) and log a DATA_QUALITY_ERROR warning, so the
    dashboard / model can show "data stale" instead of a wrong number.
  * Downstream, impute or skip nulls explicitly when training the model.
"""

import logging
import os
import sys
import time

import pandas as pd
import requests

from dotenv import load_dotenv
load_dotenv()  # reads PG* settings from .env so the database write switches on

import jsonlog

STATION = "NL10240"
BASE_URL = f"https://api.luchtmeetnet.nl/open_api/stations/{STATION}/measurements"

REQUEST_TIMEOUT = 10  # seconds
MAX_RETRIES = 3
BACKOFF_SECONDS = 2  # waits 2s, then 4s between attempts
STALE_RUN = 3  # same value for this many consecutive hours = stale

# Polling interval (required comment): Luchtmeetnet publishes one value per
# station per HOUR, so we poll once an hour. Polling every minute would not
# give fresher data; it would fetch the same hour 60 times, push 60 duplicate
# messages onto the queue, waste free-API quota (fair use is 100 requests per
# 5 minutes) and risk being rate-limited, for zero extra information.

log = logging.getLogger("ingest_air")

# In-memory counter of bad readings seen by this process (read by /health).
luchtmeetnet_bad_data_count = 0


class AirDataError(Exception):
    """Raised when the Luchtmeetnet API cannot be reached after all retries."""


def fetch_measurements(station: str = STATION, page: int = 1) -> list[dict]:
    """Return one page of raw measurement records (all pollutants).

    Retries on timeouts, connection problems and HTTP errors. Raises
    AirDataError if every attempt fails, so the caller decides what to do.
    """
    url = f"https://api.luchtmeetnet.nl/open_api/stations/{station}/measurements"
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params={"page": page}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json().get("data", [])
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            jsonlog.event(log, logging.WARNING, "fetch_retry", source="Luchtmeetnet",
                          attempt=attempt, max_attempts=MAX_RETRIES, error=str(exc))
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)

    raise AirDataError(f"Luchtmeetnet unreachable after {MAX_RETRIES} attempts: {last_error}")


def to_dataframe(records: list[dict]) -> pd.DataFrame:
    """Raw API records -> DataFrame with columns: component, value, timestamp.

    The API calls the pollutant 'formula' and the time 'timestamp_measured';
    we rename them. Timestamps are kept in UTC.
    """
    columns = ["component", "value", "timestamp"]
    if not records:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(records).rename(
        columns={"formula": "component", "timestamp_measured": "timestamp"}
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # bad values -> NaN
    return df[columns]


def flag_stale_or_null(df: pd.DataFrame, min_run: int = STALE_RUN) -> pd.DataFrame:
    """Add an is_flagged column. Nothing is dropped.

    A row is flagged if its value is null, or if the same value repeats for
    min_run or more consecutive hourly timestamps of the same pollutant.
    """
    df = df.copy()
    if df.empty:
        df["is_flagged"] = pd.Series(dtype=bool)
        return df

    df = df.sort_values(["component", "timestamp"]).reset_index(drop=True)
    run_id = df.groupby("component")["value"].transform(lambda s: s.ne(s.shift()).cumsum())
    run_size = df.groupby(["component", run_id])["value"].transform("size")
    df["is_flagged"] = df["value"].isna() | (run_size >= min_run)
    return df


def report_data_quality(df: pd.DataFrame) -> int:
    """Log a DATA_QUALITY_ERROR warning for each flagged NO2 row and count it."""
    global luchtmeetnet_bad_data_count
    flagged = df[(df["component"] == "NO2") & (df["is_flagged"])]
    for row in flagged.itertuples():
        luchtmeetnet_bad_data_count += 1
        jsonlog.event(log, logging.WARNING, "DATA_QUALITY_ERROR", source="Luchtmeetnet",
                      station_id=STATION, field="NO2", reason="stale_or_null",
                      value=None if pd.isna(row.value) else float(row.value),
                      timestamp=row.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return len(flagged)


def filter_no2_readings(df: pd.DataFrame) -> pd.DataFrame:
    """Keep NO2 rows only. Rows with a null value are KEPT, not dropped."""
    return df[df["component"] == "NO2"].copy()


def to_messages(df: pd.DataFrame, station: str = STATION) -> list[dict]:
    """NO2 rows -> JSON-ready queue messages. Null values stay null."""
    messages = []
    for row in df.itertuples():
        messages.append(
            {
                "station_id": station,
                "timestamp": row.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "component": row.component,
                "value": None if pd.isna(row.value) else float(row.value),
            }
        )
    return messages


def latest_reading(df: pd.DataFrame) -> pd.Series | None:
    """Most recent row by timestamp (may have a null value), or None if empty."""
    if df.empty:
        return None
    return df.sort_values("timestamp").iloc[-1]


def latest_valid_reading(df: pd.DataFrame) -> pd.Series | None:
    """Most recent row that actually has a value, or None."""
    return latest_reading(df.dropna(subset=["value"]))


def main() -> int:
    jsonlog.setup()

    try:
        records = fetch_measurements()
    except AirDataError as exc:
        jsonlog.event(log, logging.ERROR, "fetch_failed", source="Luchtmeetnet", error=str(exc))
        return 1

    readings = flag_stale_or_null(to_dataframe(records))
    no2 = filter_no2_readings(readings)
    newest = latest_reading(no2)
    if newest is None:
        jsonlog.event(log, logging.ERROR, "no_no2_readings", source="Luchtmeetnet", station_id=STATION)
        return 1

    jsonlog.event(log, logging.INFO, "fetch_success", source="Luchtmeetnet",
                  station_id=STATION,
                  value=None if pd.isna(newest["value"]) else float(newest["value"]),
                  timestamp=newest["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"))

    report_data_quality(no2)

    # Lab 2: if a database is configured, store ALL pollutants idempotently
    # (ON CONFLICT DO NOTHING means running twice never creates duplicates).
    # Flagged rows are STORED with is_flagged = TRUE, never dropped: a gap in
    # the time series is worse than a flagged stale value.
    if os.environ.get("PGHOST"):
        import db

        try:
            new_rows = db.save_readings(db.rows_from_dataframe(readings, STATION))
            jsonlog.event(log, logging.INFO, "db_write", rows_new=new_rows)
        except Exception as exc:  # keep printing the reading even if the DB is down
            jsonlog.event(log, logging.ERROR, "db_write_failed", error=str(exc))

    # Day 2: publish the NO2 readings to the Redis queue as well.
    if os.environ.get("REDIS_HOST"):
        import publisher

        try:
            sent = publisher.publish(to_messages(no2))
            jsonlog.event(log, logging.INFO, "queue_publish", source="Luchtmeetnet", messages=sent)
        except Exception as exc:  # the queue being down must not stop ingestion
            jsonlog.event(log, logging.ERROR, "queue_publish_failed", error=str(exc))

    print(f"Station:   {STATION}")
    print(f"Component: NO2")
    print(f"Timestamp: {newest['timestamp']} (UTC)")
    if pd.isna(newest["value"]):
        valid = latest_valid_reading(no2)
        print("Value:     MISSING (null) in the latest hour")
        if valid is not None:
            print(f"Last valid: {valid['value']} ug/m3 at {valid['timestamp']} (UTC)")
        return 0

    print(f"Value:     {newest['value']} ug/m3")
    return 0


if __name__ == "__main__":
    sys.exit(main())