from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any

class GrafanaDashboard(BaseModel):
    uid: str
    title: str
    uri: str
    tags: list[str] = []
    isStarred: bool = False

class GrafanaAnnotation(BaseModel):
    id: int | None = None
    dashboardUID: str
    time: int
    text: str
    tags: list[str] = []

class GrafanaAlert(BaseModel):
    uid: str
    title: str
    state: str
    lastEvaluation: str | None = None

class PanelQueryRequest(BaseModel):
    dashboard_uid: str
    panel_id: int
    from_time: str = "now-1h"
    to_time: str = "now"
