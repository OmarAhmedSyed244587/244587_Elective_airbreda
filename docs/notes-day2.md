# Day 2 notes: Architecture Patterns, Resilience & Observability

## Reflection: shared codebase or two services?
Right now AirBreda has two separate services (air and traffic) that live in one repo and share a few small modules (`db.py`, `publisher.py`, `jsonlog.py`, `health.py`). I think that is the right split. The two sources fail differently (NDW goes down more often than Luchtmeetnet), they poll at different intervals (every hour vs every 5 minutes), and I can restart or fix one without touching the other. Keeping one repo keeps things simple for a team of one: one test run, one `docker compose up`, no versioning between repos. I would not split further into more services.

What would change my answer in 12 months:
- If a second person or team owned the traffic side, a separate repo and release cycle would make sense.
- If one source needed to scale much more than the other (many more stations), I would deploy and scale it on its own.
- If I added many more sources, a shared ingestion framework or separate services per source would be worth it.
- If the two services always had to change together, I would merge them back, because the split would only add overhead.

## Reflection: acceptable downtime and SLO
AirBreda is an air quality dashboard. The source data only updates hourly and nobody's safety depends on a minute-level answer, so a few hours of downtime a month is acceptable. My SLO for `GET /site/{id}` is **99.5% availability per month** (non-5xx responses) with **p95 latency under 500 ms**. That gives an error budget of about 216 minutes (3.6 hours) per month. A 4-hour outage would be slightly over one month's budget, which I accept for this use case. See ADR-003.

## Day 2 wrap-up

### 1. Seven microservices: three questions I would ask
1. **What problem does each split solve?** Does any of them need to scale, deploy or fail independently, or belong to a different team? If the answer is "no, it just looks cleaner", the split only adds cost.
2. **Who will run, monitor and debug seven services?** Every service needs its own deployment, logs, health checks and alerts. For a team of one, the operational overhead and the cost of seven containers or VMs is much bigger than the benefit.
3. **What happens when one of them is slow or down?** How do they talk to each other (queue or direct calls), what do the retries and timeouts look like, and what do we do about versioning and data that has to stay consistent across services? A failure in one place can now cascade into the others.

### 2. `bad_data_count = 47` in the last hour
- **Check first:** whether it is one source, one site or everything. I would filter the JSON logs on `DATA_QUALITY_ERROR` and group by `source`, `location` and `reason`. I would also check `/health` (`last_successful_fetch`) and look at the source itself (Luchtmeetnet or NDW site) to see whether the problem is upstream or in my code (for example a changed field name or a parsing bug).
- **What I alert on:** not each warning, but the rate. `BAD_DATA_THRESHOLD_EXCEEDED` (more than 10 per hour) already triggers an alert. I would also alert if `last_successful_fetch` is older than two polling intervals, because that means the service stopped fetching.
- **What may reach the database:** valid values only. Luchtmeetnet nulls and stale values may be stored, but flagged (`is_flagged = TRUE`). NDW `speed = -1` must never be stored. If all 47 come from one dead sensor, I can keep the service running and let the dashboard show that site as stale. If everything is bad, I would investigate before trusting any new data for training.

### 3. 99.5% SLO and the December 2021 AWS outage
- Error budget per month: 0.5% of 30 days = 0.005 x 43,200 minutes = **216 minutes (3.6 hours)**.
- Error budget per year: 0.5% of 8,760 hours = **43.8 hours**.
- A 5-hour (300 minute) outage would use 300 / 216 = **139% of that month's budget**, so the month's SLO is broken by about 84 minutes.
- Against the whole year it would burn 5 / 43.8 = **about 11.4%** of the annual budget in one event.
- With a single-region Backup & Restore setup (ADR-003) I would simply be down for that time, which is why a regional outage is the one thing I accept as a risk.