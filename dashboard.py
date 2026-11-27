"""
dashboard.py - AirBreda API and dashboard (FastAPI).

Routes
  GET /site/{site_id}  JSON for one of hrl, hrr, vwd, vwa
  GET /health          both ingestion services' health, aggregated
  GET /                HTML page built on /site/{id} (it only calls our own API)

Where each field of /site/{site_id} comes from (required comment)
-----------------------------------------------------------------
  site_id                      the URL path, validated against SITES
  no2_ug_m3                    sensor_readings: latest non-null NO2 for station
                               NL10240 (one real station serves all four sites)
  no2_timestamp                that reading's timestamp (UTC)
  intensity_veh_per_hr         sensor_readings: latest FLOW for station NDW_<site>
                               (written by ingest_traffic.py every 5 minutes)
  timestamp                    timestamp of that traffic reading (UTC)
  total_intensity_veh_per_hr   sum of the latest FLOW of all four sites. The
                               model was trained on this total, so it is also
                               what predict() receives (avoids training-serving
                               skew; passing a single site would be 4x too low)
  no2_ug_m3_predicted,         predict.predict(total, hour_of_day) from predict.py
  no2_exceedance_risk          (hour_of_day = Amsterdam local hour, as in training)
  no2_age_minutes,             how old the two readings are, so the page can
  traffic_age_minutes          show "stale" instead of looking current

If predict() raises (or fewer than four sites have data, which would not match
the training features), the route does NOT fail: it still returns the real NO2
and traffic values, with the prediction fields set to null and
"prediction_error": true. Real measurements are worth more to the user than a
500 error, and the failure is logged as an ERROR event. If the DATABASE cannot
be read there is nothing real to show, so that case returns 503.
"""

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

load_dotenv()

import db
import jsonlog
import predict

log = logging.getLogger("dashboard")
jsonlog.setup()

SITES = ["hrl", "hrr", "vwd", "vwa"]
STATION = "NL10240"
CACHE_SECONDS = 30  # one database read serves all four /site calls and page refreshes
AIR_HEALTH_URL = os.environ.get("AIR_HEALTH_URL", "http://air-ingest:8001/health")
TRAFFIC_HEALTH_URL = os.environ.get("TRAFFIC_HEALTH_URL", "http://traffic-ingest:8002/health")

app = FastAPI(title="AirBreda")
_cache = {"at": 0.0, "data": None}


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_minutes(moment):
    return round((datetime.now(timezone.utc) - moment).total_seconds() / 60, 1)


def load_snapshot():
    """Latest NO2 reading and latest flow per site, cached for CACHE_SECONDS."""
    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT timestamp, value FROM sensor_readings "
            "WHERE station_id = %s AND component = 'NO2' AND value IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1",
            (STATION,),
        )
        row = cur.fetchone()
        no2 = {"timestamp": row[0], "value": float(row[1])} if row else None

        cur.execute(
            "SELECT DISTINCT ON (station_id) station_id, timestamp, value "
            "FROM sensor_readings WHERE component = 'FLOW' AND station_id LIKE 'NDW_%' "
            "ORDER BY station_id, timestamp DESC"
        )
        traffic = {
            station_id.replace("NDW_", ""): {"timestamp": ts, "value": float(value)}
            for station_id, ts, value in cur.fetchall()
        }

    data = {"no2": no2, "traffic": traffic}
    _cache.update(at=now, data=data)
    return data


@app.get("/site/{site_id}")
def site(site_id: str):
    if site_id not in SITES:
        raise HTTPException(status_code=404, detail=f"unknown site, use one of {SITES}")
    try:
        snap = load_snapshot()
    except Exception as exc:
        jsonlog.event(log, logging.ERROR, "db_read_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="database unavailable")

    no2, mine = snap["no2"], snap["traffic"].get(site_id)
    if no2 is None or mine is None:
        raise HTTPException(status_code=503, detail="no data yet for this site")

    total = sum(v["value"] for v in snap["traffic"].values())
    response = {
        "site_id": site_id,
        "no2_ug_m3": no2["value"],
        "no2_timestamp": iso(no2["timestamp"]),
        "no2_age_minutes": age_minutes(no2["timestamp"]),
        "intensity_veh_per_hr": mine["value"],
        "timestamp": iso(mine["timestamp"]),
        "traffic_age_minutes": age_minutes(mine["timestamp"]),
        "total_intensity_veh_per_hr": total,
        "no2_ug_m3_predicted": None,
        "no2_exceedance_risk": None,
        "prediction_error": False,
    }
    try:
        if len(snap["traffic"]) < len(SITES):
            raise ValueError("fewer than four sites have data")
        hour = mine["timestamp"].astimezone(ZoneInfo("Europe/Amsterdam")).hour
        result = predict.predict(total, hour)
        response.update(result)
    except Exception as exc:  # degrade: keep the real values, drop the prediction
        response["prediction_error"] = True
        jsonlog.event(log, logging.ERROR, "predict_failed", site=site_id, error=str(exc))
    return response


HEALTH_TIMEOUT = 5          # seconds; the small VM can be slow while it parses NDW
HEALTH_GRACE_SECONDS = 300  # on a one-off failure, reuse the last good answer this long
_health_cache = {}


def fetch_health(name, url):
    """Ask one ingestion container for its /health.

    One failed call (timeout, DNS blip) is retried once; if it still fails we fall
    back to the last good answer when it is under HEALTH_GRACE_SECONDS old, marked
    with stale_seconds. Beyond that the container is treated as really down.
    """
    last_error = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT) as reply:
                data = json.loads(reply.read())
            _health_cache[name] = (time.time(), data)
            return data
        except Exception as exc:
            last_error = exc
    jsonlog.event(log, logging.WARNING, "health_fetch_failed", source=name, error=str(last_error))
    cached = _health_cache.get(name)
    if cached and time.time() - cached[0] < HEALTH_GRACE_SECONDS:
        return {**cached[1], "stale_seconds": round(time.time() - cached[0])}
    return {"error": str(last_error)}


@app.get("/health")
def health():
    air = fetch_health("luchtmeetnet", AIR_HEALTH_URL)
    traffic = fetch_health("ndw", TRAFFIC_HEALTH_URL)
    ok = "error" not in air and "error" not in traffic
    return {"status": "ok" if ok else "degraded", "luchtmeetnet": air, "ndw": traffic}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AirBreda</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 820px; margin: 0 auto; padding: 16px; }
  h1 { margin-bottom: 4px; }
  .sub { color: #666; margin-top: 0; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
  .card { flex: 1 1 200px; border: 1px solid #ccc; border-radius: 8px; padding: 12px; }
  .big { font-size: 1.8rem; font-weight: 600; }
  .label { color: #666; font-size: 0.85rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
  .warn { color: #b00020; font-weight: 600; }
  .ok { color: #1b7f3b; }
</style>
</head>
<body>
<h1>AirBreda</h1>
<p class="sub">NO&#8322; and traffic at the A27 / Breda interchange</p>

<div class="cards">
  <div class="card"><div class="label">Actual NO&#8322; (station NL10240)</div><div class="big" id="no2">...</div></div>
  <div class="card"><div class="label">Total traffic (4 sites)</div><div class="big" id="total">...</div></div>
</div>

<table>
  <thead><tr><th>Site</th><th>Traffic (veh/h)</th><th>Predicted NO&#8322;</th><th>Exceedance risk</th></tr></thead>
  <tbody id="rows"></tbody>
</table>

<p id="updated" class="label"></p>
<p class="label">The prediction comes from a linear regression trained on very little data; treat it as a demo.</p>

<script>
const SITES = ["hrl", "hrr", "vwd", "vwa"];

async function load() {
  const data = await Promise.all(SITES.map(s =>
    fetch("/site/" + s).then(r => (r.ok ? r.json() : null)).catch(() => null)));
  const good = data.filter(d => d);
  const rows = document.getElementById("rows");
  rows.textContent = "";

  SITES.forEach((s, i) => {
    const d = data[i];
    const tr = document.createElement("tr");
    const cells = d
      ? [s, Math.round(d.intensity_veh_per_hr),
         d.no2_ug_m3_predicted === null ? "n/a" : d.no2_ug_m3_predicted.toFixed(1) + " \\u00b5g/m\\u00b3",
         d.no2_exceedance_risk === null ? "n/a" : Math.round(d.no2_exceedance_risk * 100) + "%"]
      : [s, "no data", "", ""];
    cells.forEach(c => { const td = document.createElement("td"); td.textContent = c; tr.appendChild(td); });
    rows.appendChild(tr);
  });

  const upd = document.getElementById("updated");
  if (!good.length) {
    document.getElementById("no2").textContent = "no data";
    document.getElementById("total").textContent = "no data";
    upd.textContent = "No data available.";
    upd.className = "label warn";
    return;
  }
  const first = good[0];
  document.getElementById("no2").textContent = first.no2_ug_m3.toFixed(1) + " \\u00b5g/m\\u00b3";
  document.getElementById("total").textContent = Math.round(first.total_intensity_veh_per_hr) + " veh/h";

  const staleNo2 = first.no2_age_minutes > 180;       // air data is hourly
  const staleTraffic = first.traffic_age_minutes > 30; // a full cycle takes ~10-15 min on this small VM
  upd.textContent = "NO2 measured " + first.no2_timestamp + " (" + Math.round(first.no2_age_minutes) + " min ago), " +
    "traffic measured " + first.timestamp + " (" + Math.round(first.traffic_age_minutes) + " min ago)" +
    (staleNo2 || staleTraffic ? " - DATA IS STALE: an ingestion service may have stopped." : "");
  upd.className = "label " + (staleNo2 || staleTraffic ? "warn" : "ok");
}

load();
setInterval(load, 60000);  // refresh every minute, no redeploy needed
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE