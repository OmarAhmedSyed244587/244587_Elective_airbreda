# AirBreda Architecture (after Day 3)

```mermaid
flowchart LR
    subgraph Sources["External data sources"]
        LM["Luchtmeetnet API<br/>NL10240"]
        NDW["NDW DATEX II feed<br/>4 A27 sites"]
    end

    subgraph VM["Azure VM airbreda-vm (Ubuntu, 1 GB, Sweden Central)"]
        IA["air-ingest container<br/>hourly, /health"]
        IT["traffic-ingest container<br/>every 5 min, /health"]
        ENV[".env on the VM<br/>DB password only"]
        MI["System-assigned<br/>managed identity"]
    end

    subgraph Azure["Azure data services"]
        DB[("PostgreSQL Flexible Server<br/>sensor_readings<br/>firewall: VM IP + my IP")]
        BLOB[("Blob Storage<br/>container airbreda")]
        RBAC["Role: Storage Blob<br/>Data Contributor"]
    end

    ME["Me (laptop)"]

    LM -->|"HTTPS"| IA
    NDW -->|"HTTPS"| IT
    IA -->|"PostgreSQL over TLS, port 5432"| DB
    IT -->|"PostgreSQL over TLS, port 5432"| DB
    IT -->|"HTTPS, uses identity token"| BLOB
    ENV -.-> IA
    ENV -.-> IT
    MI -.->|"gets token"| IT
    MI --- RBAC
    RBAC -.->|"allows write"| BLOB
    ME -->|"SSH 22, my IP only"| VM

    REDIS["Redis queue (Day 2)<br/>NOT part of this deployment"]
    IA -.-x|"off: REDIS_HOST not set"| REDIS
    IT -.-x|"off: REDIS_HOST not set"| REDIS
```

## What runs where
- **VM:** two containers, started with `--restart unless-stopped`. Each loops on its own timer and serves `/health` inside the VM (no public port).
- **VM to database:** PostgreSQL over TLS on port 5432. The database firewall allows only the VM's public IP and my own IP.
- **VM to object storage:** HTTPS using a token from the VM's managed identity. The identity has the `Storage Blob Data Contributor` role on this one storage account. No key is stored on the VM.
- **Day 2 queue:** not part of this deployment. Ingestion writes directly to the database and bucket; the Redis code stays in the repo but is switched off.
- **Access:** SSH only from my current IP; the database password is the only secret on the VM (`.env`, mode 600).