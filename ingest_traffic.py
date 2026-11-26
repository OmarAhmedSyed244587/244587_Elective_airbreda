"""
ingest_traffic.py - pull live NDW traffic data for the four A27 sites near
Breda (hrl, hrr, vwd, vwa), clean it, save one CSV per site, and optionally
upload the files to cloud object storage (Azure Blob).

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
"""

import csv
import io
import logging
import os
import sys
from datetime import timezone
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from helper_scripts import getTrafficReadings as ndw

load_dotenv()

log = logging.getLogger("ingest_traffic")

SITES = {
    "hrl": "RWS01_MONIBAS_0271hrl0063ra",
    "hrr": "RWS01_MONIBAS_0271hrr0063ra",
    "vwd": "RWS01_MONIBAS_0270vwd0063ra",
    "vwa": "RWS01_MONIBAS_0270vwa0063ra",
}

OUTPUT_DIR = Path(os.environ.get("NDW_OUTPUT_DIR", "data/ndw"))
CSV_FIELDS = ["site", "timestamp", "total_flow", "avg_speed", "lanes", "bad_speed_lanes", "dq_status"]


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
    """Upload to Azure Blob Storage if configured; otherwise skip quietly."""
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        log.info("No AZURE_STORAGE_CONNECTION_STRING set - skipping upload of %s", path)
        return False
    from azure.storage.blob import BlobServiceClient  # imported lazily

    container = os.environ.get("AZURE_STORAGE_CONTAINER", "airbreda")
    blob_name = "ndw/" + path.relative_to(base).as_posix()
    client = BlobServiceClient.from_connection_string(conn).get_blob_client(container, blob_name)
    with open(path, "rb") as fh:
        client.upload_blob(fh, overwrite=True)
    log.info("Uploaded %s", blob_name)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config_bytes = ndw.download_and_decompress(ndw.CONFIG_URL).read()
        measured_bytes = ndw.download_and_decompress(ndw.MEASURED_URL).read()
    except Exception as exc:  # network, gzip or HTTP problems
        log.error("NDW download failed: %s", exc)
        return 1

    failures = 0
    for label, site_id in SITES.items():
        index_map = ndw.build_index_map(io.BytesIO(config_bytes), site_id)
        readings = ndw.extract_measurements(io.BytesIO(measured_bytes), site_id)
        row = summarise_site(label, index_map, readings)
        if row["timestamp"] is None:
            log.error("No data for site %s (%s)", label, site_id)
            failures += 1
            continue
        if row["dq_status"] != "ok":
            log.warning("Site %s data quality: %s (bad speed lanes: %d)",
                        label, row["dq_status"], row["bad_speed_lanes"])
        path = output_path(label, row["timestamp"])
        write_csv(path, row)
        append_history(row)
        log.info("Saved %s", path)
        upload_to_blob(path)
    return 1 if failures == len(SITES) else 0


if __name__ == "__main__":
    sys.exit(main())