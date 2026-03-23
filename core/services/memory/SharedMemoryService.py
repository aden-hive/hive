import redis
import json

class SharedMemoryService:
    """
    Shared Memory Service for cross-agent state persistence.
    Enables autonomous swarms to maintain shared context and history.
    """
    def __init__(self, redis_url="redis://localhost:6379/0"):
        self.r = redis.from_url(redis_url)

    def store_context(self, swarm_id, key, value):
        full_key = f"hive:{swarm_id}:{key}"
        self.r.set(full_key, json.dumps(value))

    def retrieve_context(self, swarm_id, key):
        full_key = f"hive:{swarm_id}:{key}"
        data = self.r.get(full_key)
        return json.loads(data) if data else None
