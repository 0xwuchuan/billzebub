from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.config import Environment, Settings
from billzebub.persistence.database import Database


@pytest.mark.integration
def test_ready_with_migrated_postgres_and_writable_artifact_store(
    database: Database,
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path,
            development_identity="developer@example.test",
        ),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {"postgres": "ok", "artifact_store": "ok"},
    }
