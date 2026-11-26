# ADR-001: Initial Data Storage Strategy

**Status:** Accepted
**Date:** 2026-11-26

## Context
AirBreda collects two live open-data streams for the A27 interchange near Breda: hourly NO₂ (and other pollutant) readings from Luchtmeetnet station NL10240, and per-minute vehicle flow and speed from four NDW sites (hrl, hrr, vwd, vwa). The data must support (a) fast time-range queries and joins between air quality and traffic for the dashboard and model, and (b) a durable record of the raw data so the model can be retrained later.

## Decision
- Store parsed readings in a **managed relational database (Azure Database for PostgreSQL Flexible Server)**.
- Store raw and parsed files in **cloud object storage (Azure Blob Storage)**, laid out as `ndw/YYYY-MM-DD/HH-<site>.csv`.
- Make writes **idempotent**: primary key `(station_id, timestamp, component)` with `INSERT ... ON CONFLICT DO NOTHING`.

## Why a relational database instead of NoSQL
- The readings are highly structured: (station, timestamp, component, value).
- The main access pattern is time-range queries per station, which SQL indexes handle well.
- Correlating NO₂ with traffic needs a join, which is awkward in most NoSQL stores.
- Volume is tiny (roughly 10⁵ rows per year), so NoSQL's scaling advantage buys nothing here.

## Why raw files go in object storage
- It is cheap, durable and append-only, so it works as an audit trail.
- It keeps detail the database does not (for example per-lane values), so the model can be retrained later with different features by re-parsing the old files.
- A database cannot hold raw feeds as cheaply, and a bucket cannot answer indexed queries, so the two complement each other.

## How duplicates are handled
Delivery is at-least-once: a retry or re-run may fetch the same hour again. Because the primary key is `(station_id, timestamp, component)` and inserts use `ON CONFLICT DO NOTHING`, a duplicate reading is skipped, so re-running the script never creates duplicate rows (verified: first run stored 50 rows, second run stored 0). Exactly-once delivery would be over-engineering for this workload.

## Bad and missing data
- Null NO₂ values are kept as NULL, never dropped or replaced by 0.
- NDW `speed = -1` means "no valid measurement": it is excluded from averages and flagged in a `dq_status` column.

## Alternative considered and rejected
**Azure Cosmos DB / DynamoDB (key-value NoSQL).** Rejected: the workload is small and relational, we need joins and range queries, and the scaling benefit does not apply.

## Consequences
- Positive: simple, queryable, cheap, easy to explain.
- Negative: a managed PostgreSQL server costs money even when idle; schema changes need migrations.
- Revisit if: we grow to many stations and need much higher write throughput.

## Reflection
The decision I am least confident defending is using a managed PostgreSQL server for this data volume. It is simple to query, but it is billed while idle, and for roughly 10⁵ rows a year a much cheaper option such as SQLite on the VM could be enough. I chose it because the course expects a managed database and it makes the later cloud steps more realistic, but a reviewer could fairly ask whether the cost is justified.