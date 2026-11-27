# ADR-005: Compute & Deployment Strategy (Day 4)

- **Status:** Accepted. Extends ADR-004 (does not supersede it).
- **Date:** 2026-11-27

## Context

ADR-004 put the two ingestion containers (`air-ingest`, `traffic-ingest`) on one small Azure VM
(Standard_B2ts_v2, Sweden Central, 886 MB RAM) and ran them with Docker. Day 4 adds a third
piece: the dashboard and API (`dashboard`, FastAPI + the trained model). It must be reachable
from the internet on port 8000, read from the same database, and report on the health of both
ingestion containers.

Facts measured on the real VM (not assumptions):

| Container | Memory in use |
|---|---|
| `dashboard` | about 54 MiB |
| `air-ingest` | about 9 MiB |
| `traffic-ingest` | about 331 MiB (parses the large NDW XML files) |

- Before the dashboard was added, only about 89 MB of RAM was available and 793 MB of swap was in use.
- A full `traffic-ingest` cycle takes about 10-12 minutes, not the designed 5, because the VM swaps
  while parsing NDW.
- Cost is bounded by the budget alert (EUR 40/month) set on Day 3.

## Decision

Run the dashboard as a **third container on the same VM**, next to the two ingestion containers,
instead of moving to a managed container service.

- **How it runs:** `docker run -d --restart unless-stopped --network airbreda -p 8000:8000`.
  Docker starts at boot, and the restart policy brings the container back after a crash or reboot.
  No systemd unit is needed for this.
- **Networking:** a user-defined Docker network `airbreda` connects all three containers, so the
  dashboard can reach `air-ingest:8001` and `traffic-ingest:8002` by name for `/health`.
- **Memory:** a second 2 GB swap file was added (4 GB total, both in `/etc/fstab`).
- **Secrets:** the image contains no secrets. `.env` is excluded by `.dockerignore`, and the
  database and storage settings are supplied at run time with `--env-file`. The VM authenticates to
  Blob Storage with its managed identity (Storage Blob Data Contributor, scoped to the one storage
  account).
- **Deploying a change:** `git pull`, `docker build`, `docker rm -f dashboard`, `docker run ...`.
  There is about 10 seconds of downtime per deploy.
- **Access:** NSG port 8000 is open to my own IP while building. It will be opened wider for the
  assessment because the endpoints are read-only and expose no credentials.

### What testing locally with Compose caught

- A YAML indentation mistake that nested `dashboard` inside `traffic-ingest`. This was cheap to
  fix on the laptop.
- That `/health` depends on a shared network so the containers can find each other by name. On the
  VM the ingestion containers had been started with plain `docker run`, so I had to create the
  `airbreda` network and connect them to it.
- Compose did **not** catch the real risks: the VM's small memory and slow, occasionally failing
  name lookups. A laptop has plenty of RAM, so those only showed up on the VM. Compose tests the
  logic and the wiring, not the resource limits.

### Reboot test (done, not assumed)

I ran `sudo reboot` on the VM. After about one minute all three containers were running again
without any action from me, both swap files were active, and the dashboard could still reach the
ingestion containers.

## Alternatives considered

- **Managed container service (e.g. Azure Container Apps):** rolling deploys, autoscaling and no OS
  to patch. Rejected for now: it costs more at this size, and one corridor with three small
  containers does not need it.
- **Bigger VM:** the most likely first upgrade, because memory is the actual bottleneck. Not
  needed to meet the Day 5 requirements.

## Consequences

- **Good:** one machine to understand, cheap, simple deploys, and the reboot behaviour is verified.
  The dashboard is tiny (54 MiB), so adding it was safe once swap was added.
- **Bad:** a single VM is a single point of failure, with no failover and a short outage on every
  deploy. The VM is undersized for NDW parsing, so the traffic data is older than designed (the
  dashboard's staleness warning was set to 30 minutes to match the observed cycle time). Swap hides
  the memory problem instead of fixing it.
- **Changed from ADR-004:** a third container, a shared Docker network, 4 GB of swap instead of 2 GB,
  and an internet-facing port. The compute choice itself (one VM, Docker, restart policy) is unchanged.
- **What would change my mind:**
  - If AirBreda grows to about 10 corridors, or `traffic-ingest` cannot finish a cycle within its
    polling interval even on a bigger VM, I would first move to a larger VM (4 GB), then to a
    managed container service.
  - Needing zero-downtime deploys, several people deploying, or an availability target above the
    99.5% SLO from ADR-003 would also push me to a managed service.
  - The cheapest fix to try first: parse each NDW file once per cycle instead of once per site.