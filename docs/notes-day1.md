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
- **Migrate:** start with