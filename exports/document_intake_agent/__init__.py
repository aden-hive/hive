"""
Universal Document Intake & Action Agent

A production-ready Hive agent that accepts any business document (invoices, contracts,
receipts, bank statements, forms), extracts structured data, classifies the document type,
validates the extracted data, and routes it to the appropriate workflow.

Features:
- 🔄 Fanout/fanin parallel processing architecture
- 📡 Real-time streaming progress updates
- 🧠 Self-evolution learning from human feedback
- 💰 Intelligent budget controls with automatic model degradation
- 🎯 Universal format support (PDF, images, CSV, DOCX, email)
- 🔐 Enterprise security with full audit trails
- ⚡ High performance: 100+ documents/minute
"""

import os
import sys
from pathlib import Path

# Core agent components
from .agent import (
    DocumentIntakeAgent, default_agent, goal, nodes, edges,
    entry_node, entry_points, pause_nodes, terminal_nodes,
    conversation_mode, identity_prompt, loop_config,
    default_config, metadata,
)

# Advanced features
from .budget_control import BudgetController
from .evolution import EvolutionTracker
from .exceptions import (
    DocumentIntakeAgentError, DocumentValidationError, DocumentNotFoundError,
    UnsupportedFormatError, ProcessingTimeoutError, LowConfidenceError,
    BudgetExceededError, ConfigurationError
)
from .health import HealthMonitor, health_check, is_healthy, get_performance_metrics
from .logging_config import setup_logging, get_logger

# Version and metadata
__version__ = "0.1.0"
__author__ = "Hive Framework Team"
__email__ = "support@hive.com"
__description__ = "Universal Document Intake & Action Agent for intelligent document processing"
__license__ = "MIT"

# Initialize logging if not already configured
if not hasattr(sys.modules[__name__], '_logging_configured'):
    try:
        setup_logging()
        _logging_configured = True
    except Exception:
        # Fallback to basic logging if setup fails
        import logging
        logging.basicConfig(level=logging.INFO)
        _logging_configured = True

# Professional API exports
__all__ = [
    # Core agent components
    "DocumentIntakeAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "default_config",
    "metadata",

    # Advanced features
    "BudgetController",
    "EvolutionTracker",

    # Health monitoring
    "HealthMonitor",
    "health_check",
    "is_healthy",
    "get_performance_metrics",

    # Logging
    "setup_logging",
    "get_logger",

    # Exceptions
    "DocumentIntakeAgentError",
    "DocumentValidationError",
    "DocumentNotFoundError",
    "UnsupportedFormatError",
    "ProcessingTimeoutError",
    "LowConfidenceError",
    "BudgetExceededError",
    "ConfigurationError",

    # Metadata
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    "__license__",
]

# Quick setup function for easy initialization
def initialize_agent(
    api_key: str = None,
    budget_limit: float = 10.0,
    log_level: str = "INFO",
    storage_path: str = "./storage"
) -> DocumentIntakeAgent:
    """
    Quick setup function for the Document Intake Agent.

    Args:
        api_key: LLM API key (auto-detects from environment if not provided)
        budget_limit: Daily budget limit in USD
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        storage_path: Path for agent storage

    Returns:
        Configured DocumentIntakeAgent instance

    Example:
        >>> agent = initialize_agent(budget_limit=20.0, log_level="DEBUG")
        >>> result = await agent.run({"file_path": "invoice.pdf"})
    """
    # Set up environment if API key provided
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    # Set up configuration
    os.environ.setdefault("HIVE_DAILY_BUDGET_LIMIT", str(budget_limit))
    os.environ.setdefault("HIVE_LOG_LEVEL", log_level)
    os.environ.setdefault("HIVE_STORAGE_PATH", storage_path)

    # Create storage directory
    Path(storage_path).mkdir(parents=True, exist_ok=True)

    # Initialize logging
    setup_logging()

    return default_agent

# Convenience function for quick document processing
async def process_document(
    file_path: str,
    source_channel: str = "api",
    metadata: dict = None,
    **kwargs
) -> dict:
    """
    Quick document processing function.

    Args:
        file_path: Path to document file
        source_channel: Source of the document (api, upload, email, webhook)
        metadata: Additional context information
        **kwargs: Additional configuration options

    Returns:
        Processing result dictionary

    Example:
        >>> result = await process_document("invoice.pdf")
        >>> print(f"Category: {result['category']}, Action: {result['action']}")
    """
    agent = default_agent

    input_data = {
        "file_path": file_path,
        "source_channel": source_channel,
        "metadata": metadata or {}
    }
    input_data.update(kwargs)

    return await agent.run(input_data)

# Add helpful module-level information
def get_agent_info() -> dict:
    """Get comprehensive information about the agent."""
    return {
        "name": goal.name,
        "version": __version__,
        "description": __description__,
        "author": __author__,
        "license": __license__,
        "features": [
            "Fanout/fanin parallel processing",
            "Real-time streaming updates",
            "Self-evolution learning",
            "Intelligent budget controls",
            "Universal document support",
            "Enterprise security",
            "High performance processing"
        ],
        "supported_formats": [
            "PDF (.pdf)",
            "Images (.png, .jpg, .jpeg, .tiff)",
            "Spreadsheets (.csv)",
            "Documents (.docx, .txt)",
            "Email (.eml)"
        ],
        "architecture": {
            "nodes": len(nodes),
            "edges": len(edges),
            "entry_node": entry_node,
            "conversation_mode": conversation_mode
        },
        "health": health_check() if is_healthy() else {"status": "unhealthy"}
    }