"""
Data quality tests (Day 2, Lab 2).

No real database is needed: test 1 swaps db.connect for a fake connection that
records every INSERT, so we can check exactly what would be written.
"""

import db
import ingest_air
import ingest_traffic


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if params is not None:  # only INSERTs carry parameters
            self.store.append(params)


class FakeConnection:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.store)


def test_stale_or_null_luchtmeetnet_reading_is_written_flagged(monkeypatch):
    """A null and a stale (3 equal hours) reading are stored with is_flagged = TRUE."""
    written = []
    monkeypatch.setattr(db, "connect", lambda: FakeConnection(written))

    records = [
        {"formula": "NO2", "value": None, "timestamp_measured": "2026-11-26T10:00:00+00:00"},
        {"formula": "NO2", "value": 20.0, "timestamp_measured": "2026-11-26T11:00:00+00:00"},
        {"formula": "NO2", "value": 20.0, "timestamp_measured": "2026-11-26T12:00:00+00:00"},
        {"formula": "NO2", "value": 20.0, "timestamp_measured": "2026-11-26T13:00:00+00:00"},
        {"formula": "NO2", "value": 15.0, "timestamp_measured": "2026-11-26T14:00:00+00:00"},
    ]
    df = ingest_air.flag_stale_or_null(ingest_air.to_dataframe(records))
    db.save_readings(db.rows_from_dataframe(df, "NL10240"))

    assert len(written) == 5  # nothing was dropped
    flagged_by_hour = {params[1].hour: params[4] for params in written}
    assert flagged_by_hour == {10: True, 11: True, 12: True, 13: True, 14: False}


def test_ndw_speed_minus_one_is_not_written_and_is_counted():
    """speed = -1 never reaches the database and increments ndw_bad_data_count."""
    index_map = {
        0: {"type": "trafficFlow", "vehicle": "anyVehicle"},
        1: {"type": "trafficSpeed", "vehicle": "anyVehicle"},
    }
    readings = [
        {"index": 0, "value": "120", "timestamp": "2026-11-26T13:16:00Z"},
        {"index": 1, "value": "-1", "timestamp": "2026-11-26T13:16:00Z"},
    ]
    row = ingest_traffic.summarise_site("hrl", index_map, readings)
    before = ingest_traffic.ndw_bad_data_count

    assert ingest_traffic.report_bad_speed(row, "RWS01_MONIBAS_0271hrl0063ra") is True
    assert ingest_traffic.ndw_bad_data_count == before + 1

    db_rows = ingest_traffic.to_db_rows(row)
    assert all(r[2] != "SPEED" for r in db_rows)  # no speed row at all
    assert all(r[3] != -1 for r in db_rows)  # the sentinel is never stored