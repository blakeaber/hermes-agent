"""Artifact store for managing and persisting artifacts."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import json
import uuid
from datetime import datetime, timezone


@dataclass
class Artifact:
    """Represents a stored artifact with metadata."""
    id: str
    name: str
    content: Any
    artifact_type: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "artifact_type": self.artifact_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Artifact":
        """Create artifact from dictionary representation."""
        return cls(
            id=data["id"],
            name=data["name"],
            content=data["content"],
            artifact_type=data["artifact_type"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            metadata=data.get("metadata", {}),
        )


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ArtifactStore:
    """Manages storage and retrieval of artifacts."""

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize artifact store with optional storage path."""
        self.storage_path = storage_path or Path.home() / ".artifact_store"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._artifacts: Dict[str, Artifact] = {}
        self._load_artifacts()

    def _load_artifacts(self) -> None:
        """Load artifacts from storage."""
        store_file = self.storage_path / "artifacts.json"
        if store_file.exists():
            with open(store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for artifact_data in data:
                    artifact = Artifact.from_dict(artifact_data)
                    self._artifacts[artifact.id] = artifact

    def _save_artifacts(self) -> None:
        """Save artifacts to storage."""
        store_file = self.storage_path / "artifacts.json"
        artifacts_data = [artifact.to_dict() for artifact in self._artifacts.values()]
        with open(store_file, "w", encoding="utf-8") as f:
            json.dump(artifacts_data, f, indent=2)

    def create(
        self,
        name: str,
        content: Any,
        artifact_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """Create and store a new artifact."""
        artifact_id = str(uuid.uuid4())
        now = _utcnow_iso()
        artifact = Artifact(
            id=artifact_id,
            name=name,
            content=content,
            artifact_type=artifact_type,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._artifacts[artifact_id] = artifact
        self._save_artifacts()
        return artifact

    def get(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact by ID."""
        return self._artifacts.get(artifact_id)

    def list(self, artifact_type: Optional[str] = None) -> list[Artifact]:
        """List all artifacts, optionally filtered by type."""
        artifacts = list(self._artifacts.values())
        if artifact_type:
            artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
        return artifacts

    def update(
        self,
        artifact_id: str,
        content: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Artifact]:
        """Update an existing artifact."""
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return None

        if content is not None:
            artifact.content = content
        if metadata is not None:
            artifact.metadata.update(metadata)

        artifact.updated_at = _utcnow_iso()
        self._save_artifacts()
        return artifact

    def delete(self, artifact_id: str) -> bool:
        """Delete an artifact by ID."""
        if artifact_id in self._artifacts:
            del self._artifacts[artifact_id]
            self._save_artifacts()
            return True
        return False

    def clear(self) -> None:
        """Clear all artifacts from the store."""
        self._artifacts.clear()
        self._save_artifacts()
