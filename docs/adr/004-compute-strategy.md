# ADR-004: Compute Strategy

**Status:** Accepted
**Date:** 2026-11-26

## Context
The two ingestion services must run continuously, 24/7, not on a laptop. AirBreda is small: one station, four traffic sites, one VM's worth of work, one developer, and a limited credit budget. The service needs to survive crashes and reboots, write to a managed PostgreSQL database, and write raw files to object storage without secrets stored on the machine.

## Decision
- Run both services as **Docker containers on one Azure Linux VM** (Ubuntu 24.04, `Standard_B2ts_v2`, 1 GB RAM, 30 GB disk, Sweden Central).
- The containers are built from the repo on the VM and started with `--restart unless-stopped`; each service loops on its own timer (air hourly, traffic every 5 minutes) and exposes `/health`.
- The VM authenticates to Blob Storage with a **system-assigned managed identity** (role `Storage Blob Data Contributor` on the storage account only). No storage key is on the VM.
- The database password is in a `.env` file on the VM (permissions `600`, never in git).
- SSH is allowed only from my own IP. The database firewall allows only the VM's IP and my own IP.
- A 2 GB swap file was added so the NDW parsing does not exhaust the 1 GB of RAM.

## Why a VM instead of a managed container service
- It is the simplest thing that works for two small always-on containers, and the course asks to build on IaaS first so I understand what the platform normally hides (OS, Docker, networking, identity).
- A managed container service would hide the OS but adds concepts (environments, ingress, scaling rules) that this workload does not need.
- Cost is low and predictable: one small VM.

## What it costs per month (approximate; check the Azure pricing calculator)
| Item | Per month |
|------|-----------|
| VM `Standard_B2ts_v2` | ~ USD 8 |
| 30 GB standard SSD | ~ USD 2-3 |
| Static public IP | ~ USD 3-4 |
| PostgreSQL Burstable B1ms (from ADR-000) | ~ USD 17 |
| Blob Storage (tiny) | < USD 1 |
| **Total** | **~ USD 30-35** |

## What I would switch to at 50 corridors and 5-minute ingestion
- Ingestion as **scheduled container jobs** (Azure Container Apps jobs, or Kubernetes CronJobs once there are many) so each corridor runs and scales independently and a failure of one does not block the rest.
- Bring back a **managed queue (Azure Service Bus)** between ingestion and the database writer, so bursts do not overload the database.
- A larger database or a time-series extension (TimescaleDB) and connection pooling.
- Real monitoring and alerting instead of reading container logs by hand.

## One operational concern I had not anticipated
**Memory.** The traffic container was killed by the kernel (`OOMKilled`, exit code 137) and restarted 376 times with no error message in the logs, because parsing the NDW files needs more than the VM's free RAM. It only showed up on the small VM, not on my laptop. I found it with `docker inspect` and fixed it with swap. A better long-term fix is to parse the NDW XML as a stream instead of loading it all. Two smaller surprises: the cheap `Standard_B1s` size was unavailable in every region I tried, and SSH locked me out when my laptop's IP changed.

## Why the Redis queue from ADR-002 was dropped for this deployment
With one VM, hourly (and 5-minute) ingestion and no second consumer, a broker is another thing to run, monitor and keep alive without any benefit: both services already write straight to the database and bucket. The queue code is still in the repo and switches on only when `REDIS_HOST` is set. It comes back when (a) a second consumer needs the readings (an ML inference service, an anomaly detector), or (b) ingestion outgrows a single VM and needs buffering between producers and the database.

## Consequences
- Positive: simple, cheap, no secrets for storage, easy to explain, survives reboots.
- Negative: single point of failure (one VM, one region), manual updates and patching, small memory headroom, I operate the OS myself.
- Revisit if: the load grows, a second consumer appears, or the VM needs to be rebuilt often.