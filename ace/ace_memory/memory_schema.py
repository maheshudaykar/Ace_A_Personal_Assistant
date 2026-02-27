"""Memory schema definitions using Pydantic for strict typing."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class MemoryType(str, Enum):
    """Memory entry types."""

    WORKING = "working"
    EPISODIC = "episodic"
    CONSOLIDATED = "consolidated"


class MemoryEntry(BaseModel):
    """Strict schema for memory entries."""


    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str
    content: str
    embedding: Optional[List[float]] = None
    importance_score: float = Field(ge=0.0, le=1.0, default=0.5)
    access_count: int = Field(ge=0, default=0)
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    memory_type: MemoryType = MemoryType.EPISODIC
    archived: bool = False

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content cannot be empty")
        return v

    @field_validator("task_id")
    @classmethod
    def task_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("task_id cannot be empty")
        return v

    @field_validator("embedding")
    @classmethod
    def embedding_dimension_valid(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is not None and len(v) == 0:
            raise ValueError("embedding must be None or non-empty list")
        return v

    def update_access(self) -> None:
        """Update access tracking."""
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)
