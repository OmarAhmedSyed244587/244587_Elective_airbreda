# Day 3 notes: Provisioning, storage and connecting the stack

## What I built
- Azure Linux VM (Ubuntu 24.04, `Standard_B2ts_v2`, Sweden Central) running two containers 24/7: `air-ingest` (hourly) and `traffic-ingest` (every 5 minutes).
- Both containers write parsed readings to PostgreSQL (`sensor_readings`) and the traffic container uploads raw CSVs to Blob Storage.
- The VM uses a **system-assigned managed identity** with `Storage Blob Data Contributor` on the storage account, so no storage key is on the VM.
- The database password is only in a `.env` file on the VM (mode 600, not in git).
- SSH is limited to my IP; the database firewall allows only the VM and my laptop; the broad "allow Azure services" rule was removed.
- Budget alert set in Cost Management (EUR 40 per month, alerts at 80% and 100%).

## Checklist result
- VM running in the cloud: yes
- Both containers run on the VM: yes
- `sensor_readings` has real rows from the VM: yes (FLOW, SPEED, NO2, NO, NOx, PM10, PM25)
- NDW files in object storage: yes (36 files at the time of checking)
- No hardcoded storage credentials: yes (managed identity)
- ADR-004 written: yes
- Cost so far: EUR 0.03 (reporting lags by about a day)

## Problems I hit and how I fixed them
- **VM size unavailable:** `Standard_B1s` failed with `SkuNotAvailable` in every region I tried. `Standard_B2ts_v2` in Sweden Central worked.
- **Commands run in the wrong place:** I ran `az` commands inside the VM and `git` commands on the VM. Rule: `azureuser@airbreda-vm` is the VM, `PS C:\` is my laptop.
- **SSH locked out:** the NSG rule allows only my IP, so a new network meant `Connection timed out`. Fix: re-run `az network nsg rule update` with the new IP.
- **Container crash loop (OOM):** `traffic-ingest` was killed 376 times (`OOMKilled=true`, exit code 137) with no log output, because parsing the NDW files needs more than the 1 GB of RAM. Fix: a 2 GB swap file. Better long-term fix: stream-parse the XML.
- **Uncommitted file:** `ingest_air.py` had changes that were never pushed, so the VM would have cloned an old version. `git status` caught it.
- **CLI argument names:** `az postgres flexible-server firewall-rule` uses `--server-name` for the server and `--name` for the rule name in this CLI version.

## Things I learned
- IaaS means I own the OS, Docker, networking, the firewall and the identity setup.
- A managed identity removes secrets from the machine: the code asks for a token instead of holding a key.
- `docker inspect` (`OOMKilled`, `RestartCount`) finds problems that the logs cannot show.
- Silent restarts are dangerous: `--restart unless-stopped` hid a crash loop for 3 hours.

## To do before the end
- Change the database password (it was shared in chat earlier) and update the `.env` on the VM, then restart the containers.
- Delete the resource group `airbreda-rg` after the demo to stop charges.