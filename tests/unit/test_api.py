from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.categories import CategoryRecord
from billzebub.config import Settings


class FakeCategories:
    def __init__(self) -> None:
        self.records: list[CategoryRecord] = []

    def list(self) -> tuple[CategoryRecord, ...]:
        return tuple(self.records)

    def create(self, name: str, *, parent_id: UUID | None = None) -> CategoryRecord:
        record = CategoryRecord(id=uuid4(), name=name, parent_id=parent_id, active=True)
        self.records.append(record)
        return record


class FakeDatabase:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.closed = False

    def ping(self) -> None:
        if not self.available:
            raise RuntimeError("database details must remain private")

    def close(self) -> None:
        self.closed = True


def test_health_resources_report_dependencies_without_driver_details(tmp_path: Path) -> None:
    database = FakeDatabase(available=False)
    app = create_app(Settings(artifact_root=tmp_path), database)

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {"postgres": "unavailable", "artifact_store": "ok"},
    }
    assert "private" not in response.text
    assert database.closed is True


def test_production_web_root_serves_the_built_spa_without_shadowing_api_routes(
    tmp_path: Path,
) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<main>Billzebub</main>", encoding="utf-8")
    app = create_app(
        Settings(artifact_root=tmp_path / "artifacts", web_root=web_root), FakeDatabase()
    )

    with TestClient(app) as client:
        homepage = client.get("/")
        health = client.get("/health/live")

    assert homepage.status_code == 200
    assert homepage.text == "<main>Billzebub</main>"
    assert health.json() == {"status": "ok"}


def test_owner_resource_uses_loopback_development_identity(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            artifact_root=tmp_path,
            development_identity="developer@example.test",
        ),
        FakeDatabase(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/whoami")

    assert response.status_code == 200
    assert response.json() == {
        "login": "developer@example.test",
        "name": "developer@example.test",
    }


def test_owner_resource_accepts_allowlisted_tailscale_headers(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            artifact_root=tmp_path,
            trust_tailscale_headers=True,
            tailscale_allowed_logins=("owner@example.test",),
        ),
        FakeDatabase(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/whoami",
            headers={
                "Tailscale-User-Login": "owner@example.test",
                "Tailscale-User-Name": "Owner",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"login": "owner@example.test", "name": "Owner"}


def test_owner_category_mutations_require_browser_origin_json_and_csrf(tmp_path: Path) -> None:
    categories = FakeCategories()
    app = create_app(
        Settings(
            artifact_root=tmp_path,
            development_identity="developer@example.test",
        ),
        FakeDatabase(),
        category_catalog=categories,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        listed = client.get("/api/v1/categories")
        blocked = client.post("/api/v1/categories", json={"name": "Synthetic Food"})
        created = client.post(
            "/api/v1/categories",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={"name": "Synthetic Food"},
        )

    assert listed.status_code == 200
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "browser_mutation_forbidden"
    assert created.status_code == 201
    assert created.json()["name"] == "Synthetic Food"
    assert len(categories.records) == 1


def test_import_resources_are_documented_and_fail_closed_without_identity(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(artifact_root=tmp_path), FakeDatabase())

    assert "/api/v1/imports" in app.openapi()["paths"]
    assert "/api/v1/imports/{extraction_id}" in app.openapi()["paths"]
    assert "/api/v1/statement-coverage" in app.openapi()["paths"]
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/imports")

    assert response.status_code == 401


def test_owner_resource_fails_closed_without_identity(tmp_path: Path) -> None:
    app = create_app(Settings(artifact_root=tmp_path), FakeDatabase())

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/whoami")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "https://billzebub.local/problems/owner_identity_required",
        "title": "Owner identity required",
        "status": 401,
        "detail": "owner_identity_required",
    }
