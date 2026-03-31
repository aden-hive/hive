"""Provider-specific model configurations with descriptions and capability detection."""

from typing import Dict, List, TypedDict, Optional
import os
import json
from pathlib import Path

class ModelInfo(TypedDict):
    name: str
    description: str
    api_name: str
    tier: str  # "free" or "paid"
    speed: str  # "fast", "balanced", "slow"
    quality: str  # "basic", "good", "better", "best"
    max_tokens: int
    supports_streaming: bool
    supports_tools: bool
    supports_json_mode: bool

# Provider model definitions
PROVIDER_MODELS: Dict[str, List[ModelInfo]] = {
    "anthropic": [
        {
            "name": "Claude 3.5 Haiku",
            "description": "Fastest responses, lowest cost",
            "api_name": "claude-3-5-haiku-20241022",
            "tier": "paid",
            "speed": "fast",
            "quality": "good",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Claude 3.5 Sonnet",
            "description": "Balanced speed and quality",
            "api_name": "claude-3-5-sonnet-20241022",
            "tier": "paid",
            "speed": "balanced",
            "quality": "better",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Claude 3.5 Opus",
            "description": "Highest quality, slower responses",
            "api_name": "claude-3-opus-20240229",
            "tier": "paid",
            "speed": "slow",
            "quality": "best",
            "max_tokens": 32768,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Claude 3.7 Sonnet",
            "description": "Latest model, improved reasoning",
            "api_name": "claude-3-7-sonnet-20250219",
            "tier": "paid",
            "speed": "balanced",
            "quality": "best",
            "max_tokens": 16384,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        }
    ],
    
    "openai": [
        {
            "name": "GPT-3.5 Turbo",
            "description": "Fast, efficient, cost-effective",
            "api_name": "gpt-3.5-turbo",
            "tier": "paid",
            "speed": "fast",
            "quality": "basic",
            "max_tokens": 16384,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "GPT-4 Turbo",
            "description": "Balanced performance and cost",
            "api_name": "gpt-4-turbo-preview",
            "tier": "paid",
            "speed": "balanced",
            "quality": "good",
            "max_tokens": 128000,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "GPT-4o",
            "description": "Latest, multimodal, best quality",
            "api_name": "gpt-4o",
            "tier": "paid",
            "speed": "balanced",
            "quality": "best",
            "max_tokens": 128000,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "GPT-4.5 Preview",
            "description": "Preview of next-gen model",
            "api_name": "gpt-4.5-preview",
            "tier": "paid",
            "speed": "slow",
            "quality": "best",
            "max_tokens": 128000,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        }
    ],
    
    "gemini": [
        {
            "name": "Gemini 2.5 Flash",
            "description": "Fast, efficient, free tier available",
            "api_name": "gemini-2.5-flash",
            "tier": "free",
            "speed": "fast",
            "quality": "good",
            "max_tokens": 1048576,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Gemini 2.5 Pro",
            "description": "Best quality",
            "api_name": "gemini-2.5-pro",
            "tier": "Paid",
            "speed": "Balance",
            "quality": "Best",
            "max_tokens": 1048576,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Gemini 3 Flash Preview",
            "description": "Better reasoning, higher quality",
            "api_name": "gemini-3-flash-preview",
            "tier": "paid",
            "speed": "balanced",
            "quality": "better",
            "max_tokens": 1048576,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Gemini 2.5 Pro",
            "description": "Latest, best quality",
            "api_name": "gemini-2.5-pro-preview",
            "tier": "paid",
            "speed": "slow",
            "quality": "best",
            "max_tokens": 32768,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        }
    ],
    
    "groq": [
        {
            "name": "Llama 3.3 70B",
            "description": "Fast inference, high quality",
            "api_name": "llama-3.3-70b-versatile",
            "tier": "free",
            "speed": "fast",
            "quality": "good",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Mixtral 8x7B",
            "description": "Efficient, good performance",
            "api_name": "mixtral-8x7b-32768",
            "tier": "free",
            "speed": "fast",
            "quality": "good",
            "max_tokens": 32768,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Gemma 2 9B",
            "description": "Lightweight, fast",
            "api_name": "gemma2-9b-it",
            "tier": "free",
            "speed": "fast",
            "quality": "basic",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        }
    ],
    
    "cerebras": [
        {
            "name": "Llama 3.1 8B",
            "description": "Fast, lightweight",
            "api_name": "llama3.1-8b",
            "tier": "free",
            "speed": "fast",
            "quality": "basic",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        },
        {
            "name": "Llama 3.1 70B",
            "description": "Higher quality, still fast",
            "api_name": "llama3.1-70b",
            "tier": "free",
            "speed": "fast",
            "quality": "good",
            "max_tokens": 8192,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_mode": True
        }
    ]
}

def get_provider_models(provider_id: str) -> List[ModelInfo]:
    """Get available models for a specific provider."""
    return PROVIDER_MODELS.get(provider_id, [])

def get_model_info(provider_id: str, api_name: str) -> Optional[ModelInfo]:
    """Get model info by API name."""
    models = get_provider_models(provider_id)
    for model in models:
        if model["api_name"] == api_name:
            return model
    return None

def format_model_menu(provider_id: str) -> str:
    """Format model selection menu for a provider with icons."""
    models = get_provider_models(provider_id)
    if not models:
        return f"No predefined models for {provider_id}. You can enter a custom model name."
    
    menu = f"\nAvailable {provider_id.title()} Models:\n"
    menu += "-" * 60 + "\n"
    
    for idx, model in enumerate(models, 1):
        # Icons for tier
        tier_icon = "🆓" if model["tier"] == "free" else "💰"
        
        # Icons for speed
        speed_icon = {
            "fast": "⚡",
            "balanced": "⚖️", 
            "slow": "🐢"
        }.get(model["speed"], "")
        
        # Icons for quality
        quality_icon = {
            "basic": "🔹",
            "good": "🔸",
            "better": "⭐",
            "best": "🌟🌟"
        }.get(model["quality"], "")
        
        menu += f"\n{idx}. {model['name']} {tier_icon}{speed_icon}{quality_icon}"
        menu += f"\n   {model['description']}"
        menu += f"\n   API: {model['api_name']} | Max tokens: {model['max_tokens']}"
        menu += f"\n   Features: "
        features = []
        if model["supports_streaming"]:
            features.append("streaming")
        if model["supports_tools"]:
            features.append("tools")
        if model["supports_json_mode"]:
            features.append("JSON mode")
        menu += ", ".join(features)
        menu += "\n"
    
    menu += "\n" + "-" * 60
    menu += "\n0. Enter custom model name"
    return menu

def get_model_display_name(provider_id: str, api_name: str) -> str:
    """Get user-friendly display name for a model."""
    model_info = get_model_info(provider_id, api_name)
    if model_info:
        return model_info["name"]
    return api_name

def get_model_capabilities(provider_id: str, api_name: str) -> Dict[str, bool]:
    """Get capability flags for a model."""
    model_info = get_model_info(provider_id, api_name)
    if model_info:
        return {
            "streaming": model_info["supports_streaming"],
            "tools": model_info["supports_tools"],
            "json_mode": model_info["supports_json_mode"]
        }
    # Default capabilities for unknown models
    return {
        "streaming": True,
        "tools": True,
        "json_mode": True
    }