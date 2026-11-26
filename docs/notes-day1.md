# Day 1 notes

## Lab 1: Luchtmeetnet API (station NL10240, Breda-Tilburgseweg)
1. **Fields per record:** value, timestamp_measured, formula, timestamp_measured_start, timestamp_measured_end
2. **Time resolution:** hourly. Each record covers one hour, and the station reports NO, NO2, NOx, PM10 and PM25.
3. **Unmeasured formula:** the API does not return an error. It returns an empty `data` list with `last_page: 0`, so the code has to check for an empty list.
4. **How recent:** the latest reading (NO2 17.96 µg/m³, 09:00 UTC = 10:00 Amsterdam) was almost an hour old when I ran the script at about 10:53.

## Reading 1: How Zalando moved to AWS (CNCF, 2018)
- In 2015, Zalando began moving its infrastructure from on-premises data centers to AWS to support its growth.
- The old on-premises setup was the same for every team, so autonomous teams were not possible there.
- No lift and shift: applications were reworked for the cloud, including their persistence layers. Docker provided a common way to package applications.
- More than 200 teams chose their own technologies and ran applications in separate AWS accounts. This gave ownership but made compliance harder.
- Compliance checks detected problems after they were introduced, so teams had to resolve violations. Spinning up EC2 instances was also slow.
- Zalando delayed orchestration at first, then began moving to Kubernetes in 2016 (with training on CI/CD, concepts and APIs, and weekly check-ins).
- Kubernetes is a container orchestration platform, not a PaaS. The article mentions about 40 clusters in the text and 140+ in the summary box (2018), and cluster autoscaling mattered.
- The Kubernetes API let Zalando run applications in a cloud provider-agnostic way.
- Results: stack wait time went from 10-15 minutes to seconds, with 3,000+ production deployments per week.
- **Takeaway:** the first product moved was business-critical and took longer than expected, and the article suggests starting with something less critical. Rewriting applications and organizational change are disruptive, so don't copy the approach wholesale.

## Reading 2: Cost saving strategies for large enterprise cloud migrations (AWS blog, 2023)
- Migration can cause unplanned costs. The AWS MAP approach has three steps: Assess, Mobilize, Migrate.
- **Assess:** check readiness, inventory current assets and licences, and avoid the "double-bubble cost" (paying for the old and new environments at once).
- **Mobilize:** build a landing zone and a Cloud Center of Excellence, and plan migration waves.
- **Migrate:** move workloads quickly to keep double-bubble costs low. Start with one simple application, then add complex ones in later waves. Modernization should start alongside migrating.
- This is partly a vendor's view, since most of the tools named are AWS programs.

## Reflection: engineer at Zalando in 2016
**Concern:** compliance. Freedom to choose my own tools sounds great, until violations are only found after I have built and pushed something, so I would have to fix it afterwards. Nothing stops the mistake up front, so I'd lose time and the compliance team would be overloaded too.
**Excitement:** speed. With Kubernetes, a stack comes up in seconds instead of the 10 to 15 minutes it took on plain AWS, which would let teams deploy much more often.

## CAP theorem

### Reading: CAP theorem (IBM)
- A distributed system can deliver only two of three characteristics: consistency, availability and partition tolerance. It's like "cheap, fast, good: pick two".
- A distributed system stores data on more than one node, and all cloud applications are distributed systems.
- Consistency: all clients see the same data at the same time, whichever node they connect to.
- Availability: every request gets a response, even if some nodes are down.
- Partition tolerance: the system keeps working when communication between nodes breaks.
- Partitions cannot be avoided in a distributed system, so the real choice is CP or AP.
- CP (e.g. MongoDB): consistent, but nodes may become unavailable during a partition.
- AP (e.g. Cassandra): always available, but nodes may return older data. Eventual consistency repairs this afterwards.
- IBM says a CA distributed database can't exist in practice, but a relational database such as PostgreSQL gives consistency and availability on a single node or with replication.
- Use an AP database when you can tolerate eventual consistency. Use a relational database when consistency matters (payments, e-commerce).

### Reading: Please stop calling databases CP or AP (Kleppmann, 2015)
- The CAP theorem is too simplistic and too widely misunderstood to be used to label systems.
- CAP uses very narrow definitions: consistency means linearizability (not the C in ACID), availability means every non-failing node must respond, and partition tolerance just means the network can delay or drop messages.
- Linearizability: if operation B starts after operation A completed, B must see A's result or something newer. His example is Alice and Bob checking the World Cup score, where Bob's lagging replica shows an old result.
- The theorem only covers a single read-write register and only one fault (a network partition). It says nothing about crashes, full disks, bugs or latency.
- Many systems are neither CAP-consistent nor CAP-available, for example single-leader replication and PostgreSQL. Cassandra depends on its settings (R, W, N), and ZooKeeper is neither by default.
- Labelling a system CP or AP is a false dichotomy: one product can have operations with different consistency levels, and the label loses all the subtlety.
- Even Brewer admits CAP is oversimplified. It was meant to start a discussion, not to classify systems.
- **Takeaway:** don't just say "CP" or "AP". State what happens to reads and writes in a failure, and think through the trade-offs for your own system.

### My CAP answers
1. **C, A and P in my own words:**
   - Consistency: everyone gets the same, most recent data, whichever copy they ask.
   - Availability: every request gets an answer, not an error, even if some parts are broken.
   - Partition tolerance: the system keeps working even when the connection between its parts breaks.
2. **Why P cannot be avoided:** networks fail in real life (cables, overload, outages), so any system spread over several machines has to cope with it. Since partitions will happen, the real choice is what to give up while one lasts: consistency or availability.
3. **How this applies to the Luchtmeetnet sensor data:** when a sensor station loses its connection, the API still answers, but the latest hour may be missing (null) or an old value. The API favours availability over being up to date, so it behaves like an AP-style system. My pipeline must therefore never treat a response as automatically correct: it keeps a null as NULL (not 0) and flags values that look stale. Kleppmann's point is that "AP" is too crude a label, so I describe exactly what happens instead of only using the label.

## Cloud pricing and FinOps

### Reading: Amazon EC2 pricing
- On-Demand: pay by the hour or second, with no upfront payment or long-term commitment.
- Savings Plans: up to 72% off in exchange for a usage commitment.
- Spot Instances: spare capacity at up to 90% off, but it can be taken back.
- Capacity Reservations: reserve capacity in one availability zone for business-critical events, high availability or disaster recovery.
- Per-second billing (60-second minimum) removes the cost of unused time, which helps irregular workloads.
- Free tier and a pricing calculator are available. Azure has its own pricing calculator.
- The course table says reserved instances give up to 66% off, and this page says savings plans give up to 72%. Both numbers change over time.

### Reading: What is FinOps? (FinOps Foundation)
- FinOps is an operational framework and cultural practice that maximizes the business value of technology through collaboration between engineering, finance and business teams. The name combines "Finance" and "DevOps".
- It is about getting the most value from technology, not only about saving money.
- Everyone owns their own cost and usage, supported by a central best-practices group.
- Maturity follows "crawl, walk, run": crawl is reactive and fixes problems after they happen, run factors cost into architecture decisions from the start.
- Framework parts: principles, personas (executives, engineers, finance, procurement and others), maturity model, scopes.
- FOCUS is an open specification for billing data, and the big cloud providers export it, which makes cost skills transferable across clouds.

### Reading: AWS Cost Optimization pillar
- Cost optimization is a continual process of refinement over a workload's lifecycle.
- Goal: deliver business outcomes at the lowest appropriate price while meeting performance, reliability, security and sustainability needs.
- Four areas:
  - Cloud financial management: budgets, forecasts and targets, set before the workload runs.
  - Expenditure and usage awareness: you can't optimize what you can't see, so monitor cost, manage the lifecycle of resources and plan for data transfer costs.
  - Cost-efficient resources: pick the right service, size and pricing model.
  - Continuous optimization: match capacity to demand, review regularly and automate.
- The aim is the best ratio of cost to business value, not the lowest cost alone.

### How it applies to AirBreda
- A small VM running 24/7 on on-demand pricing is the baseline. Switching it off when not needed, and the 10 versus 50 corridor estimate, are the FinOps part of the ADR.

## Storage

### Reading: Introduction to Azure Storage
- Azure Storage is Microsoft's cloud storage: durable, highly available, secure, scalable, managed and reachable over HTTP/HTTPS.
- Data services: Blobs (object store), Files (managed file shares), Queues (messaging), Tables (NoSQL key/attribute), managed disks (block storage for VMs), plus Elastic SAN, Container Storage, NetApp Files and Managed Lustre.
- Blob Storage is for unstructured data: backups, files for distributed access, serving files to browsers, and data for analysis.
- Azure Files is for lift and shift of apps that use file shares. Managed disks are for data attached to one VM.
- Access is controlled with Microsoft Entra, shared key or shared access signatures (SAS). All data is encrypted at rest.
- You choose a redundancy option when you create the storage account.
- This maps to the course table: Blob Storage = object, managed disk = block, Azure Files = file.

### Reading: Prepare to choose a data store in Azure
- Decide the data store by comparing functional needs (data format, relationships, consistency, access method), non-functional needs (latency, scale, availability), cost, security and the team's skills.
- Key questions: how much control over the database engine, whether the workload is relational, key-value, document, time-series or analytics.
- For relational workloads Azure offers SQL Database, Azure Database for MySQL and Azure Database for PostgreSQL, all managed (PaaS).
- Cosmos DB covers document, key-value and graph data, Fabric covers analytics, and Azure Data Explorer covers time-series.
- Azure Policy can restrict which database types people may create.
- For AirBreda this points to Azure Database for PostgreSQL, because the lab SQL is PostgreSQL.

### Reading: Time-series data: why (and how) to use a relational database instead of NoSQL (TimescaleDB)
- Time-series data (sensors, monitoring, finance) is mostly INSERTs to a recent time interval, unlike OLTP, which is mostly random UPDATEs.
- Plain relational databases slow down as tables grow, because indexes no longer fit in memory and updates cause expensive disk swaps. PostgreSQL's insert rate dropped sharply after about 50 million rows.
- NoSQL databases use LSM trees to make writes cheaper, but need more memory and have poor secondary index support.
- TimescaleDB splits data into time-based "chunks" so recent chunks and indexes stay in memory, which gave about 15x better insert rates.
- This is a vendor's view, but the point stands: for AirBreda's tiny volume, plain PostgreSQL is enough and a relational database is not the problem.

## Architecture and delivery

### Reading: Spotify event delivery, Part I
- Events (such as listening to a song) from clients are sent to gateways and have to reach a central Hadoop cluster in hourly buckets.
- The old system was built on Kafka 0.7. An event only counted as reliably persisted once it was written to HDFS, so Hadoop was a single point of failure.
- The system handled more than 700,000 events per second.
- Problems: producers had to wait for confirmation from a far-away data center, all event types shared one channel, the ETL step added about 30 minutes, a dead machine could not send an end-of-file marker so hours waited forever, and the components were tightly coupled.
- Rising load caused more outages, and because of the coupling it could not be improved step by step. They decided on a full rewrite.

### Reading: Spotify event delivery, Part II
- New design: a simple file tailer, an Event Delivery Service, a reliable persistent queue and an ETL job. One topic per event type, structured format early.
- They first tried Kafka 0.8, but Mirror Maker dropped data and reported success, and the producer could get stuck and need a restart.
- They chose Google Cloud Pub/Sub: 7 days of retention, at-least-once delivery, global availability, and Google handled operations.
- Load test: 2 million events per second without degradation. Consumer test: about 800,000 per second for 5 days, median latency about 20 seconds and no lost messages.
- Trade-off: a managed service means trusting another organization's operations, but it removed their capacity planning and monitoring work.
- Link to the course: a single database or system works until volume grows, and managed services can shift the operational burden.

### Reading: Questioning the Lambda Architecture (Kreps) and Databricks glossary
- Lambda architecture feeds the same data into a batch layer (accurate, slow) and a speed layer (recent, fast), and merges them in a serving layer.
- Good: it keeps the input data unchanged and highlights the need for reprocessing, because code always changes.
- Bad: the same logic has to be written and kept in sync in two different systems, which is painful and complex.
- It does not "beat the CAP theorem". Results are asynchronous, so CAP still applies.
- Kappa alternative: one stream processing system with a retained log (e.g. Kafka). To reprocess, start a second job from the beginning and switch when it catches up.
- Advice: use batch if you are not latency sensitive, stream if you are, and don't do both unless you must.
- The Databricks page lists benefits like "no server management", which describes serverless AWS Lambda, not the architecture. Be careful not to mix the two up.

### Reading: Kafka delivery guarantees and Flink fault tolerance
- At most once: messages may be lost and are not redelivered. At least once: nothing is lost but there may be duplicates. Exactly once: each message exactly once, which costs more latency and complexity.
- Kafka defaults to at-least-once. With a primary key, writes can be made idempotent, so a repeated message just overwrites the same record.
- Flink takes periodic snapshots (checkpoints) so it can resume after a failure. "Exactly once" there means each event affects the state once, not that it is processed once.
- Exactly once end to end needs replayable sources and transactional or idempotent sinks.
- For AirBreda: at-least-once with an upsert on (station, timestamp, component) is enough, so exactly-once is over-engineering.

### Reading: AWS Well-Architected Framework
- The framework helps you judge the pros and cons of architecture decisions. Reviews are constructive conversations, not audits.
- It moves architecture from a central team to the teams that build the workload, supported by shared standards and automated checks.
- Governance by automation: infrastructure as code, guardrails that prevent non-compliant deployments instead of detecting them afterwards, and architecture decision records.
- This links back to Zalando: the same problem of violations found after the fact, solved by preventive guardrails.
- Architecture is evolutionary: make decisions reversible, use data, and keep documentation and decision records up to date as it changes.
- This is the reason for writing an ADR for every decision.

## Estimation exercise (Kubernetes cluster 24/7, job runs 08:00-20:00, €500/month)
- The job runs 12 hours a day but the cluster runs 24, so half of the cluster time is idle. Half of €500 is about €250 wasted per month.
- Fix: scale the cluster down to zero or the minimum outside 08:00-20:00 (scheduled scaling), use autoscaling so capacity follows demand, or run the job as a scheduled CronJob so resources exist only while it runs. This is the FinOps idea of matching spend to usage.

## Day 1 wrap-up questions
1. DynamoDB: three questions I would ask:
   - How much data and write traffic do we really have? AirBreda has about 100,000 rows a year, so infinite scaling solves a problem we don't have.
   - Do we need joins and time-range queries? Yes, correlating NO2 with traffic needs a join, and DynamoDB is built for key lookups.
   - What does it cost us in skills and lock-in? The team knows SQL, so a relational database is cheaper to learn and more portable.
2. Row count after 5 years and 10 stations:
   - 3 components x 8,760 hours x 10 stations x 5 years = about 1.3 million rows (about 2.2 million if all 5 components are stored).
   - This does not change the database choice. It is small for PostgreSQL, which only starts to slow down at tens of millions of rows, so a relational database with an index on station and timestamp is still the right answer.
3. Most recent NO2 value, and what a null would look like:
   - The most recent NO2 value was 17.96 µg/m³ at 09:00 UTC (26 Nov 2026).
   - A null would be a record with "value": null (or an hour missing from the list). The pipeline keeps it as NULL instead of dropping it or replacing it with 0, flags it, and reports the last valid reading together with its age, so the dashboard shows "data stale" instead of a wrong number.