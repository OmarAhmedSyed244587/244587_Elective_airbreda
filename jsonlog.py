"""
jsonlog.py - structured (JSON) logging helpers shared by the ingestion services.

Every log line is one JSON object, so a monitoring tool can filter on fields
like "event" or "level" instead of grepping free text.
"""

import json
import logging
import sys
from datetime import datetime, timezone


def setup(level=logging.INFO):
    """Send plain-message log lines to stdout (the JSON is built in event())."""
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    logging.getLogger("azure").setLevel(logging.WARNING)  # silence the chatty SDK


def event(logger, level, name, **fields):
    """Log one structured event, e.g. event(log, logging.INFO, "fetch_success", value=18.4)."""
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": logging.getLevelName(level),
        "event": name,
        **fields,
    }
    logger.log(level, json.dumps(record, default=str))