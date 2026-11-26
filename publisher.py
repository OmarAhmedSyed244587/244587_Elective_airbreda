"""
publisher.py - push reading messages onto the shared Redis list "readings".

Producer -> broker -> consumer: the ingestion scripts only know this one
function, not who reads the queue afterwards. If REDIS_HOST is not set (for
example when running locally without Docker) nothing is published.
"""

import json
import os

QUEUE = "readings"


def publish(messages: list[dict]) -> int:
    """RPUSH each message as a JSON string. Returns how many were published."""
    host = os.environ.get("REDIS_HOST")
    if not host or not messages:
        return 0

    import redis

    client = redis.Redis(
        host=host,
        port=int(os.environ.get("REDIS_PORT", "6379")),
        socket_connect_timeout=5,
    )
    for message in messages:
        client.rpush(QUEUE, json.dumps(message))
    return len(messages)