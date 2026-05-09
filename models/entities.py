from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    feature = "feature"
    workflow = "workflow"
    bug = "bug"
    persona = "persona"
    integration = "integration"


class Entity(BaseModel):
    model_config = {"frozen": False}

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    name: str
    type: EntityType
    canonical: bool = Field(default=True)

    def to_neo4j_props(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": self.tenant_id,
            "name": self.name,
            "type": self.type.value,
            "canonical": self.canonical,
        }
