"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn
import argparse
import sys
import os

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
    parser = argparse.ArgumentParser(description="Maintainer Service")
    parser.add_argument("--check", type=str, help="Lookback window in hours (e.g., 24, 0.5, 1/60)")
    parser.add_argument("--schedule", type=str, help="Analysis interval in hours (e.g., 1, 0.5, 1/60)")
    
    # Parse known args to avoid conflict with uvicorn or other potential args
    args, unknown = parser.parse_known_args()
    
    def parse_hours(value: str) -> float:
        try:
            if "/" in value:
                num, denom = value.split("/")
                return float(num) / float(denom)
            return float(value)
        except ValueError:
            print(f"Error: Invalid hour format '{value}'. Use decimal (0.5) or fraction (1/2).")
            sys.exit(1)
    
    if args.check:
        hours = parse_hours(args.check)
        minutes = int(hours * 60)
        # Ensure at least 1 minute
        minutes = max(1, minutes)
        os.environ["LOOKBACK_WINDOW_MINUTES"] = str(minutes)
        print(f"Configured lookback window: {args.check} hours ({minutes} minutes)")
        
    if args.schedule:
        hours = parse_hours(args.schedule)
        minutes = int(hours * 60)
        # Ensure at least 1 minute
        minutes = max(1, minutes)
        os.environ["ANALYSIS_INTERVAL_MINUTES"] = str(minutes)
        print(f"Configured analysis interval: {args.schedule} hours ({minutes} minutes)")
    
    # Remove our custom args from sys.argv so uvicorn doesn't complain if we were to use sys.argv
    # But here we are using uvicorn.run programmatically, so it's fine.
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
