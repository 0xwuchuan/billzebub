from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.categories import CategoryRecord, CategoryUpdate
from billzebub.category_spend import CategorySpendReport
from billzebub.config import Settings
from billzebub.imports import ImportNotDismissableError, ImportNotFoundError, ImportRecord
from billzebub.statement_coverage import StatementCoverageReport


class FakeCategories:
    def __init__(self) -> None:
        self.records: list[CategoryRecord] = []

    def list(self) -> tuple[CategoryRecord, ...]:
        return tuple(self.records)

    def create(self, name: str, *, parent_id: UUID | None = None) -> CategoryRecord:
        record = CategoryRecord(id=uuid4(), name=name, parent_id=parent_id, active=True)
        self.records.append(record)
        return record

    def get(self, category_id: UUID) -> CategoryRecord:
        raise AssertionError(category_id)

    def update(self, category_id: UUID, command: CategoryUpdate) -> CategoryRecord:
        raise AssertionError((category_id, command))

    def delete(self, category_id: UUID, *, expected_version: int) -> None:
        raise AssertionError((category_id, expected_version))

    def spending(self, month: str) -> CategorySpendReport:
        raise AssertionError(month)


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
    assert "/api/v1/imports/{extraction_id}/dismiss" in app.openapi()["paths"]
    assert "/api/v1/imports/dismiss-failed" in app.openapi()["paths"]
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


class FakeImportCatalog:
    def __init__(self, record: ImportRecord) -> None:
        self.record = record
        self.include_dismissed: list[bool] = []
        self.dismissed: list[UUID] = []
        self.dismissed_failed = 0

    def list(self, *, include_dismissed: bool = False) -> tuple[ImportRecord, ...]:
        self.include_dismissed.append(include_dismissed)
        if include_dismissed or self.record.dismissed_at is None:
            return (self.record,)
        return ()

    def get(self, extraction_id: UUID) -> ImportRecord:
        if extraction_id != self.record.id:
            raise ImportNotFoundError(str(extraction_id))
        return self.record

    def dismiss(self, extraction_id: UUID) -> ImportRecord:
        if extraction_id != self.record.id:
            raise ImportNotFoundError(str(extraction_id))
        if self.record.status != "failed":
            raise ImportNotDismissableError("only failed Extractions may be dismissed")
        self.dismissed.append(extraction_id)
        self.record = replace(self.record, dismissed_at=datetime(2026, 9, 15, tzinfo=UTC))
        return self.record

    def dismiss_failed(self) -> int:
        self.dismissed_failed += 1
        return 2

    def coverage(
        self,
        *,
        months: int = 6,
        as_of: date | None = None,
    ) -> StatementCoverageReport:
        del months, as_of
        raise AssertionError("coverage is unused")


def _failed_import() -> ImportRecord:
    return ImportRecord(
        id=uuid4(),
        source_artifact_id=uuid4(),
        financial_account_id=None,
        financial_account_name=None,
        status="failed",
        adapter_key="apple_wallet_shortcut",
        parser_version="2",
        statement_date=None,
        period_start=None,
        period_end=None,
        candidate_row_count=0,
        claim_count=0,
        failure_code="invalid_payload_shape",
        validation_report={"failure": {"code": "invalid_payload_shape"}},
        duplicate_arrivals=0,
        active_review_id=None,
        supersedes_extraction_id=None,
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
        accepted_at=None,
        dismissed_at=None,
    )


def test_import_list_excludes_dismissed_unless_requested(tmp_path: Path) -> None:
    catalog = FakeImportCatalog(_failed_import())
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        import_catalog=catalog,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        default_list = client.get("/api/v1/imports")
        included = client.get("/api/v1/imports", params={"include_dismissed": True})

    assert default_list.status_code == 200
    assert included.status_code == 200
    assert catalog.include_dismissed == [False, True]


def test_import_dismiss_requires_browser_protection(tmp_path: Path) -> None:
    catalog = FakeImportCatalog(_failed_import())
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        import_catalog=catalog,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        blocked = client.post(f"/api/v1/imports/{catalog.record.id}/dismiss", json={})
        dismissed = client.post(
            f"/api/v1/imports/{catalog.record.id}/dismiss",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={},
        )
        bulk = client.post(
            "/api/v1/imports/dismiss-failed",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={},
        )

    assert blocked.status_code == 403
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None
    assert dismissed.json()["status"] == "failed"
    assert bulk.status_code == 200
    assert bulk.json() == {"dismissed_count": 2}
    assert catalog.dismissed == [catalog.record.id]
    assert catalog.dismissed_failed == 1
