# ADR-003: Resilience Strategy

**Status:** Accepted
**Date:** 2026-11-26

## Context
AirBreda is an air-quality dashboard and API for a single location (Breda). Nobody's safety or money depends on a minute-by-minute answer, and the system is built and run by one person on limited cloud credit. The Day 2 case study (AWS us-east-1, December 2021) shows that a whole region can be unavailable for hours, and that tightly coupled services fail together. The question is how much reliability is worth paying for here.

## Decision

### SLO for `GET /site/{id}`
- **Availability SLO: 99.5% per calendar month**, measured as the share of requests answered with a non-5xx status.
- **Latency SLO:** p95 response time under 500 ms.
- **Error budget:** 0.5% of a 30-day month = about **216 minutes (3.6 hours)** of allowed downtime per month.
- Why 99.5%: air quality changes slowly (the source publishes hourly), so a few hours of downtime a month is acceptable. 99.9% would leave only 43 minutes a month, which a single VM cannot realistically promise. 99% would be so loose that it would hide real problems.

### Disaster recovery tier: Backup & Restore
- PostgreSQL Flexible Server keeps **automated backups** (point-in-time restore).
- Raw files live in **Blob Storage**, which is already a durable copy of the data.
- All code, Dockerfiles and `docker-compose.yml` are in GitHub, so the VM can be rebuilt from scratch.
- **Targets:** RTO of a few hours (create a new VM, `docker compose up`, restore the database if needed); RPO of at most one hour for the database (one polling cycle of data can be re-fetched from the sources or replayed from the blob files).

### Why not a higher tier
- The error budget (3.6 hours a month) already tolerates a one-off recovery of a few hours.
- The data is open data that can be fetched again, so losing an hour costs little.
- A warm standby would cost more per month than the whole system's compute.

## Cost difference to the next tier up (approximate, check the Azure pricing calculator)
| Tier | What runs all the time | Extra cost per month |
|------|------------------------|----------------------|
| **Backup & Restore (chosen)** | nothing extra; backups and blobs are included or cost cents | ~ USD 0 |
| Pilot Light | a second, minimal PostgreSQL replica (Burstable B1ms, ~USD 17) plus a stored VM image | ~ USD 17-20 |
| Warm Standby | a small second VM running the containers plus the database replica | ~ USD 25-35 |

Moving from Backup & Restore to Pilot Light roughly doubles the database cost for a faster recovery that this use case does not need.

## Consequences
- Positive: cheapest option, simple, easy to explain; fits inside the SLO budget.
- Negative: recovery is manual and takes hours; a regional outage like December 2021 (about 5 hours) would use up more than one month's error budget.
- Single region (North Europe): a region failure takes the system down. This is accepted.
- Revisit if: the dashboard becomes something people rely on (for example for health advice), or the SLO moves to 99.9%.