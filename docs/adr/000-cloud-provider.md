# ADR-000: Cloud Provider

**Status:** Accepted
**Date:** 2026-11-26

## Context
AirBreda needs a cloud platform for a managed database, object storage and, later in the week, a virtual machine that runs three containers. The system is small, runs for about a week, and must be cheap and easy to tear down. I had no prior hands-on experience with either major provider.

## Decision
Use **Microsoft Azure**, region **North Europe (Ireland)**.

## Reasons
- **Cost:** my subscription includes credit (about €180, expiring 23 December 2026), which covers this project without a credit card charge. Budget is protected by choosing small tiers (Burstable B1ms PostgreSQL, standard locally-redundant storage).
- **Equivalent services:** Azure has what the case needs: Blob Storage (object storage), PostgreSQL Flexible Server (managed relational DB), and Linux VMs. These map directly to the AWS concepts in the course (S3, RDS, EC2).
- **Career relevance:** Azure is widely used in Dutch enterprises and government, so the experience transfers. The concepts (object vs block vs file storage, managed DB, VM, networking) are the same on AWS.
- **EU data residency:** the data stays in an EU region, which matters for GDPR in general, even though this dataset is open data.

## Alternatives considered and rejected
- **AWS (S3 + RDS + EC2):** the course examples use AWS, and it has the largest market share. Rejected because I had no credit available there, and the free tier would need a card with a risk of surprise charges.
- **Run everything locally or on a cheap VPS:** cheapest, but it would not show managed-service trade-offs, which is the point of the elective.

## Consequences
- Positive: no cost to me, same concepts as AWS, region close to Breda (low latency).
- Negative: course material uses AWS names, so I translate (S3 -> Blob, RDS -> Flexible Server, EC2 -> VM). Some regions refused to provision PostgreSQL on my subscription (West Europe), so I used North Europe.
- Cost control: the default PostgreSQL tier would have cost about USD 327/month, so I picked the Burstable B1ms tier (about USD 17/month). The whole resource group is deleted after the demo.
- Revisit if: credits run out or the project needs a service Azure's free allowances do not cover.