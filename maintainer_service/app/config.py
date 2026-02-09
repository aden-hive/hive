"""Configuration settings for the Maintainer Service."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # GitHub
    github_token: str
    github_repo_owner: str
    github_repo_name: str
    github_webhook_secret: str | None = None
    
    # LLM
    openai_api_key: str
    openai_model: str = "gpt-4.1-nano"
    
    # Database
    # Resolve paths relative to the project root (maintainer_service/)
    _project_root = Path(__file__).resolve().parent.parent
    chroma_persist_directory: str = str(_project_root / "data" / "chroma")
    sqlite_db_path: str = str(_project_root / "data" / "state.db")
    
    # Scheduler
    analysis_interval_minutes: int = 60
    lookback_window_minutes: int = 65  # How far back to look for issues
    
    # Notification
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    notification_email: str | None = None
    
    slack_webhook_url: str | None = None
    
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),  # Try current dir first, then parent
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )


settings = Settings()
