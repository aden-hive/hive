"""Provider capability detection to validate model access and features."""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
from litellm import completion

logger = logging.getLogger(__name__)

class CapabilityDetector:
    """Detect and validate model capabilities."""
    
    def __init__(self, provider: str, model: str, api_key: str):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self._full_model = model if provider == "gemini" else f"{provider}/{model}"
    
    async def check_access(self) -> Tuple[bool, Optional[str]]:
        """Check if the API key has access to the model."""
        try:
            response = await asyncio.to_thread(
                completion,
                model=self._full_model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
                api_key=self.api_key
            )
            if response and response.choices:
                return True, None
            return False, "No response from model"
        except Exception as e:
            error_str = str(e).lower()
            if "access" in error_str or "permission" in error_str:
                return False, f"No access to model: {e}"
            if "invalid" in error_str or "auth" in error_str:
                return False, f"Invalid API key: {e}"
            if "rate" in error_str:
                return True, "Rate limited but key is valid"
            # Other errors might be temporary
            return True, f"Model may be accessible (error: {e})"
    
    async def detect_streaming_support(self) -> bool:
        """Detect if model supports streaming."""
        try:
            response = await asyncio.to_thread(
                completion,
                model=self._full_model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
                stream=True,
                api_key=self.api_key
            )
            # If we get here without error, streaming is supported
            return True
        except Exception as e:
            logger.debug(f"Streaming test failed: {e}")
            return False
    
    async def detect_tools_support(self) -> bool:
        """Detect if model supports tool calling."""
        try:
            tools = [{
                "type": "function",
                "function": {
                    "name": "test",
                    "description": "Test function",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "test": {"type": "string"}
                        }
                    }
                }
            }]
            response = await asyncio.to_thread(
                completion,
                model=self._full_model,
                messages=[{"role": "user", "content": "test"}],
                tools=tools,
                max_tokens=5,
                api_key=self.api_key
            )
            # If we get here without error, tools are supported
            return True
        except Exception as e:
            logger.debug(f"Tools test failed: {e}")
            return False
    
    async def detect_json_mode_support(self) -> bool:
        """Detect if model supports JSON mode."""
        try:
            response = await asyncio.to_thread(
                completion,
                model=self._full_model,
                messages=[{"role": "user", "content": 'Return JSON: {"test": "value"}'}],
                response_format={"type": "json_object"},
                max_tokens=10,
                api_key=self.api_key
            )
            # If we get here without error, JSON mode is supported
            return True
        except Exception as e:
            logger.debug(f"JSON mode test failed: {e}")
            return False
    
    async def detect_all_capabilities(self) -> Dict[str, Any]:
        """Detect all model capabilities."""
        access_ok, access_msg = await self.check_access()
        
        if not access_ok:
            return {
                "accessible": False,
                "message": access_msg,
                "streaming": False,
                "tools": False,
                "json_mode": False
            }
        
        # Run capability tests in parallel
        streaming_test = self.detect_streaming_support()
        tools_test = self.detect_tools_support()
        json_test = self.detect_json_mode_support()
        
        streaming, tools, json_mode = await asyncio.gather(
            streaming_test, tools_test, json_test
        )
        
        return {
            "accessible": True,
            "message": access_msg,
            "streaming": streaming,
            "tools": tools,
            "json_mode": json_mode
        }

async def validate_model_config(provider: str, model: str, api_key: str) -> Dict[str, Any]:
    """Validate a complete model configuration."""
    detector = CapabilityDetector(provider, model, api_key)
    return await detector.detect_all_capabilities()

def print_capabilities_report(capabilities: Dict[str, Any]) -> str:
    """Format capabilities for display."""
    if not capabilities.get("accessible", False):
        return f"❌ Model not accessible: {capabilities.get('message', 'Unknown error')}"
    
    lines = []
    lines.append(f"✅ Model accessible")
    lines.append(f"   Streaming: {'✅' if capabilities['streaming'] else '❌'}")
    lines.append(f"   Tool calling: {'✅' if capabilities['tools'] else '❌'}")
    lines.append(f"   JSON mode: {'✅' if capabilities['json_mode'] else '❌'}")
    
    if capabilities.get('message'):
        lines.append(f"   Note: {capabilities['message']}")
    
    return "\n".join(lines)