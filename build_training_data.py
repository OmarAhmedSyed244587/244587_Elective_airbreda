"""
build_training_data.py - join NO2 and traffic into one training table.

NO2 comes from sensor_readings (station NL10240, component NO2). Traffic comes
from sensor_readings too: ingest_traffic.py stores each site's total flow as
component FLOW for station NDW_<site> about every 5 minutes. Both are rounded
down to the hour; the traffic samples inside an hour are averaged, which gives
vehicles per hour for that hour.

Output: training_data.csv with
  hour, no2_ug_m3, hrl, hrr, vwd, vwa, total_intensity_veh_per_hr, hour_of_day
"""

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

import db

STATION = "NL10240"
SITES = ["hrl", "hrr", "vwd", "vwa"]
MIN_SAMPLES = 3  # a site-hour needs at least this many 5-minute samples to count


def query(sql, columns):
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=columns)


def load_no2():
    df = query(
        "SELECT timestamp, value FROM sensor_readings "
        "WHERE station_id = %s AND component = 'NO2' AND value IS NOT NULL".replace("%s", f"'{STATION}'"),
        ["timestamp", "no2_ug_m3"],
    )
    df["hour"] = pd.to_datetime(df["timestamp"], utc=True).dt.floor("h")
    return df.groupby("hour", as_index=False)["no2_ug_m3"].mean()


def load_traffic():
    df = query(
        "SELECT station_id, timestamp, value FROM sensor_readings "
        "WHERE component = 'FLOW' AND station_id LIKE 'NDW_%'",
        ["station_id", "timestamp", "flow"],
    )
    df["site"] = df["station_id"].str.replace("NDW_", "", regex=False)
    df["hour"] = pd.to_datetime(df["timestamp"], utc=True).dt.floor("h")
    hourly = df.groupby(["hour", "site"]).agg(flow=("flow", "mean"), samples=("flow", "size")).reset_index()
    hourly = hourly[hourly["samples"] >= MIN_SAMPLES]
    wide = hourly.pivot(index="hour", columns="site", values="flow")
    wide = wide.reindex(columns=SITES).dropna()  # all four sites must be present
    return wide.reset_index()


def main():
    no2 = load_no2()
    traffic = load_traffic()
    print(f"NO2 hours: {len(no2)}   traffic hours (all 4 sites): {len(traffic)}")

    data = no2.merge(traffic, on="hour", how="inner").sort_values("hour")
    data["total_intensity_veh_per_hr"] = data[SITES].sum(axis=1)
    # Rush hour follows the local clock, so use Amsterdam time for hour_of_day.
    data["hour_of_day"] = data["hour"].dt.tz_convert("Europe/Amsterdam").dt.hour

    data.to_csv("training_data.csv", index=False)
    print(f"Joined rows: {len(data)}  ->  training_data.csv")
    print(data[["hour", "no2_ug_m3", "total_intensity_veh_per_hr", "hour_of_day"]].to_string(index=False))


if __name__ == "__main__":
    main()