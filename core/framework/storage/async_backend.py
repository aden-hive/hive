"""
Async Storage Protocol and Backends

This module provides high-performance async storage backends for the framework:
- AsyncFileStorage: Async file I/O with aiofiles
- RedisStorage: High-performance Redis backend for hot data
- PostgresStorage: Durable storage for production
- StorageFactory: Easy backend switching
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional

import aiofiles
import aiofiles.os
import orjson

if TYPE_CHECKING:
    from framework.schemas.run import Run, RunSummary, RunStatus

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """
    Abstract async storage backend protocol.
    
    All storage backends must implement these async methods.
    """
    
    @abstractmethod
    async def save_run(self, run: "Run") -> None:
        """Save a run to storage."""
        pass
    
    @abstractmethod
    async def load_run(self, run_id: str) -> Optional["Run"]:
        """Load a run from storage."""
        pass
    
    @abstractmethod
    async def load_summary(self, run_id: str) -> Optional["RunSummary"]:
        """Load just the summary (faster than full run)."""
        pass
    
    @abstractmethod
    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from storage."""
        pass
    
    @abstractmethod
    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        pass
    
    @abstractmethod
    async def get_runs_by_status(self, status: str) -> list[str]:
        """Get all run IDs with a status."""
        pass
    
    @abstractmethod
    async def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the storage backend and release resources."""
        pass


class AsyncFileStorage(StorageBackend):
    """
    High-performance async file-based storage.
    
    Uses aiofiles for non-blocking I/O and orjson for fast serialization.
    
    Directory structure:
    {base_path}/
      runs/{run_id}.json           # Full run data
      indexes/by_goal/{goal_id}.json
      indexes/by_status/{status}.json
      summaries/{run_id}.json      # Quick-load summaries
    """
    
    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        if self._initialized:
            return
        
        dirs = [
            self.base_path / "runs",
            self.base_path / "indexes" / "by_goal",
            self.base_path / "indexes" / "by_status",
            self.base_path / "indexes" / "by_node",
            self.base_path / "summaries",
        ]
        
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        
        self._initialized = True
    
    async def save_run(self, run: "Run") -> None:
        """Save a run to storage using async I/O."""
        await self._ensure_dirs()
        
        # Use orjson for 10x faster serialization
        run_data = orjson.dumps(
            run.model_dump(),
            option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY
        )
        
        run_path = self.base_path / "runs" / f"{run.id}.json"
        async with aiofiles.open(run_path, "wb") as f:
            await f.write(run_data)
        
        # Save summary
        from framework.schemas.run import RunSummary
        summary = RunSummary.from_run(run)
        summary_data = orjson.dumps(summary.model_dump(), option=orjson.OPT_INDENT_2)
        
        summary_path = self.base_path / "summaries" / f"{run.id}.json"
        async with aiofiles.open(summary_path, "wb") as f:
            await f.write(summary_data)
        
        # Update indexes concurrently
        await asyncio.gather(
            self._add_to_index("by_goal", run.goal_id, run.id),
            self._add_to_index("by_status", run.status.value, run.id),
            *[
                self._add_to_index("by_node", node_id, run.id)
                for node_id in run.metrics.nodes_executed
            ]
        )
    
    async def load_run(self, run_id: str) -> Optional["Run"]:
        """Load a run from storage."""
        from framework.schemas.run import Run
        
        run_path = self.base_path / "runs" / f"{run_id}.json"
        if not run_path.exists():
            return None
        
        async with aiofiles.open(run_path, "rb") as f:
            data = await f.read()
        
        return Run.model_validate(orjson.loads(data))
    
    async def load_summary(self, run_id: str) -> Optional["RunSummary"]:
        """Load just the summary (faster than full run)."""
        from framework.schemas.run import RunSummary
        
        summary_path = self.base_path / "summaries" / f"{run_id}.json"
        
        if not summary_path.exists():
            # Fall back to computing from full run
            run = await self.load_run(run_id)
            if run:
                return RunSummary.from_run(run)
            return None
        
        async with aiofiles.open(summary_path, "rb") as f:
            data = await f.read()
        
        return RunSummary.model_validate(orjson.loads(data))
    
    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        summary_path = self.base_path / "summaries" / f"{run_id}.json"
        
        if not run_path.exists():
            return False
        
        # Load run to get index keys
        run = await self.load_run(run_id)
        if run:
            await asyncio.gather(
                self._remove_from_index("by_goal", run.goal_id, run_id),
                self._remove_from_index("by_status", run.status.value, run_id),
                *[
                    self._remove_from_index("by_node", node_id, run_id)
                    for node_id in run.metrics.nodes_executed
                ]
            )
        
        # Delete files
        await aiofiles.os.remove(run_path)
        if summary_path.exists():
            await aiofiles.os.remove(summary_path)
        
        return True
    
    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        return await self._get_index("by_goal", goal_id)
    
    async def get_runs_by_status(self, status: str) -> list[str]:
        """Get all run IDs with a status."""
        return await self._get_index("by_status", status)
    
    async def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        await self._ensure_dirs()
        runs_dir = self.base_path / "runs"
        return [f.stem for f in runs_dir.glob("*.json")]
    
    async def close(self) -> None:
        """Close the storage backend."""
        pass  # File storage doesn't need cleanup
    
    # === Index Operations (with locking for thread safety) ===
    
    async def _get_index(self, index_type: str, key: str) -> list[str]:
        """Get values from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        if not index_path.exists():
            return []
        
        async with aiofiles.open(index_path, "rb") as f:
            data = await f.read()
        
        return orjson.loads(data)
    
    async def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index with locking."""
        async with self._lock:
            index_path = self.base_path / "indexes" / index_type / f"{key}.json"
            values = await self._get_index(index_type, key)
            
            if value not in values:
                values.append(value)
                async with aiofiles.open(index_path, "wb") as f:
                    await f.write(orjson.dumps(values))
    
    async def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index with locking."""
        async with self._lock:
            index_path = self.base_path / "indexes" / index_type / f"{key}.json"
            values = await self._get_index(index_type, key)
            
            if value in values:
                values.remove(value)
                async with aiofiles.open(index_path, "wb") as f:
                    await f.write(orjson.dumps(values))


class RedisStorage(StorageBackend):
    """
    High-performance Redis storage for hot/active data.
    
    Features:
    - Connection pooling with hiredis
    - Automatic TTL for expiration
    - Pipeline operations for batch writes
    - Sorted sets for time-based queries
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 86400,  # 24 hours
        max_connections: int = 50,
    ):
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.max_connections = max_connections
        self._pool = None
        self._client = None
    
    async def _get_client(self):
        """Get or create Redis client with connection pool."""
        if self._client is None:
            try:
                import redis.asyncio as redis
            except ImportError:
                raise ImportError(
                    "Redis support requires 'redis' package. "
                    "Install with: pip install redis[hiredis]"
                )
            
            self._pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                decode_responses=False,  # Binary mode for orjson
            )
            self._client = redis.Redis(connection_pool=self._pool)
        
        return self._client
    
    async def save_run(self, run: "Run") -> None:
        """Save a run to Redis with pipeline for atomicity."""
        client = await self._get_client()
        
        # Serialize with orjson
        run_data = orjson.dumps(run.model_dump())
        
        # Build summary
        from framework.schemas.run import RunSummary
        summary = RunSummary.from_run(run)
        summary_data = orjson.dumps(summary.model_dump())
        
        # Use pipeline for atomic multi-key operation
        async with client.pipeline(transaction=True) as pipe:
            # Store run with TTL
            pipe.set(f"run:{run.id}", run_data, ex=self.default_ttl)
            pipe.set(f"summary:{run.id}", summary_data, ex=self.default_ttl)
            
            # Add to sorted set for time-based queries
            timestamp = run.started_at.timestamp() if run.started_at else datetime.now().timestamp()
            pipe.zadd("runs:by_time", {run.id: timestamp})
            
            # Add to goal and status sets
            pipe.sadd(f"runs:by_goal:{run.goal_id}", run.id)
            pipe.sadd(f"runs:by_status:{run.status.value}", run.id)
            
            # Add to node sets
            for node_id in run.metrics.nodes_executed:
                pipe.sadd(f"runs:by_node:{node_id}", run.id)
            
            await pipe.execute()
    
    async def load_run(self, run_id: str) -> Optional["Run"]:
        """Load a run from Redis."""
        from framework.schemas.run import Run
        
        client = await self._get_client()
        data = await client.get(f"run:{run_id}")
        
        if data:
            return Run.model_validate(orjson.loads(data))
        return None
    
    async def load_summary(self, run_id: str) -> Optional["RunSummary"]:
        """Load a summary from Redis."""
        from framework.schemas.run import RunSummary
        
        client = await self._get_client()
        data = await client.get(f"summary:{run_id}")
        
        if data:
            return RunSummary.model_validate(orjson.loads(data))
        
        # Fall back to computing from full run
        run = await self.load_run(run_id)
        if run:
            return RunSummary.from_run(run)
        return None
    
    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from Redis."""
        client = await self._get_client()
        
        # Load run to get index keys
        run = await self.load_run(run_id)
        if not run:
            return False
        
        async with client.pipeline(transaction=True) as pipe:
            pipe.delete(f"run:{run_id}")
            pipe.delete(f"summary:{run_id}")
            pipe.zrem("runs:by_time", run_id)
            pipe.srem(f"runs:by_goal:{run.goal_id}", run_id)
            pipe.srem(f"runs:by_status:{run.status.value}", run_id)
            
            for node_id in run.metrics.nodes_executed:
                pipe.srem(f"runs:by_node:{node_id}", run_id)
            
            await pipe.execute()
        
        return True
    
    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        client = await self._get_client()
        members = await client.smembers(f"runs:by_goal:{goal_id}")
        return [m.decode() if isinstance(m, bytes) else m for m in members]
    
    async def get_runs_by_status(self, status: str) -> list[str]:
        """Get all run IDs with a status."""
        client = await self._get_client()
        members = await client.smembers(f"runs:by_status:{status}")
        return [m.decode() if isinstance(m, bytes) else m for m in members]
    
    async def list_all_runs(self, limit: int = 1000) -> list[str]:
        """List all run IDs (most recent first)."""
        client = await self._get_client()
        members = await client.zrevrange("runs:by_time", 0, limit - 1)
        return [m.decode() if isinstance(m, bytes) else m for m in members]
    
    async def close(self) -> None:
        """Close Redis connection pool."""
        if self._client:
            await self._client.close()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None


class PostgresStorage(StorageBackend):
    """
    Durable PostgreSQL storage for production environments.
    
    Features:
    - Async connection pooling with asyncpg
    - JSONB storage with GIN indexes
    - Full ACID compliance
    - Efficient pagination and filtering
    """
    
    # SQL for creating tables
    CREATE_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS runs (
        id VARCHAR(64) PRIMARY KEY,
        goal_id VARCHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL,
        data JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE INDEX IF NOT EXISTS idx_runs_goal_id ON runs (goal_id);
    CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);
    CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_runs_data_gin ON runs USING GIN (data jsonb_path_ops);
    """
    
    def __init__(
        self,
        dsn: str = "postgresql://localhost/hive",
        min_connections: int = 5,
        max_connections: int = 20,
    ):
        self.dsn = dsn
        self.min_connections = min_connections
        self.max_connections = max_connections
        self._pool = None
    
    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            try:
                import asyncpg
            except ImportError:
                raise ImportError(
                    "PostgreSQL support requires 'asyncpg' package. "
                    "Install with: pip install asyncpg"
                )
            
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=self.min_connections,
                max_size=self.max_connections,
                command_timeout=30,
            )
            
            # Create tables if they don't exist
            async with self._pool.acquire() as conn:
                await conn.execute(self.CREATE_TABLES_SQL)
        
        return self._pool
    
    @asynccontextmanager
    async def _acquire(self) -> AsyncGenerator:
        """Acquire a connection from the pool."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            yield conn
    
    async def save_run(self, run: "Run") -> None:
        """Save a run to PostgreSQL."""
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO runs (id, goal_id, status, data, created_at, updated_at)
                VALUES ($1, $2, $3, $4, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    data = EXCLUDED.data,
                    updated_at = NOW()
                """,
                run.id,
                run.goal_id,
                run.status.value,
                orjson.dumps(run.model_dump()).decode(),
            )
    
    async def load_run(self, run_id: str) -> Optional["Run"]:
        """Load a run from PostgreSQL."""
        from framework.schemas.run import Run
        
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM runs WHERE id = $1",
                run_id
            )
        
        if row:
            return Run.model_validate(orjson.loads(row["data"]))
        return None
    
    async def load_summary(self, run_id: str) -> Optional["RunSummary"]:
        """Load a summary (computed from run data)."""
        from framework.schemas.run import RunSummary
        
        run = await self.load_run(run_id)
        if run:
            return RunSummary.from_run(run)
        return None
    
    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from PostgreSQL."""
        async with self._acquire() as conn:
            result = await conn.execute(
                "DELETE FROM runs WHERE id = $1",
                run_id
            )
        
        return "DELETE 1" in result
    
    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM runs WHERE goal_id = $1 ORDER BY created_at DESC",
                goal_id
            )
        
        return [row["id"] for row in rows]
    
    async def get_runs_by_status(self, status: str) -> list[str]:
        """Get all run IDs with a status."""
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM runs WHERE status = $1 ORDER BY created_at DESC",
                status
            )
        
        return [row["id"] for row in rows]
    
    async def list_all_runs(self, limit: int = 1000) -> list[str]:
        """List all run IDs."""
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT $1",
                limit
            )
        
        return [row["id"] for row in rows]
    
    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


class StorageFactory:
    """
    Factory for creating storage backends.
    
    Usage:
        # File-based (default)
        storage = StorageFactory.create("file", base_path="/data")
        
        # Redis (hot storage)
        storage = StorageFactory.create("redis", redis_url="redis://localhost")
        
        # PostgreSQL (production)
        storage = StorageFactory.create("postgres", dsn="postgresql://...")
    """
    
    @staticmethod
    def create(backend: str = "file", **kwargs) -> StorageBackend:
        """Create a storage backend instance."""
        backends = {
            "file": AsyncFileStorage,
            "redis": RedisStorage,
            "postgres": PostgresStorage,
            "postgresql": PostgresStorage,
        }
        
        if backend not in backends:
            raise ValueError(
                f"Unknown storage backend: {backend}. "
                f"Available: {list(backends.keys())}"
            )
        
        return backends[backend](**kwargs)


class TieredStorage(StorageBackend):
    """
    Multi-tier storage with automatic promotion/demotion.
    
    Hot tier (Redis) -> Warm tier (File/Postgres) -> Cold tier (S3)
    
    Recent data stays in hot tier, older data moves to warm/cold.
    """
    
    def __init__(
        self,
        hot: StorageBackend,
        warm: StorageBackend,
        hot_ttl_hours: int = 24,
    ):
        self.hot = hot
        self.warm = warm
        self.hot_ttl_hours = hot_ttl_hours
    
    async def save_run(self, run: "Run") -> None:
        """Save to both hot and warm tiers."""
        await asyncio.gather(
            self.hot.save_run(run),
            self.warm.save_run(run),
        )
    
    async def load_run(self, run_id: str) -> Optional["Run"]:
        """Try hot tier first, then warm."""
        run = await self.hot.load_run(run_id)
        if run:
            return run
        
        # Fall back to warm tier
        run = await self.warm.load_run(run_id)
        if run:
            # Promote to hot tier for future access
            await self.hot.save_run(run)
        
        return run
    
    async def load_summary(self, run_id: str) -> Optional["RunSummary"]:
        """Try hot tier first, then warm."""
        summary = await self.hot.load_summary(run_id)
        if summary:
            return summary
        
        return await self.warm.load_summary(run_id)
    
    async def delete_run(self, run_id: str) -> bool:
        """Delete from all tiers."""
        results = await asyncio.gather(
            self.hot.delete_run(run_id),
            self.warm.delete_run(run_id),
        )
        return any(results)
    
    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get from warm tier (complete index)."""
        return await self.warm.get_runs_by_goal(goal_id)
    
    async def get_runs_by_status(self, status: str) -> list[str]:
        """Get from warm tier (complete index)."""
        return await self.warm.get_runs_by_status(status)
    
    async def list_all_runs(self) -> list[str]:
        """Get from warm tier (complete list)."""
        return await self.warm.list_all_runs()
    
    async def close(self) -> None:
        """Close all tiers."""
        await asyncio.gather(
            self.hot.close(),
            self.warm.close(),
        )
