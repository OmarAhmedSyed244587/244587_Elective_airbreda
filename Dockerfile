FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ingest_air.py db.py publisher.py jsonlog.py ./

CMD ["python", "ingest_air.py"]