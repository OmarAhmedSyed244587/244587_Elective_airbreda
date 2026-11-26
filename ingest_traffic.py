"""
ingest_traffic.py - pull live NDW traffic data for the four A27 sites near
Breda (hrl, hrr, vwd, vwa), clean it, save one CSV per site, store it in the
database and optionally upload the files to cloud object storage (Azure Blob).

File layout (the timestamp comes from the DATA, not from today's clock):
    data/ndw/YYYY-MM-DD/HH-hrl.csv   (UTC date and hour of the measurement)

Why both a database AND a bucket (required comment)
---------------------------------------------------
* The bucket keeps the files exactly as received: cheap, durable and
  append-only. It is our audit trail. Six months from now, when we want to
  retrain the model with a better feature (say, speed per lane instead of an
  average), the database no longer has the detail we threw away. The bucket
  does: we re-parse the old files and rebuild the training set.
* The database keeps the parsed, structured readings with a primary key and
  indexes: fast time-range queries and joins (NO2 vs traffic) for the
  dashboard and the model. A bucket cannot do indexed queries or joins, and it
  cannot reject duplicates.
* Bucket = history and reprocessing. Database = fast serving and analysis.

Bad data (NDW)
--------------
NDW reports speed = -1 when a detector has no valid measurement. Unlike the
Luchtmeetnet air readings (flagged and kept), a bad NDW speed is DROPPED: a
sentinel value must never reach sensor_readings, because a -1 would silently
wreck averages and the model. We log a DATA_QUALITY_ERROR warning, count it in
ndw_bad_data_count, and write only the values that are valid.
"""

import csv
import io
import logging
import os
import sys
import time
from datetime import timezone
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from helper_scripts import getTrafficReadings as ndw

load_dotenv()

import health
import jsonlog

log = logging.getLogger("ingest_traffic")

SITES = {
    "hrl": "RWS01_MONIBAS_0271hrl0063ra",
    "hrr": "RWS01_MONIBAS_0271hrr0063ra",
    "vwd": "RWS01_MONIBAS_0270vwd0063ra",
    "vwa": "RWS01_MONIBAS_0270vwa0063ra",
}

OUTPUT_DIR = Path(os.environ.get("NDW_OUTPUT_DIR", "data/ndw"))
CSV_FIELDS = ["site", "timestamp", "total_flow", "avg_speed", "lanes", "bad_speed_lanes", "dq_status"]

# Polling interval (required comment): the NDW feed refreshes about once a
# minute, but the model predicts hourly NO2, so polling every ~5 minutes is
# plenty. Polling every minute would push 5x more messages with almost
# identical values, fill the queue and the history file faster, and hit the
# NDW server far more often than the data justifies.

# In-memory counter of bad readings seen by this process (read by /health).
ndw_bad_data_count = 0
HEALTH = health.SourceHealth("NDW", lambda: ndw_bad_data_count)
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "300"))  # every 5 minutes, see the polling comment above


def clean_speed(raw):
    """Bad data handler for NDW speed values.

    NDW reports speed = -1 when a detector has no valid measurement. It is NOT
    a real speed, so it must never enter an average. Returns a float, or None
    if the value is missing or invalid.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def summarise_site(label, index_map, readings):
    """Combine per-lane readings into one summary row for the site."""
    flow_idx = {i for i, info in index_map.items()
                if info["type"] == "trafficFlow" and info["vehicle"] == "anyVehicle"}
    speed_idx = {i for i, info in index_map.items()
                 if info["type"] == "trafficSpeed" and info["vehicle"] == "anyVehicle"}

    flows = []
    for r in readings:
        if r["index"] in flow_idx:
            try:
                value = float(r["value"])
            except (TypeError, ValueError):
                continue
            if value >= 0:
                flows.append(value)

    speeds, bad = [], 0
    for r in readings:
        if r["index"] in speed_idx:
            cleaned = clean_speed(r["value"])
            if cleaned is None:
                bad += 1
            else:
                speeds.append(cleaned)

    timestamp = readings[0].get("timestamp") if readings else None
    if not readings or timestamp is None:
        status = "no_data"
    elif bad:
        status = "partial_speed" if speeds else "no_valid_speed"
    else:
        status = "ok"

    return {
        "site": label,
        "timestamp": timestamp,
        "total_flow": sum(flows) if flows else None,
        "avg_speed": sum(speeds) / len(speeds) if speeds else None,
        "lanes": len(flow_idx),
        "bad_speed_lanes": bad,
        "dq_status": status,
    }


def report_bad_speed(row, site_id):
    """Log a DATA_QUALITY_ERROR warning and count it if any lane had no valid speed."""
    global ndw_bad_data_count
    if not row["bad_speed_lanes"]:
        return False
    ndw_bad_data_count += 1
    HEALTH.record_bad()
    jsonlog.event(log, logging.WARNING, "DATA_QUALITY_ERROR", source="NDW",
                  location=site_id, field="speed", value=-1,
                  bad_lanes=row["bad_speed_lanes"], dq_status=row["dq_status"])
    return True


def to_db_rows(row):
    """Summary row -> sensor_readings tuples (station, time, component, value, flagged).

    A missing speed produces NO SPEED row, so a -1 can never be stored.
    """
    when = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    station = f"NDW_{row['site']}"
    rows = []
    if row["total_flow"] is not None:
        rows.append((station, when, "FLOW", float(row["total_flow"]), False))
    if row["avg_speed"] is not None:
        rows.append((station, when, "SPEED", float(row["avg_speed"]), False))
    return rows


def output_path(label, timestamp, base=OUTPUT_DIR):
    """data/ndw/YYYY-MM-DD/HH-label.csv from the measurement timestamp (UTC)."""
    when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return Path(base) / when.strftime("%Y-%m-%d") / f"{when.strftime('%H')}-{label}.csv"


def write_csv(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def append_history(row, history=None):
    """Append every reading to one growing CSV.

    The per-hour files are overwritten by later runs within the same hour (the
    feed updates every minute), so this history file keeps the minute-level
    readings for training the Day 4 model.
    """
    history = Path(history or OUTPUT_DIR.parent / "traffic_history.csv")
    history.parent.mkdir(parents=True, exist_ok=True)
    new_file = not history.exists()
    with open(history, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def upload_to_blob(path, base=OUTPUT_DIR):
    """Upload to Azure Blob Storage if configured; otherwise skip quietly.

    Two ways to authenticate, no secret needed on the VM:
      * AZURE_STORAGE_ACCOUNT_URL: use the VM's managed identity (production).
      * AZURE_STORAGE_CONNECTION_STRING: a key, only for running on a laptop.
    """
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not conn and not account_url:
        jsonlog.event(log, logging.INFO, "blob_upload_skipped", path=str(path))
        return False
    from azure.storage.blob import BlobServiceClient  # imported lazily

    if conn:
        service = BlobServiceClient.from_connection_string(conn)
    else:
        from azure.identity import DefaultAzureCredential

        service = BlobServiceClient(account_url, credential=DefaultAzureCredential())

    container = os.environ.get("AZURE_STORAGE_CONTAINER", "airbreda")
    blob_name = "ndw/" + path.relative_to(base).as_posix()
    client = service.get_blob_client(container, blob_name)
    with open(path, "rb") as fh:
        client.upload_blob(fh, overwrite=True)
    jsonlog.event(log, logging.INFO, "blob_uploaded", blob=blob_name)
    return True


def main():
    jsonlog.setup()
    try:
        config_bytes = ndw.download_and_decompress(ndw.CONFIG_URL).read()
        measured_bytes = ndw.download_and_decompress(ndw.MEASURED_URL).read()
    except Exception as exc:  # network, gzip or HTTP problems
        jsonlog.event(log, logging.ERROR, "fetch_failed", source="NDW", error=str(exc))
        return 1

    HEALTH.fetch_ok()
    failures = 0
    for label, site_id in SITES.items():
        index_map = ndw.build_index_map(io.BytesIO(config_bytes), site_id)
        readings = ndw.extract_measurements(io.BytesIO(measured_bytes), site_id)
        row = summarise_site(label, index_map, readings)
        if row["timestamp"] is None:
            jsonlog.event(log, logging.ERROR, "no_data_for_site", source="NDW",
                          site=label, location=site_id)
            failures += 1
            continue

        jsonlog.event(log, logging.INFO, "fetch_success", source="NDW", site=label,
                      location=site_id, total_flow=row["total_flow"],
                      avg_speed=row["avg_speed"], timestamp=row["timestamp"])
        report_bad_speed(row, site_id)

        path = output_path(label, row["timestamp"])
        write_csv(path, row)
        append_history(row)

        # Store only valid values: a missing speed produces no SPEED row.
        if os.environ.get("PGHOST"):
            import db

            try:
                new_rows = db.save_readings(to_db_rows(row))
                jsonlog.event(log, logging.INFO, "db_write", site=label, rows_new=new_rows)
            except Exception as exc:  # the database being down must not stop ingestion
                jsonlog.event(log, logging.ERROR, "db_write_failed", site=label, error=str(exc))

        # Day 2: publish one message per site to the Redis queue (off unless REDIS_HOST is set).
        if os.environ.get("REDIS_HOST"):
            import publisher

            try:
                publisher.publish([{
                    "station_id": site_id,
                    "site": label,
                    "source": "NDW",
                    "timestamp": row["timestamp"],
                    "total_flow": row["total_flow"],
                    "avg_speed": row["avg_speed"],
                    "dq_status": row["dq_status"],
                }])
                jsonlog.event(log, logging.INFO, "queue_publish", source="NDW", site=label)
            except Exception as exc:  # the queue being down must not stop ingestion
                jsonlog.event(log, logging.ERROR, "queue_publish_failed", site=label, error=str(exc))

        try:
            upload_to_blob(path)
        except Exception as exc:  # blob storage being down must not stop ingestion
            jsonlog.event(log, logging.ERROR, "blob_upload_failed", site=label, error=str(exc))
    return 1 if failures == len(SITES) else 0


def run_forever():
    """Service mode: serve /health and repeat the job every POLL_SECONDS."""
    jsonlog.setup()
    health.serve(HEALTH, int(os.environ.get("HEALTH_PORT", "8002")))
    while True:
        try:
            main()
        except Exception as exc:  # one bad run must never kill the service
            jsonlog.event(log, logging.ERROR, "run_failed", source="NDW", error=str(exc))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        run_forever()
    else:
        sys.exit(main())