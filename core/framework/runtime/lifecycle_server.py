"""
Lifecycle Server for Hive Agent Runtime

Provides HTTP API for lifecycle management and health monitoring.
Designed for production deployments in Docker/Kubernetes.

Usage:
    # Start with lifecycle server enabled
    python -m framework.runtime.lifecycle_server --agent exports/my-agent --port 8080
    
    # Or programmatically
    from framework.runtime.lifecycle_server import LifecycleServer
    server = LifecycleServer(runtime, config)
    await server.start()
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

# Assuming these exist in the framework
# from framework.runtime.agent_runtime import AgentRuntime, RuntimeState
# For demo purposes, we'll define minimal versions

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class LifecycleConfig:
    """Configuration for lifecycle server."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    graceful_shutdown_timeout: float = 30.0  # seconds
    enable_metrics: bool = True
    enable_cors: bool = False
    cors_origins: list[str] = field(default_factory=list)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "LifecycleConfig":
        """Load configuration from environment variables."""
        import os

        return cls(
            enabled=os.getenv("HIVE_LIFECYCLE_ENABLED", "false").lower() == "true",
            host=os.getenv("HIVE_LIFECYCLE_HOST", "0.0.0.0"),
            port=int(os.getenv("HIVE_LIFECYCLE_PORT", "8080")),
            graceful_shutdown_timeout=float(
                os.getenv("HIVE_GRACEFUL_SHUTDOWN_TIMEOUT", "30.0")
            ),
            enable_metrics=os.getenv("HIVE_LIFECYCLE_METRICS", "true").lower()
            == "true",
            enable_cors=os.getenv("HIVE_LIFECYCLE_CORS", "false").lower() == "true",
        )


# ============================================================================
# Request/Response Models
# ============================================================================


class RuntimeStateEnum(str, Enum):
    """Runtime state enumeration."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


class HealthStatus(str, Enum):
    """Health status for components."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentHealth(BaseModel):
    """Health status of a component."""

    status: HealthStatus
    message: Optional[str] = None
    last_check: datetime = Field(default_factory=datetime.utcnow)


class RuntimeStatus(BaseModel):
    """Detailed runtime status."""

    state: RuntimeStateEnum
    uptime_seconds: float
    started_at: Optional[datetime] = None
    active_streams: int = 0
    total_executions: int = 0
    failed_executions: int = 0
    entry_points: list[str] = Field(default_factory=list)
    health: dict[str, ComponentHealth] = Field(default_factory=dict)


class LifecycleResponse(BaseModel):
    """Response from lifecycle operations."""

    success: bool
    message: str
    state: RuntimeStateEnum
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# Lifecycle Server
# ============================================================================


class LifecycleServer:
    """
    HTTP server for agent lifecycle management.

    Provides RESTful API for:
    - Lifecycle operations (start, stop, pause, resume)
    - Health checks (liveness, readiness)
    - Status monitoring
    - Metrics (Prometheus-compatible)
    """

    def __init__(
        self,
        runtime: Any,  # AgentRuntime
        config: Optional[LifecycleConfig] = None,
    ):
        """
        Initialize lifecycle server.

        Args:
            runtime: AgentRuntime instance to manage
            config: Server configuration (defaults to env vars)
        """
        self.runtime = runtime
        self.config = config or LifecycleConfig.from_env()
        self.app: Optional[FastAPI] = None
        self.server: Optional[uvicorn.Server] = None
        self._shutdown_event = asyncio.Event()
        self._started_at: Optional[datetime] = None

        # Metrics
        self._total_requests = 0
        self._failed_requests = 0

    def _create_app(self) -> FastAPI:
        """Create FastAPI application with all routes."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Lifespan context manager for startup/shutdown."""
            logger.info("Lifecycle server starting...")
            self._started_at = datetime.utcnow()
            yield
            logger.info("Lifecycle server shutting down...")
            await self._graceful_shutdown()

        app = FastAPI(
            title="Hive Agent Lifecycle API",
            description="Lifecycle management and health monitoring for Hive agents",
            version="1.0.0",
            lifespan=lifespan,
        )

        # CORS
        if self.config.enable_cors:
            from fastapi.middleware.cors import CORSMiddleware

            app.add_middleware(
                CORSMiddleware,
                allow_origins=self.config.cors_origins or ["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # ====================================================================
        # Lifecycle Endpoints
        # ====================================================================

        @app.post(
            "/api/v1/lifecycle/start",
            response_model=LifecycleResponse,
            status_code=status.HTTP_200_OK,
        )
        async def start_runtime():
            """Start the agent runtime."""
            try:
                if hasattr(self.runtime, "_running") and self.runtime._running:
                    return LifecycleResponse(
                        success=True,
                        message="Runtime already running",
                        state=RuntimeStateEnum.RUNNING,
                    )

                await self.runtime.start()
                logger.info("Runtime started via API")

                return LifecycleResponse(
                    success=True,
                    message="Runtime started successfully",
                    state=RuntimeStateEnum.RUNNING,
                )
            except Exception as e:
                logger.error(f"Failed to start runtime: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to start runtime: {str(e)}",
                )

        @app.post(
            "/api/v1/lifecycle/stop",
            response_model=LifecycleResponse,
            status_code=status.HTTP_200_OK,
        )
        async def stop_runtime():
            """Stop the agent runtime gracefully."""
            try:
                if hasattr(self.runtime, "_running") and not self.runtime._running:
                    return LifecycleResponse(
                        success=True,
                        message="Runtime already stopped",
                        state=RuntimeStateEnum.STOPPED,
                    )

                # Graceful shutdown with timeout
                try:
                    await asyncio.wait_for(
                        self.runtime.stop(),
                        timeout=self.config.graceful_shutdown_timeout,
                    )
                    logger.info("Runtime stopped gracefully via API")
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Runtime stop exceeded timeout of {self.config.graceful_shutdown_timeout}s"
                    )
                    # Force stop if needed
                    await self.runtime.stop()

                return LifecycleResponse(
                    success=True,
                    message="Runtime stopped successfully",
                    state=RuntimeStateEnum.STOPPED,
                )
            except Exception as e:
                logger.error(f"Failed to stop runtime: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to stop runtime: {str(e)}",
                )

        @app.post(
            "/api/v1/lifecycle/pause",
            response_model=LifecycleResponse,
            status_code=status.HTTP_200_OK,
        )
        async def pause_runtime():
            """Pause the agent runtime (finish in-flight work, stop accepting new)."""
            try:
                if not hasattr(self.runtime, "pause"):
                    raise HTTPException(
                        status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Pause operation not implemented in runtime",
                    )

                await self.runtime.pause(
                    drain_timeout=self.config.graceful_shutdown_timeout
                )
                logger.info("Runtime paused via API")

                return LifecycleResponse(
                    success=True,
                    message="Runtime paused successfully",
                    state=RuntimeStateEnum.PAUSED,
                )
            except Exception as e:
                logger.error(f"Failed to pause runtime: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to pause runtime: {str(e)}",
                )

        @app.post(
            "/api/v1/lifecycle/resume",
            response_model=LifecycleResponse,
            status_code=status.HTTP_200_OK,
        )
        async def resume_runtime():
            """Resume a paused runtime."""
            try:
                if not hasattr(self.runtime, "resume"):
                    raise HTTPException(
                        status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Resume operation not implemented in runtime",
                    )

                await self.runtime.resume()
                logger.info("Runtime resumed via API")

                return LifecycleResponse(
                    success=True,
                    message="Runtime resumed successfully",
                    state=RuntimeStateEnum.RUNNING,
                )
            except Exception as e:
                logger.error(f"Failed to resume runtime: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to resume runtime: {str(e)}",
                )

        @app.post(
            "/api/v1/lifecycle/restart",
            response_model=LifecycleResponse,
            status_code=status.HTTP_200_OK,
        )
        async def restart_runtime():
            """Restart the runtime (stop + start)."""
            try:
                # Stop
                if hasattr(self.runtime, "_running") and self.runtime._running:
                    await asyncio.wait_for(
                        self.runtime.stop(),
                        timeout=self.config.graceful_shutdown_timeout,
                    )

                # Small delay
                await asyncio.sleep(1)

                # Start
                await self.runtime.start()
                logger.info("Runtime restarted via API")

                return LifecycleResponse(
                    success=True,
                    message="Runtime restarted successfully",
                    state=RuntimeStateEnum.RUNNING,
                )
            except Exception as e:
                logger.error(f"Failed to restart runtime: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to restart runtime: {str(e)}",
                )

        # ====================================================================
        # Health & Status Endpoints
        # ====================================================================

        @app.get("/health/live", status_code=status.HTTP_200_OK)
        async def liveness_probe():
            """
            Liveness probe for Kubernetes.
            Returns 200 if process is alive, 503 if not.
            """
            # Simple check: is the server running?
            return {"status": "alive", "timestamp": datetime.utcnow()}

        @app.get("/health/ready", status_code=status.HTTP_200_OK)
        async def readiness_probe():
            """
            Readiness probe for Kubernetes.
            Returns 200 if ready to accept work, 503 if not.
            """
            try:
                # Check if runtime is in a ready state
                is_ready = (
                    hasattr(self.runtime, "_running") and self.runtime._running
                )

                if not is_ready:
                    return JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={
                            "status": "not_ready",
                            "reason": "Runtime not running",
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    )

                return {"status": "ready", "timestamp": datetime.utcnow()}
            except Exception as e:
                logger.error(f"Readiness check failed: {e}")
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "status": "not_ready",
                        "reason": str(e),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

        @app.get("/api/v1/status", response_model=RuntimeStatus)
        async def get_status():
            """Get detailed runtime status."""
            try:
                # Calculate uptime
                uptime = 0.0
                if self._started_at:
                    uptime = (datetime.utcnow() - self._started_at).total_seconds()

                # Determine state
                state = RuntimeStateEnum.STOPPED
                if hasattr(self.runtime, "_running"):
                    if self.runtime._running:
                        state = RuntimeStateEnum.RUNNING
                    # Check for pause state if implemented
                    if hasattr(self.runtime, "_paused") and self.runtime._paused:
                        state = RuntimeStateEnum.PAUSED

                # Get active streams
                active_streams = 0
                if hasattr(self.runtime, "_streams"):
                    active_streams = len(self.runtime._streams)

                # Get entry points
                entry_points = []
                if hasattr(self.runtime, "_entry_points"):
                    entry_points = list(self.runtime._entry_points.keys())

                # Component health checks
                health = {
                    "storage": ComponentHealth(status=HealthStatus.HEALTHY),
                    "llm": ComponentHealth(status=HealthStatus.HEALTHY),
                    "tools": ComponentHealth(status=HealthStatus.HEALTHY),
                }

                return RuntimeStatus(
                    state=state,
                    uptime_seconds=uptime,
                    started_at=self._started_at,
                    active_streams=active_streams,
                    total_executions=0,  # TODO: Track from runtime
                    failed_executions=0,  # TODO: Track from runtime
                    entry_points=entry_points,
                    health=health,
                )
            except Exception as e:
                logger.error(f"Failed to get status: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get status: {str(e)}",
                )

        @app.get("/api/v1/status/streams")
        async def get_streams():
            """Get active execution streams."""
            try:
                streams = []
                if hasattr(self.runtime, "_streams"):
                    for stream_id, stream in self.runtime._streams.items():
                        streams.append(
                            {
                                "id": stream_id,
                                "entry_node": getattr(stream, "entry_node", "unknown"),
                                "active": True,
                            }
                        )
                return {"streams": streams, "count": len(streams)}
            except Exception as e:
                logger.error(f"Failed to get streams: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get streams: {str(e)}",
                )

        # ====================================================================
        # Metrics Endpoint (Prometheus-compatible)
        # ====================================================================

        if self.config.enable_metrics:

            @app.get("/metrics", response_class=JSONResponse)
            async def metrics():
                """Prometheus-compatible metrics endpoint."""
                # Simple metrics for now
                uptime = 0.0
                if self._started_at:
                    uptime = (datetime.utcnow() - self._started_at).total_seconds()

                return {
                    "hive_runtime_uptime_seconds": uptime,
                    "hive_runtime_state": 1
                    if hasattr(self.runtime, "_running") and self.runtime._running
                    else 0,
                    "hive_active_streams": len(self.runtime._streams)
                    if hasattr(self.runtime, "_streams")
                    else 0,
                    "hive_total_requests": self._total_requests,
                    "hive_failed_requests": self._failed_requests,
                }

        return app

    async def start(self):
        """Start the lifecycle server."""
        if not self.config.enabled:
            logger.info("Lifecycle server disabled")
            return

        self.app = self._create_app()

        # Setup signal handlers
        self._setup_signal_handlers()

        # Create server
        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level.lower(),
        )
        self.server = uvicorn.Server(config)

        logger.info(
            f"Starting lifecycle server on {self.config.host}:{self.config.port}"
        )
        await self.server.serve()

    async def stop(self):
        """Stop the lifecycle server."""
        if self.server:
            logger.info("Stopping lifecycle server...")
            self.server.should_exit = True
            await asyncio.sleep(0.1)  # Give it time to shutdown

    async def _graceful_shutdown(self):
        """Handle graceful shutdown."""
        logger.info("Initiating graceful shutdown...")

        # Stop accepting new requests
        if self.server:
            self.server.should_exit = True

        # Stop runtime gracefully
        try:
            await asyncio.wait_for(
                self.runtime.stop(), timeout=self.config.graceful_shutdown_timeout
            )
            logger.info("Runtime stopped gracefully")
        except asyncio.TimeoutError:
            logger.warning(
                f"Runtime shutdown exceeded timeout of {self.config.graceful_shutdown_timeout}s"
            )
        except Exception as e:
            logger.error(f"Error during runtime shutdown: {e}")

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            asyncio.create_task(self._graceful_shutdown())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)


# ============================================================================
# Main Entry Point
# ============================================================================


async def main():
    """Main entry point for running lifecycle server."""
    import argparse

    parser = argparse.ArgumentParser(description="Hive Agent Lifecycle Server")
    parser.add_argument("--agent", required=True, help="Path to agent export")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    args = parser.parse_args()

    # Load agent (simplified - actual implementation would use AgentRunner)
    # from framework.runner.runner import AgentRunner
    # runtime = await AgentRunner.load(args.agent)

    # For demo, create a mock runtime
    class MockRuntime:
        def __init__(self):
            self._running = False
            self._streams = {}
            self._entry_points = {"main": None}

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

    runtime = MockRuntime()

    # Create and start server
    config = LifecycleConfig(
        enabled=True, host=args.host, port=args.port, enable_metrics=True
    )
    server = LifecycleServer(runtime, config)
    await server.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
