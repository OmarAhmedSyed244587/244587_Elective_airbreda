# AirBreda Architecture (after Day 2)

```mermaid
flowchart LR
    subgraph Sources["External data sources"]
        LM["Luchtmeetnet API<br/>NL10240, hourly"]
        NDW["NDW DATEX II feed<br/>4 A27 sites, per minute"]
    end

    subgraph Compose["Docker Compose network: airbreda"]
        IA["air-ingest<br/>polls hourly<br/>GET /health :8001"]
        IT["traffic-ingest<br/>polls every 5 min<br/>GET /health :8002"]
        RQ[("Redis list<br/>readings")]
        DQA{"Data quality<br/>air: null or stale?"}
        DQT{"Data quality<br/>NDW: speed = -1?"}
    end

    subgraph Azure["Azure North Europe"]
        DB[("PostgreSQL<br/>sensor_readings<br/>is_flagged")]
        BLOB[("Blob Storage<br/>ndw/YYYY-MM-DD/HH-site.csv")]
    end

    LOGS["stdout: JSON logs<br/>INFO fetch_success<br/>WARNING DATA_QUALITY_ERROR<br/>ERROR BAD_DATA_THRESHOLD_EXCEEDED"]

    LM --> IA
    NDW --> IT

    IA --> DQA
    DQA -->|"ok"| DB
    DQA -->|"flag is_flagged = TRUE, keep row"| DB

    IT --> DQT
    DQT -->|"valid values"| DB
    DQT -->|"bad speed: warn, count, skip SPEED row"| LOGS
    IT -->|"raw and parsed CSV"| BLOB

    IA -->|"RPUSH JSON message"| RQ
    IT -->|"RPUSH JSON message"| RQ

    IA -.-> LOGS
    IT -.-> LOGS

    RQ -.->|"Day 3-4: consumers"| APP["FastAPI service<br/>GET /, /site/id, /health"]
    DB -.->|"Day 3-4"| APP
```

## Paths
- **Queue path:** both ingestion services publish every reading as JSON to the Redis list `readings`. Nothing consumes it yet. If Redis is down, ingestion logs the error and continues (ADR-002).
- **Logging path:** each service writes one JSON object per line to stdout (`fetch_success`, `DATA_QUALITY_ERROR`, `BAD_DATA_THRESHOLD_EXCEEDED`, ...). A monitoring tool added on Day 4 or 5 can filter on the `event` field.
- **Data quality path:** Luchtmeetnet null or stale readings are stored with `is_flagged = TRUE` (kept). NDW `speed = -1` is warned about, counted in `ndw_bad_data_count`, and never written to the database (dropped).
- **Health:** each service exposes `GET /health` with `last_successful_fetch`, `bad_data_count` and `source`.
- **Dashed lines:** planned for Days 3 and 4.