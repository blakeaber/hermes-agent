"""Tests for artifact store functionality."""

import time
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.artifact_store import Artifact, ArtifactStore


class TestArtifact:
    """Tests for Artifact class."""

    def test_artifact_creation(self):
        """Test creating an artifact."""
        artifact = Artifact(
            id="test-id",
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        assert artifact.id == "test-id"
        assert artifact.name == "test-artifact"
        assert artifact.content == {"key": "value"}
        assert artifact.artifact_type == "test"

    def test_artifact_to_dict(self):
        """Test converting artifact to dictionary."""
        artifact = Artifact(
            id="test-id",
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            metadata={"custom": "data"},
        )
        artifact_dict = artifact.to_dict()
        assert artifact_dict["id"] == "test-id"
        assert artifact_dict["name"] == "test-artifact"
        assert artifact_dict["metadata"] == {"custom": "data"}

    def test_artifact_from_dict(self):
        """Test creating artifact from dictionary."""
        data = {
            "id": "test-id",
            "name": "test-artifact",
            "content": {"key": "value"},
            "artifact_type": "test",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "metadata": {"custom": "data"},
        }
        artifact = Artifact.from_dict(data)
        assert artifact.id == "test-id"
        assert artifact.name == "test-artifact"
        assert artifact.metadata == {"custom": "data"}


class TestArtifactStore:
    """Tests for ArtifactStore class."""

    @pytest.fixture
    def temp_store(self):
        """Create a temporary artifact store."""
        with TemporaryDirectory() as tmpdir:
            store = ArtifactStore(storage_path=Path(tmpdir))
            yield store

    def test_store_creation(self, temp_store):
        """Test creating an artifact store."""
        assert temp_store.storage_path.exists()

    def test_create_artifact(self, temp_store):
        """Test creating an artifact in the store."""
        artifact = temp_store.create(
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
        )
        assert artifact.id is not None
        assert artifact.name == "test-artifact"
        assert artifact.content == {"key": "value"}
        assert artifact.artifact_type == "test"

    def test_get_artifact(self, temp_store):
        """Test retrieving an artifact from the store."""
        created = temp_store.create(
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
        )
        retrieved = temp_store.get(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "test-artifact"

    def test_get_nonexistent_artifact(self, temp_store):
        """Test retrieving a nonexistent artifact."""
        result = temp_store.get("nonexistent-id")
        assert result is None

    def test_list_artifacts(self, temp_store):
        """Test listing all artifacts."""
        temp_store.create(
            name="artifact-1",
            content={"data": 1},
            artifact_type="type-a",
        )
        temp_store.create(
            name="artifact-2",
            content={"data": 2},
            artifact_type="type-b",
        )
        artifacts = temp_store.list()
        assert len(artifacts) == 2

    def test_list_artifacts_by_type(self, temp_store):
        """Test listing artifacts filtered by type."""
        temp_store.create(
            name="artifact-1",
            content={"data": 1},
            artifact_type="type-a",
        )
        temp_store.create(
            name="artifact-2",
            content={"data": 2},
            artifact_type="type-b",
        )
        artifacts = temp_store.list(artifact_type="type-a")
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "type-a"

    def test_update_artifact(self, temp_store):
        """Test updating an artifact."""
        created = temp_store.create(
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
        )
        # Capture the original updated_at before mutation since update() mutates in place
        original_updated_at = created.updated_at
        # Sleep to ensure the timestamp advances
        time.sleep(0.05)
        updated = temp_store.update(
            created.id,
            content={"key": "updated-value"},
        )
        assert updated is not None
        assert updated.content == {"key": "updated-value"}
        assert updated.updated_at > original_updated_at

    def test_update_artifact_metadata(self, temp_store):
        """Test updating artifact metadata."""
        created = temp_store.create(
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
            metadata={"version": 1},
        )
        updated = temp_store.update(
            created.id,
            metadata={"version": 2},
        )
        assert updated is not None
        assert updated.metadata["version"] == 2

    def test_update_nonexistent_artifact(self, temp_store):
        """Test updating a nonexistent artifact."""
        result = temp_store.update("nonexistent-id", content={"key": "value"})
        assert result is None

    def test_delete_artifact(self, temp_store):
        """Test deleting an artifact."""
        created = temp_store.create(
            name="test-artifact",
            content={"key": "value"},
            artifact_type="test",
        )
        deleted = temp_store.delete(created.id)
        assert deleted is True
        assert temp_store.get(created.id) is None

    def test_delete_nonexistent_artifact(self, temp_store):
        """Test deleting a nonexistent artifact."""
        result = temp_store.delete("nonexistent-id")
        assert result is False

    def test_clear_artifacts(self, temp_store):
        """Test clearing all artifacts."""
        temp_store.create(
            name="artifact-1",
            content={"data": 1},
            artifact_type="test",
        )
        temp_store.create(
            name="artifact-2",
            content={"data": 2},
            artifact_type="test",
        )
        temp_store.clear()
        artifacts = temp_store.list()
        assert len(artifacts) == 0

    def test_persistence(self):
        """Test that artifacts persist across store instances."""
        with TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir)
            store1 = ArtifactStore(storage_path=storage_path)
            created = store1.create(
                name="persistent-artifact",
                content={"key": "value"},
                artifact_type="test",
            )

            store2 = ArtifactStore(storage_path=storage_path)
            retrieved = store2.get(created.id)
            assert retrieved is not None
            assert retrieved.name == "persistent-artifact"
            assert retrieved.content == {"key": "value"}
