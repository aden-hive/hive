"""Workflow Service - Advanced workflow orchestration."""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
from datetime import datetime
import uuid
import asyncio

import sys
sys.path.append("../../core")
from framework.workflow.dag import DAG, Task, TaskState
from framework.workflow.executor import WorkflowExecutor

app = FastAPI(
    title="Workflow Service",
    description="Advanced workflow orchestration service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Workflow storage
workflows_db = {}


@app.post("/api/v1/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(workflow_data: Dict[str, Any]):
    """Create a new workflow."""
    workflow_id = str(uuid.uuid4())

    workflow = {
        "id": workflow_id,
        "name": workflow_data.get("name"),
        "description": workflow_data.get("description", ""),
        "tasks": workflow_data.get("tasks", []),
        "created_at": datetime.utcnow().isoformat()
    }

    workflows_db[workflow_id] = workflow
    return workflow


@app.get("/api/v1/workflows")
async def list_workflows():
    """List all workflows."""
    return {"data": list(workflows_db.values())}


@app.get("/api/v1/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get workflow by ID."""
    workflow = workflows_db.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@app.post("/api/v1/workflows/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, params: Dict[str, Any] = None):
    """Execute a workflow."""
    workflow = workflows_db.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Create DAG from workflow
    dag = DAG(dag_id=workflow_id, description=workflow.get("description", ""))

    # Add tasks to DAG
    for task_data in workflow.get("tasks", []):
        task = Task(
            id=task_data["id"],
            name=task_data["name"],
            dependencies=task_data.get("dependencies", []),
            params=task_data.get("params", {})
        )
        dag.add_task(task)

    # Execute workflow
    executor = WorkflowExecutor(dag)
    result = await executor.execute()

    return {
        "workflow_id": workflow_id,
        "execution_id": str(uuid.uuid4()),
        "status": "completed",
        "result": result
    }


@app.delete("/api/v1/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    if workflow_id not in workflows_db:
        raise HTTPException(status_code=404, detail="Workflow not found")
    del workflows_db[workflow_id]
    return {"message": "Workflow deleted"}


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "service": "workflow-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)
