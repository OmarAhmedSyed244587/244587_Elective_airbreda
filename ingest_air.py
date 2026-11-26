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
  * Report the latest *valid* reading separately and flag how old it is, so
    the dashboard / model can show "data stale" instead of a wrong number.
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

STATION = "NL10240"
BASE_URL = f"https://api.luchtmeetnet.nl/open_api/stations/{STATION}/measurements"

REQUEST_TIMEOUT = 10  # seconds
MAX_RETRIES = 3
BACKOFF_SECONDS = 2  # waits 2s, then 4s between attempts

# Polling interval (required comment): Luchtmeetnet publishes one value per
# station per HOUR, so we poll once an hour. Polling every minute would not
# give fresher data; it would fetch the same hour 60 times, push 60 duplicate
# messages onto the queue, waste free-API quota (fair use is 100 requests per
# 5 minutes) and risk being rate-limited, for zero extra information.

log = logging.getLogger("ingest_air")


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
            log.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        records = fetch_measurements()
    except AirDataError as exc:
        log.error("%s", exc)
        return 1

    no2 = filter_no2_readings(to_dataframe(records))
    newest = latest_reading(no2)
    if newest is None:
        log.error("No NO2 readings in the API response for station %s", STATION)
        return 1

    # Lab 2: if a database is configured, store ALL pollutants idempotently
    # (ON CONFLICT DO NOTHING means running twice never creates duplicates).
    if os.environ.get("PGHOST"):
        import db

        try:
            new_rows = db.save_readings(db.rows_from_dataframe(to_dataframe(records), STATION))
            log.info("Database: %d new rows stored", new_rows)
        except Exception as exc:  # keep printing the reading even if the DB is down
            log.error("Database write failed: %s", exc)
            
    # Day 2: publish the NO2 readings to the Redis queue as well.
    if os.environ.get("REDIS_HOST"):
        import publisher

        try:
            sent = publisher.publish(to_messages(no2))
            log.info("Queue: %d messages published", sent)
        except Exception as exc:  # the queue being down must not stop ingestion
            log.error("Queue publish failed: %s", exc)

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