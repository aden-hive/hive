"""Configuration Management Service API."""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional

import sys
sys.path.append("../../core")

from framework.config.models import Configuration, FeatureFlag, FeatureFlagEvaluateRequest
from framework.config.service import ConfigService


app = FastAPI(
    title="Configuration Service",
    description="Centralized configuration and feature flag management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config_service = ConfigService()


@app.post("/api/v1/config/{environment}/{service}/{key}")
async def set_config(
    environment: str,
    service: str,
    key: str,
    value: Any,
    type: str = "string",
    is_sensitive: bool = False
):
    """Set a configuration value."""
    config = config_service.set_config(
        environment=environment,
        service=service,
        key=key,
        value=value,
        config_type=type,
        is_sensitive=is_sensitive
    )
    return config


@app.get("/api/v1/config/{environment}/{service}")
async def get_all_configs(environment: str, service: str):
    """Get all configurations for a service."""
    configs = config_service.get_all_configs(environment, service)
    return {"data": configs}


@app.get("/api/v1/config/{environment}/{service}/{key}")
async def get_config(environment: str, service: str, key: str):
    """Get a specific configuration value."""
    config = config_service.get_config(environment, service, key)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return config


@app.delete("/api/v1/config/{environment}/{service}/{key}")
async def delete_config(environment: str, service: str, key: str):
    """Delete a configuration."""
    success = config_service.delete_config(environment, service, key)
    if not success:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return {"message": "Configuration deleted"}


@app.post("/api/v1/feature-flags")
async def create_feature_flag(
    name: str,
    enabled: bool,
    description: Optional[str] = None,
    rules: Optional[list] = None,
    rollout_percentage: int = 100
):
    """Create a feature flag."""
    flag = config_service.set_feature_flag(
        name=name,
        enabled=enabled,
        description=description,
        rules=rules,
        rollout_percentage=rollout_percentage
    )
    return flag


@app.get("/api/v1/feature-flags")
async def list_feature_flags():
    """List all feature flags."""
    flags = config_service.get_all_feature_flags()
    return {"data": flags}


@app.post("/api/v1/feature-flags/{name}/evaluate")
async def evaluate_feature_flag(name: str, request: FeatureFlagEvaluateRequest):
    """Evaluate a feature flag for a user."""
    enabled = config_service.evaluate_feature_flag(
        flag_name=name,
        user_attributes=request.user_attributes
    )
    return {"flag": name, "enabled": enabled}


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "service": "config-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
