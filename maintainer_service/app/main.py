"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from app.config import settings
from app.database import init_db
from app.scheduler import start_scheduler
from app.webhooks import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Initializing Maintainer Service...")
    init_db()
    scheduler = start_scheduler(settings.analysis_interval_minutes)
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    scheduler.shutdown()


app = FastAPI(
    title="Maintainer Service",
    description="Intelligent GitHub Issue & PR Management",
    lifespan=lifespan
)

# Register routes
app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
