"""Storage Service - Data persistence and management."""

from fastapi import FastAPI, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
from datetime import datetime
import uuid

app = FastAPI(
    title="Storage Service",
    description="Data persistence and management service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage (in-memory, replace with S3/database)
storage_db = {}


@app.post("/api/v1/storage", status_code=status.HTTP_201_CREATED)
async def store_data(key: str, data: Dict[str, Any]):
    """Store data."""
    storage_db[key] = {
        "key": key,
        "data": data,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    return storage_db[key]


@app.get("/api/v1/storage/{key}")
async def get_data(key: str):
    """Get data by key."""
    if key not in storage_db:
        raise HTTPException(status_code=404, detail="Data not found")
    return storage_db[key]


@app.put("/api/v1/storage/{key}")
async def update_data(key: str, data: Dict[str, Any]):
    """Update data."""
    if key not in storage_db:
        raise HTTPException(status_code=404, detail="Data not found")

    storage_db[key]["data"] = data
    storage_db[key]["updated_at"] = datetime.utcnow().isoformat()
    return storage_db[key]


@app.delete("/api/v1/storage/{key}")
async def delete_data(key: str):
    """Delete data."""
    if key not in storage_db:
        raise HTTPException(status_code=404, detail="Data not found")
    del storage_db[key]
    return {"message": "Data deleted"}


@app.post("/api/v1/storage/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file."""
    file_id = str(uuid.uuid4())

    # Read file content
    content = await file.read()

    storage_db[file_id] = {
        "file_id": file_id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "uploaded_at": datetime.utcnow().isoformat()
    }

    return storage_db[file_id]


@app.get("/api/v1/storage")
async def list_storage(limit: int = 100):
    """List all stored data."""
    items = list(storage_db.values())[:limit]
    return {"data": items, "total": len(items)}


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "service": "storage-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
