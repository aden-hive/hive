"""Tool Service - MCP tool orchestration."""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
from datetime import datetime
import uuid

app = FastAPI(
    title="Tool Service",
    description="MCP tool orchestration service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tool registry
tools_db = {
    "web_search": {
        "id": "web_search",
        "name": "Web Search",
        "description": "Search the web for information",
        "parameters": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 10}
        }
    },
    "file_read": {
        "id": "file_read",
        "name": "Read File",
        "description": "Read file contents",
        "parameters": {
            "path": {"type": "string", "description": "File path"}
        }
    }
}


@app.get("/api/v1/tools")
async def list_tools():
    """List all available tools."""
    return {"data": list(tools_db.values())}


@app.get("/api/v1/tools/{tool_id}")
async def get_tool(tool_id: str):
    """Get tool by ID."""
    tool = tools_db.get(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@app.post("/api/v1/tools/{tool_id}/invoke")
async def invoke_tool(tool_id: str, params: Dict[str, Any]):
    """Invoke a tool."""
    tool = tools_db.get(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Simulate tool execution
    result = {
        "tool_id": tool_id,
        "params": params,
        "result": f"Tool {tool_id} executed with params {params}",
        "executed_at": datetime.utcnow().isoformat()
    }

    return result


@app.post("/api/v1/tools/register")
async def register_tool(tool: Dict[str, Any]):
    """Register a new tool."""
    tool_id = tool.get("id", str(uuid.uuid4()))
    tool["id"] = tool_id
    tools_db[tool_id] = tool
    return tool


@app.delete("/api/v1/tools/{tool_id}")
async def delete_tool(tool_id: str):
    """Delete a tool."""
    if tool_id not in tools_db:
        raise HTTPException(status_code=404, detail="Tool not found")
    del tools_db[tool_id]
    return {"message": "Tool deleted"}


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "service": "tool-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
