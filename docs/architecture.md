# AirBreda Architecture (Day 1)

```mermaid
flowchart LR
    subgraph Sources["External data sources"]
        LM["Luchtmeetnet API<br/>station NL10240<br/>hourly NO2"]
        NDW["NDW DATEX II feed<br/>4 A27 sites<br/>flow and speed"]
    end

    subgraph Ingest["Ingestion (Python)"]
        IA["ingest_air.py<br/>retry and backoff,<br/>keeps NULLs"]
        IT["ingest_traffic.py<br/>speed = -1 handled,<br/>dq_status"]
    end

    subgraph Azure["Azure (North Europe)"]
        DB[("PostgreSQL Flexible Server<br/>sensor_readings<br/>PK: station, timestamp, component")]
        BLOB[("Blob Storage<br/>container airbreda<br/>ndw/YYYY-MM-DD/HH-site.csv")]
    end

    LM --> IA
    NDW --> IT
    IA -->|"INSERT ... ON CONFLICT DO NOTHING"| DB
    IT -->|"raw and parsed CSV"| BLOB

    DB -.->|"Day 3-4: dashboard, API, model"| APP["FastAPI service<br/>GET /, /site/id, /health"]
    BLOB -.->|"Day 4: training data"| APP
```

## Components
- **Luchtmeetnet API**: public RIVM API, no key, hourly readings, can return null values.
- **NDW feed**: gzip-compressed DATEX II XML, one measurement per lane.
- **PostgreSQL**: structured readings, idempotent writes, time-range queries.
- **Blob Storage**: durable raw record, cheap, allows re-parsing later.
- **Dashed lines**: planned for Days 3 and 4.