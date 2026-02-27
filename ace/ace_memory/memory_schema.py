"""Memory schema definitions using Pydantic for strict typing."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field, field_validator


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

    def __hash__(self) -> int:
        """Enable hashing for deduplication (using entry ID)."""
        return hash(self.id)

    @computed_field  # type: ignore[misc]
    @property
    def age_seconds(self) -> float:
        """Compute age of memory entry in seconds."""
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    @computed_field  # type: ignore[misc]
    @property
    def is_fresh(self) -> bool:
        """Check if memory is fresh (less than 24 hours old)."""
        return self.age_seconds < 86400.0

    @computed_field  # type: ignore[misc]
    @property
    def access_rate_per_day(self) -> float:
        """Compute access frequency per day."""
        age_days = max(self.age_seconds / 86400.0, 0.01)  # Avoid division by zero
        return self.access_count / age_days
