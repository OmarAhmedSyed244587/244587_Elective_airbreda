FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir requests pandas

COPY ingest_air.py .

# Data is fetched live from the API on every run - nothing to bake into the image
CMD ["python", "ingest_air.py"]