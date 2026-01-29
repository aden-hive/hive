# In test_mcp_server.py, update the routes to match the MCP server API
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import json

app = FastAPI()

# MCP Server Routes
class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]

class ToolRequest(BaseModel):
    input: Dict[str, Any]

# Mock tools
TOOLS = {
    "test_tool": ToolDefinition(
        name="test_tool",
        description="A test tool that echoes back input",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo back"}
            },
            "required": ["message"]
        }
    )
}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

@app.post("/mcp/v1")
async def list_tools():
    """List all available tools (MCP v1 API)"""
    return {
        "result": {
            "tools": list(TOOLS.values())  # Wrap in the expected format
        }
    }

@app.post("/mcp/v1/tools/{tool_name}")
async def execute_tool(tool_name: str, request: Dict[str, Any]):
    """Execute a tool (MCP v1 API)"""
    if tool_name not in TOOLS:
        raise HTTPException(status_code=404, detail="Tool not found")

    # For testing, just echo back the input
    return [{
        "text": f"Echo from {tool_name}: {request.get('input', {}).get('message', 'No message')}",
        "status": "success"
    }]

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the MCP server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_server()
