# ADR-002: Messaging Architecture

**Status:** Accepted
**Date:** 2026-11-26

## Context
AirBreda has two ingestion services (Luchtmeetnet air quality, NDW traffic). On Day 1 each script wrote directly to the database or bucket. Tomorrow's consumers (a database writer, an ML inference service, an anomaly detector) should not have to be wired into the ingestion code. The system is small, runs for about a week, and is built by one person.

## Decision
- Both ingestion services publish each reading as a JSON message to a **Redis list named `readings`** (`RPUSH`), through a shared `publisher.py`.
- Redis runs as a container (`redis:7-alpine`) on the same Docker network as the two services; the services reach it by the hostname `redis`.
- Publishing is optional and non-blocking: if `REDIS_HOST` is not set, or Redis is down, the service logs `queue_publish_failed` and carries on.
- The services still write directly to PostgreSQL and Blob Storage as well, so the queue is not on the critical path for storing data.

## Why a queue instead of direct database writes only
- **Decoupling:** the producer does not know who reads the readings. Adding an ML or anomaly-detection consumer needs no change to the ingestion code.
- **Different rates:** a consumer can be slow or restarted without slowing down ingestion.
- **Extensibility:** the same message can later feed more than one consumer.
- Direct writes alone would be simpler, and are kept for durability, but every new consumer would mean editing the ingestion scripts.

## Why Redis (and not SQS or Service Bus)
- Runs as one container with no cloud setup, so it is the fastest way to build and test the pattern locally and on the VM.
- Cost is zero beyond the VM we already pay for. A managed queue would add a service to provision, secure and pay for.
- For production I would use **Azure Service Bus** (queue ~USD 0.10 per million operations): it has acknowledgements, retries, dead-letter queues and durable storage. A plain Redis list has none of these.

## What happens if the broker goes down
- Redis keeps data in memory only (no persistence is configured), so a Redis restart **loses** the messages that have not been consumed.
- Ingestion keeps running: publish errors are logged as `queue_publish_failed` and the data is still written to PostgreSQL and Blob Storage. No reading is lost for the dashboard or for model training.
- Consumers that rely on the queue would miss messages during the outage. Recovery is to replay the missed period from the database or the bucket.
- Delivery is **at-least-once**: re-running an ingestion adds the same hour again as a duplicate message. Consumers must be idempotent; the database is, because of its primary key.

## Bad data: Luchtmeetnet is flagged and kept, NDW is dropped
- **Luchtmeetnet** null or stale values are stored with `is_flagged = TRUE`. A gap in the hourly NO₂ series is worse for the dashboard and the model than a flagged value, and a stale value is still a real (old) measurement.
- **NDW** `speed = -1` is not a measurement but a sentinel meaning "no valid reading". Storing it would corrupt averages, so it is logged as `DATA_QUALITY_ERROR`, counted, and never written. Valid values from the same site (for example flow) are still written.
- **If I started over**, I would use one rule for both: keep a row and mark it, with the bad value stored as NULL and a flag, never the sentinel. That keeps the gap visible and auditable and still protects the data. The current split exists because the lab asks for it, and it makes NDW gaps harder to see.

## Consequences
- Positive: loose coupling, easy to add consumers, ingestion survives a broker outage.
- Negative: one more container to run, no durability or acknowledgements in a Redis list, duplicates must be handled by consumers.
- Revisit if: a real consumer needs guaranteed delivery. Then move to Azure Service Bus.