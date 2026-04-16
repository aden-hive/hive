from pydantic import BaseModel, Field
from typing import List, Optional, Any

class GrafanaDashboard(BaseModel):
    uid: str
    title: str
    uri: str
    tags: List[str] = []
    isStarred: bool = False

class GrafanaAnnotation(BaseModel):
    id: Optional[int] = None
    dashboardUID: str
    time: int
    text: str
    tags: List[str] = []

class GrafanaAlert(BaseModel):
    uid: str
    title: str
    state: str
    lastEvaluation: Optional[str] = None

class PanelQueryRequest(BaseModel):
    dashboard_uid: str
    panel_id: int
    from_time: str = "now-1h"
    to_time: str = "now"
