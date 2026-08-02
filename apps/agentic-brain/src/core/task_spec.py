from pydantic import BaseModel, Field, HttpUrl
from typing import List, Dict, Any
from uuid import UUID4, uuid4

class AgentSpec(BaseModel):
    name: str
    input: Dict[str, Any] = {}

class TaskSpec(BaseModel):
    task_id: UUID4 = Field(default_factory=uuid4)
    tenant_id: str
    agents: List[AgentSpec]
    callback_url: HttpUrl | None = None
    priority: str = "normal"
    expires_at: Any | None = None
