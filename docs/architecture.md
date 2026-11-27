# AirBreda architecture (as deployed, 2026-11-28)

```mermaid
flowchart LR
    subgraph EXT["Public data sources (internet)"]
        LM["Luchtmeetnet API<br/>station NL10240, NO2 hourly"]
        NDW["NDW open data feed<br/>4 sites: hrl hrr vwd vwa"]
    end

    USER["Browser / grader"]

    subgraph AZ["Azure: resource group airbreda-rg"]
            subgraph VM["VM airbreda-vm<br/>NSG: 22 and 8000, allowed IPs only"]
            subgraph NET["Docker network airbreda (restart: unless-stopped)"]
                AIR["air-ingest<br/>hourly, /health on 8001"]
                TRF["traffic-ingest<br/>loop every ~10 min, /health on 8002"]
                DASH["dashboard (FastAPI) on 8000<br/>model.pkl baked into the image<br/>predict.py"]
            end
            ENV[".env file, mode 0600<br/>DB password and settings, no keys"]
        end
        MI["System-assigned managed identity<br/>Storage Blob Data Contributor<br/>scope: this one storage account"]
        BLOB[("Blob Storage, container airbreda<br/>raw NDW CSV files, ndw/date/hour-site.csv")]
        PG[("PostgreSQL Flexible Server<br/>table sensor_readings, column is_flagged<br/>firewall: VM IP only")]
    end

    LM -->|HTTPS| AIR
    NDW -->|HTTPS| TRF
    AIR -->|"NO2 rows, stale or null kept with is_flagged"| PG
    TRF -->|"FLOW and SPEED rows, speed -1 dropped and logged"| PG
    TRF -->|"upload CSV, no stored keys"| BLOB
    TRF -.->|"token from"| MI
    MI -.->|"allowed to write"| BLOB
    DASH -->|"read latest NO2 and flow"| PG
    DASH -->|"GET /health"| AIR
    DASH -->|"GET /health"| TRF
    USER -->|"HTTP 8000: /, /site/id, /health"| DASH
    ENV -.-> AIR
    ENV -.-> TRF
    ENV -.-> DASH
```

## Where the model lives and how the dashboard uses it

`model.pkl` is trained offline (`build_training_data.py`, then `train_model.py`) and copied into the
dashboard's Docker image at build time. At runtime `dashboard.py` imports `predict.py`, which loads
the file once. For each `/site/{id}` request the dashboard reads the latest NO2 and the latest flow
of all four sites from PostgreSQL, calls `predict(total_flow, hour_of_day)` and returns the
predicted NO2 and the exceedance risk. Retraining means rebuilding the image (ADR-006).

## Trust boundaries (who can access what)

| Principal | Can reach | How it is controlled |
|---|---|---|
| Anyone on the internet | Only port 8000 on the VM (dashboard, read-only) | NSG rule `allow-dashboard`; nothing else is exposed |
| Me (administration) | SSH port 22 on the VM | NSG rule `default-allow-ssh`, limited to my IP |
| VM managed identity | Blob container `airbreda` (read and write) and nothing else in Azure | Role Storage Blob Data Contributor, scoped to the one storage account; no keys on the VM |
| Containers on the VM | PostgreSQL | Password in `.env` (mode 0600, not in Git or the image); the server firewall allows the VM's IP only |
| Dashboard container | PostgreSQL (read) and the two `/health` endpoints | Same `.env`; it does not use Blob Storage |

Known limits: the managed identity belongs to the whole VM, so the dashboard container could in
principle use it too, even though it never does; and the database password is a shared secret in a
file. Per-container identities and a secret store (for example Key Vault) are the production fix.

Note: Redis (a queue between ingestion and storage, ADR-002) runs only in the local Compose setup
for testing. It is not part of the deployed system, where the ingestion containers write directly
to PostgreSQL.