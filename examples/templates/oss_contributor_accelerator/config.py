"""Configuration for OSS Contributor Accelerator agent."""

from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Config:
    """Runtime configuration for OSS Contributor Accelerator."""
    
    # LLM settings
    llm_model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4000
    
    # Checkpoint settings
    checkpoints_enabled: bool = True
    checkpoint_dir: str = "./checkpoints"
    
    # Tool settings
    web_search_max_results: int = 10
    web_scrape_timeout: int = 30
    
    # Agent-specific settings
    max_issues_to_analyze: int = 20
    max_selected_issues: int = 3

# Default configuration
default_config = Config()

# Agent metadata
metadata = {
    "name": "OSS Contributor Accelerator",
    "description": "Systematically identify and execute high-impact open source contributions",
    "version": "1.0.0",
    "author": "Hive Templates",
    "tags": ["oss", "contributions", "github", "development", "accelerator"],
    "category": "development",
    "input_schema": {
        "type": "object",
        "properties": {
            "initial_request": {
                "type": "string",
                "description": "Initial request describing what you want to contribute to",
            }
        },
        "required": ["initial_request"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "contribution_brief": {
                "type": "string",
                "description": "Path to generated contribution brief with implementation plan",
            }
        },
        "required": ["contribution_brief"],
    },
}
