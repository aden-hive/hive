"""Agent Service - Agent execution and management."""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
from datetime import datetime
import uuid

app = FastAPI(
    title="Agent Service",
    description="Agent execution and management service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (replace with database)
agents_db = {}
agent_runs_db = {}


class AgentCreate:
    def __init__(self, name: str, goal: str, nodes: List[Dict] = None):
        self.name = name
        self.goal = goal
        self.nodes = nodes or []


@app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(agent_data: AgentCreate):
    """Create a new agent."""
    agent_id = str(uuid.uuid4())

    agent = {
        "id": agent_id,
        "name": agent_data.name,
        "goal": agent_data.goal,
        "nodes": agent_data.nodes,
        "created_at": datetime.utcnow().isoformat(),
        "status": "created"
    }

    agents_db[agent_id] = agent
    return agent


@app.get("/api/v1/agents")
async def list_agents(limit: int = 20, offset: int = 0):
    """List all agents."""
    agents = list(agents_db.values())
    return {
        "data": agents[offset:offset + limit],
        "total": len(agents),
        "limit": limit,
        "offset": offset
    }


@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get agent by ID."""
    agent = agents_db.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.post("/api/v1/agents/{agent_id}/execute")
async def execute_agent(agent_id: str, params: Dict[str, Any] = None):
    """Execute an agent."""
    agent = agents_db.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run_id = str(uuid.uuid4())
    run = {
        "run_id": run_id,
        "agent_id": agent_id,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "params": params or {}
    }

    agent_runs_db[run_id] = run

    # Simulate execution
    run["status"] = "completed"
    run["completed_at"] = datetime.utcnow().isoformat()
    run["result"] = {"success": True, "output": "Agent executed successfully"}

    return run


@app.get("/api/v1/agents/{agent_id}/runs")
async def list_agent_runs(agent_id: str):
    """List agent execution runs."""
    runs = [r for r in agent_runs_db.values() if r["agent_id"] == agent_id]
    return {"data": runs}


@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent."""
    if agent_id not in agents_db:
        raise HTTPException(status_code=404, detail="Agent not found")
    del agents_db[agent_id]
    return {"message": "Agent deleted"}


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "service": "agent-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
