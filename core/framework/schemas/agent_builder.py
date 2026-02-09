from pydantic import BaseModel


class CreateSessionResponse(BaseModel):
    session_id: str
    name: str
    status: str
    persisted: bool
