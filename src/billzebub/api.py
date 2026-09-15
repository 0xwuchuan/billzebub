"""FastAPI application factory and versioned HTTP resources."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from billzebub.agent_facade import (
    AgentFacade,
    AgentFacadeError,
    CategorizationCommand,
    ProposalCommand,
    ProposalType,
)
from billzebub.apple_wallet import AppleWalletCaptureOutcome, AppleWalletIngestion
from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ArtifactStoreError, ContentAddressedStore
from billzebub.categories import CategoryCatalog, CategoryError, CategoryRecord
from billzebub.categorizer import AutoCategorizer
from billzebub.config import Settings
from billzebub.financial_account_aliases import (
    FinancialAccountAliasError,
    FinancialAccountAliases,
    FinancialAccountAliasRecord,
)
from billzebub.financial_accounts import (
    FinancialAccountBootstrap,
    FinancialAccountBootstrapCommand,
    FinancialAccountRecord,
    FinancialAccountSetupError,
    StatementAdapterRecord,
)
from billzebub.financial_history import TransactionKind
from billzebub.identity import IdentityError, OwnerIdentity, resolve_owner
from billzebub.imports import ImportCatalog, ImportNotFoundError, ImportRecord
from billzebub.owner_actors import OwnerActors
from billzebub.owner_transaction_actions import (
    OwnerCategorizationCommand,
    OwnerTransactionActionError,
    OwnerTransactionActions,
)
from billzebub.owner_workspace import OwnerWorkspace, OwnerWorkspaceError
from billzebub.persistence.database import Database
from billzebub.persistence.models import AuditActorKind, FinancialAccountKind
from billzebub.review_actions import (
    ReviewActionError,
    ReviewActions,
    ReviewConfigurationRequiredError,
)
from billzebub.reviews import PendingReviewStatus, ReviewDecision, ReviewError
from billzebub.statement_adapters import configured_statement_adapters
from billzebub.statement_extraction import StatementAdapterRegistry, StatementExtraction
from billzebub.tokens import (
    IssuedToken,
    TokenAuthenticationError,
    TokenManager,
    TokenPrincipal,
    TokenRecord,
    TokenRotationError,
    TokenScope,
)


class ImportCatalogRuntime(Protocol):
    def list(self) -> tuple[ImportRecord, ...]: ...

    def get(self, extraction_id: UUID) -> ImportRecord: ...


class CategoryCatalogRuntime(Protocol):
    def list(self) -> tuple[CategoryRecord, ...]: ...

    def create(self, name: str, *, parent_id: UUID | None = None) -> CategoryRecord: ...


class OwnerTransactionActionsRuntime(Protocol):
    def categorize(self, command: OwnerCategorizationCommand) -> Any: ...


class OwnerActorRuntime(Protocol):
    def resolve(self, identity: OwnerIdentity) -> UUID: ...


class ReviewActionsRuntime(Protocol):
    def decide(self, command: ReviewDecision) -> Any: ...


class OwnerWorkspaceRuntime(Protocol):
    def list_transactions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
    ) -> Any: ...

    def get_transaction(self, transaction_id: UUID) -> Any: ...

    def list_reviews(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        review_status: PendingReviewStatus = PendingReviewStatus.PENDING,
    ) -> Any: ...

    def get_review(self, review_id: UUID) -> Any: ...


class AgentFacadeRuntime(Protocol):
    def list_transactions(self, *, cursor: str | None = None, limit: int = 50) -> Any: ...

    def get_transaction(self, transaction_id: UUID) -> Any: ...

    def list_categories(self) -> tuple[Any, ...]: ...

    def list_reviews(self) -> tuple[Any, ...]: ...

    def categorize(self, command: Any, *, principal: str, idempotency_key: str) -> Any: ...

    def propose(self, command: Any, *, principal: str, idempotency_key: str) -> Any: ...


class TokenRuntime(Protocol):
    def authenticate(
        self,
        plaintext: str,
        *,
        required_scopes: frozenset[TokenScope] = frozenset(),
    ) -> TokenPrincipal: ...


class OwnerTokenRuntime(Protocol):
    def list_active(self) -> tuple[TokenRecord, ...]: ...

    def issue(
        self,
        *,
        name: str,
        actor_kind: AuditActorKind,
        scopes: frozenset[TokenScope],
    ) -> IssuedToken: ...

    def rotate(self, token_id: UUID) -> IssuedToken: ...

    def revoke(self, token_id: UUID) -> bool: ...


class AccountBootstrapRuntime(Protocol):
    def accepted_adapters(self) -> tuple[StatementAdapterRecord, ...]: ...

    def list(self) -> tuple[FinancialAccountRecord, ...]: ...

    def get(self, account_id: UUID) -> FinancialAccountRecord: ...

    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: bool = False,
    ) -> Any: ...


class AccountAliasRuntime(Protocol):
    def list(self) -> tuple[FinancialAccountAliasRecord, ...]: ...

    def add_apple_wallet_card_for_account(
        self,
        account_id: UUID,
        *,
        card_label: str,
    ) -> FinancialAccountAliasRecord: ...


class DatabaseRuntime(Protocol):
    def ping(self) -> None: ...

    def close(self) -> None: ...


class AppleWalletRuntime(Protocol):
    def ingest(
        self,
        body: bytes,
        *,
        received_at: datetime,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome: ...


class CategorizePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID


class OwnerCategorizePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID


class OwnerCategoryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None


class OwnerFinancialAccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    institution: str = Field(min_length=1, max_length=80)
    kind: Literal["credit_card", "paylah"]
    default_currency: str = Field(min_length=3, max_length=3)
    statement_adapter_key: str | None = None
    statement_account_identifier: str | None = None
    statement_password_secret: str | None = None


class OwnerAliasPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["apple_wallet_card"]
    card_label: str = Field(min_length=1, max_length=160)


class OwnerTokenIssuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: Literal["integration", "agent"]
    scopes: list[TokenScope] = Field(min_length=1)


class OwnerReviewDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: str = Field(min_length=1, max_length=120)


class ProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_type: ProposalType
    summary: str = Field(min_length=1, max_length=500)


class AppleWalletCaptureWire(BaseModel):
    status: Literal["accepted", "review_required"]
    duplicate: bool


class MoneyWire(BaseModel):
    amount: str = Field(pattern=r"^-?\d+(?:\.\d+)?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class OwnerCategoryWire(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    active: bool


class OwnerCategoryPageWire(BaseModel):
    items: list[OwnerCategoryWire]


class OwnerAliasWire(BaseModel):
    id: UUID
    alias_kind: str
    masked_value: str


class OwnerFinancialAccountWire(BaseModel):
    id: UUID
    slug: str
    display_name: str
    institution: str
    kind: str
    default_currency: str
    statement_adapter_key: str | None
    active: bool
    password_configured: bool
    inbox_ready: bool
    aliases: list[OwnerAliasWire]


class OwnerFinancialAccountPageWire(BaseModel):
    items: list[OwnerFinancialAccountWire]


class OwnerStatementAdapterWire(BaseModel):
    key: str
    institution: str
    kind: str


class OwnerStatementAdapterPageWire(BaseModel):
    items: list[OwnerStatementAdapterWire]


class OwnerTokenWire(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None


class OwnerTokenPageWire(BaseModel):
    items: list[OwnerTokenWire]


class OwnerIssuedTokenWire(OwnerTokenWire):
    plaintext: str


class OwnerRevokedTokenWire(BaseModel):
    id: UUID
    revoked: bool


class OwnerAccountWire(BaseModel):
    id: UUID
    name: str


class OwnerTransactionCategoryWire(BaseModel):
    id: UUID
    name: str
    amount: MoneyWire


class OwnerTransactionReviewWire(BaseModel):
    id: UUID
    condition_code: str
    severity: str
    version: int = Field(ge=1)
    allowed_decisions: list[str]


class OwnerTransactionWire(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    financial_account: OwnerAccountWire
    counterparty: str
    posted_amount: MoneyWire
    authorized_amount: MoneyWire | None
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: str
    category_splits: list[OwnerTransactionCategoryWire]
    reviews: list[OwnerTransactionReviewWire]


class OwnerTransactionPageWire(BaseModel):
    items: list[OwnerTransactionWire]
    next_cursor: str | None


class OwnerReviewWire(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    condition_code: str
    severity: str
    status: str
    version: int = Field(ge=1)
    allowed_decisions: list[str]
    context: dict[str, Any]
    created_at: str
    updated_at: str


class OwnerReviewPageWire(BaseModel):
    items: list[OwnerReviewWire]
    next_cursor: str | None


class AgentCategoryWire(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None


class AgentCategoryAllocationWire(BaseModel):
    category: AgentCategoryWire
    amount: MoneyWire


class AgentTransactionWire(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    counterparty: str
    amount: MoneyWire
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: str
    categories: list[AgentCategoryAllocationWire]
    review_choices: list[str]


class AgentTransactionPageWire(BaseModel):
    items: list[AgentTransactionWire]
    next_cursor: str | None


class AgentReviewWire(BaseModel):
    transaction_id: UUID
    choices: list[str]


class AgentReviewPageWire(BaseModel):
    items: list[AgentReviewWire]


class AgentCategoryPageWire(BaseModel):
    items: list[AgentCategoryWire]


class AgentProposalWire(BaseModel):
    transaction_id: UUID
    proposal_type: ProposalType
    status: Literal["pending"]


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    next_step: str | None = None
    command: str | None = None


class ProblemError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        extras: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.title = title
        self.extras = extras or {}


@dataclass(slots=True)
class Runtime:
    settings: Settings
    database: DatabaseRuntime
    import_catalog: ImportCatalogRuntime | None
    category_catalog: CategoryCatalogRuntime | None
    owner_transaction_actions: OwnerTransactionActionsRuntime | None
    owner_actors: OwnerActorRuntime | None
    review_actions: ReviewActionsRuntime | None
    owner_workspace: OwnerWorkspaceRuntime | None
    agent_facade: AgentFacadeRuntime | None
    token_manager: TokenRuntime | None
    owner_tokens: OwnerTokenRuntime | None
    account_bootstrap: AccountBootstrapRuntime | None
    account_aliases: AccountAliasRuntime | None
    apple_wallet_ingestion: AppleWalletRuntime | None


def create_app(
    settings: Settings | None = None,
    database: DatabaseRuntime | None = None,
    import_catalog: ImportCatalogRuntime | None = None,
    category_catalog: CategoryCatalogRuntime | None = None,
    owner_transaction_actions: OwnerTransactionActionsRuntime | None = None,
    owner_actors: OwnerActorRuntime | None = None,
    review_actions: ReviewActionsRuntime | None = None,
    owner_workspace: OwnerWorkspaceRuntime | None = None,
    agent_facade: AgentFacadeRuntime | None = None,
    token_manager: TokenRuntime | None = None,
    owner_tokens: OwnerTokenRuntime | None = None,
    account_bootstrap: AccountBootstrapRuntime | None = None,
    account_aliases: AccountAliasRuntime | None = None,
    apple_wallet_ingestion: AppleWalletRuntime | None = None,
) -> FastAPI:
    """Build the HTTP process without creating hidden global dependencies."""
    resolved_settings = settings or Settings()
    resolved_database = database or Database(resolved_settings)
    resolved_catalog = import_catalog
    resolved_category_catalog = category_catalog
    resolved_owner_transaction_actions = owner_transaction_actions
    resolved_owner_actors = owner_actors
    resolved_review_actions = review_actions
    resolved_owner_workspace = owner_workspace
    resolved_agent_facade = agent_facade
    resolved_token_manager = token_manager
    resolved_owner_tokens = owner_tokens
    resolved_account_bootstrap = account_bootstrap
    resolved_account_aliases = account_aliases
    resolved_apple_wallet_ingestion = apple_wallet_ingestion
    if isinstance(resolved_database, Database):
        resolved_catalog = resolved_catalog or ImportCatalog(resolved_database)
        resolved_category_catalog = resolved_category_catalog or CategoryCatalog(resolved_database)
        resolved_owner_transaction_actions = (
            resolved_owner_transaction_actions or OwnerTransactionActions(resolved_database)
        )
        resolved_owner_actors = resolved_owner_actors or OwnerActors(resolved_database)
        resolved_review_actions = resolved_review_actions or ReviewActions(
            resolved_database,
            extraction=StatementExtraction(
                resolved_database,
                ContentAddressedStore(
                    resolved_settings.artifact_root,
                    max_bytes=resolved_settings.artifact_max_bytes,
                ),
                StatementAdapterRegistry(configured_statement_adapters()),
                password_root=resolved_settings.statement_password_root,
            ),
        )
        resolved_owner_workspace = resolved_owner_workspace or OwnerWorkspace(
            resolved_database,
            categorizer=AutoCategorizer(
                resolved_database,
                min_confidence=resolved_settings.categorizer_min_confidence,
                enabled=resolved_settings.categorizer_enabled,
            ),
        )
        resolved_agent_facade = resolved_agent_facade or AgentFacade(resolved_database)
        resolved_token_manager = resolved_token_manager or TokenManager(resolved_database)
        if resolved_owner_tokens is None and isinstance(resolved_token_manager, TokenManager):
            resolved_owner_tokens = resolved_token_manager
        if resolved_account_bootstrap is None:
            resolved_account_bootstrap = cast(
                AccountBootstrapRuntime,
                FinancialAccountBootstrap(
                    resolved_database,
                    inbox_root=resolved_settings.statement_inbox_root,
                    password_root=resolved_settings.statement_password_root,
                ),
            )
        if resolved_account_aliases is None:
            resolved_account_aliases = FinancialAccountAliases(resolved_database)
        if (
            resolved_apple_wallet_ingestion is None
            and resolved_settings.apple_wallet_timezone is not None
        ):
            resolved_apple_wallet_ingestion = AppleWalletIngestion(
                resolved_database,
                ArtifactCapture(
                    ContentAddressedStore(
                        resolved_settings.artifact_root,
                        max_bytes=resolved_settings.artifact_max_bytes,
                    ),
                    resolved_database,
                ),
                FinancialAccountAliases(resolved_database),
                timezone=ZoneInfo(resolved_settings.apple_wallet_timezone),
            )
    runtime = Runtime(
        settings=resolved_settings,
        database=resolved_database,
        import_catalog=resolved_catalog,
        category_catalog=resolved_category_catalog,
        owner_transaction_actions=resolved_owner_transaction_actions,
        owner_actors=resolved_owner_actors,
        review_actions=resolved_review_actions,
        owner_workspace=resolved_owner_workspace,
        agent_facade=resolved_agent_facade,
        token_manager=resolved_token_manager,
        owner_tokens=resolved_owner_tokens,
        account_bootstrap=resolved_account_bootstrap,
        account_aliases=resolved_account_aliases,
        apple_wallet_ingestion=resolved_apple_wallet_ingestion,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        runtime.database.close()

    app = FastAPI(title="Billzebub", version="1.0.0", lifespan=lifespan)
    app.state.runtime = runtime

    @app.exception_handler(ProblemError)
    async def problem_response(_request: Request, error: ProblemError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=Problem(
                type=f"https://billzebub.local/problems/{error.code}",
                title=error.title,
                status=error.status_code,
                detail=error.code,
                **error.extras,
            ).model_dump(exclude_none=True),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_response(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return _problem("invalid_request", "Invalid request", status.HTTP_400_BAD_REQUEST)

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"], response_model=None)
    def ready() -> JSONResponse:
        dependencies: dict[str, str] = {"postgres": "ok", "artifact_store": "ok"}
        try:
            runtime.database.ping()
        except Exception:  # Health must redact driver details at the HTTP seam.
            dependencies["postgres"] = "unavailable"
        try:
            _verify_writable_directory(runtime.settings.artifact_root)
        except OSError:
            dependencies["artifact_store"] = "unavailable"

        ready_now = all(value == "ok" for value in dependencies.values())
        body: dict[str, object] = {
            "status": "ok" if ready_now else "unavailable",
            "dependencies": dependencies,
        }
        response_status = status.HTTP_200_OK if ready_now else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=response_status, content=body)

    def owner(request: Request) -> OwnerIdentity:
        client_host = request.client.host if request.client is not None else ""
        try:
            return resolve_owner(
                request.headers,
                client_host=client_host,
                settings=runtime.settings,
            )
        except IdentityError as error:
            raise ProblemError(
                status.HTTP_401_UNAUTHORIZED,
                "owner_identity_required",
                "Owner identity required",
            ) from error

    def browser_mutation(request: Request) -> OwnerIdentity:
        identity = owner(request)
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if (
            origin != expected_origin
            or content_type != "application/json"
            or request.headers.get("x-billzebub-csrf") != "bzb-spa"
        ):
            raise ProblemError(
                status.HTTP_403_FORBIDDEN,
                "browser_mutation_forbidden",
                "Browser mutation forbidden",
            )
        return identity

    def imports() -> ImportCatalogRuntime:
        if runtime.import_catalog is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "import_catalog_unavailable",
                "Import catalog unavailable",
            )
        return runtime.import_catalog

    def categories() -> CategoryCatalogRuntime:
        if runtime.category_catalog is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "category_catalog_unavailable",
                "Category catalog unavailable",
            )
        return runtime.category_catalog

    def owner_transaction_actions_resource() -> OwnerTransactionActionsRuntime:
        if runtime.owner_transaction_actions is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "owner_transaction_actions_unavailable",
                "Owner Transaction action service unavailable",
            )
        return runtime.owner_transaction_actions

    def owner_actors_resource() -> OwnerActorRuntime:
        if runtime.owner_actors is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "owner_actors_unavailable",
                "Owner audit actor service unavailable",
            )
        return runtime.owner_actors

    def review_actions_resource() -> ReviewActionsRuntime:
        if runtime.review_actions is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "review_actions_unavailable",
                "Review action service unavailable",
            )
        return runtime.review_actions

    def owner_workspace_resource() -> OwnerWorkspaceRuntime:
        if runtime.owner_workspace is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "owner_workspace_unavailable",
                "Owner workspace unavailable",
            )
        return runtime.owner_workspace

    def agent() -> AgentFacadeRuntime:
        if runtime.agent_facade is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "agent_facade_unavailable",
                "Agent facade unavailable",
            )
        return runtime.agent_facade

    def bearer(
        request: Request,
        scopes: frozenset[TokenScope],
    ) -> TokenPrincipal:
        authorization = request.headers.get("authorization", "")
        scheme, separator, plaintext = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not separator or not plaintext.strip():
            raise ProblemError(
                status.HTTP_401_UNAUTHORIZED,
                "bearer_token_required",
                "Bearer token required",
            )
        if runtime.token_manager is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "token_authentication_unavailable",
                "Token authentication unavailable",
            )
        try:
            return runtime.token_manager.authenticate(
                plaintext.strip(),
                required_scopes=scopes,
            )
        except TokenAuthenticationError as error:
            raise ProblemError(
                status.HTTP_401_UNAUTHORIZED,
                "bearer_token_invalid",
                "Bearer token invalid",
            ) from error

    def agent_reader(request: Request) -> TokenPrincipal:
        return bearer(request, frozenset({TokenScope.AGENT_READ}))

    def agent_categorizer(request: Request) -> TokenPrincipal:
        return bearer(request, frozenset({TokenScope.AGENT_CATEGORIZE}))

    def agent_proposer(request: Request) -> TokenPrincipal:
        return bearer(request, frozenset({TokenScope.AGENT_PROPOSE}))

    def shortcut_claim_creator(request: Request) -> TokenPrincipal:
        return bearer(request, frozenset({TokenScope.SHORTCUT_CLAIMS_CREATE}))

    def apple_wallet_capture_resource() -> AppleWalletRuntime:
        if runtime.apple_wallet_ingestion is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "apple_wallet_ingestion_unavailable",
                "Apple Wallet ingestion unavailable",
            )
        return runtime.apple_wallet_ingestion

    def account_bootstrap_resource() -> AccountBootstrapRuntime:
        if runtime.account_bootstrap is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "financial_account_setup_unavailable",
                "Financial Account setup unavailable",
            )
        return runtime.account_bootstrap

    def account_aliases_resource() -> AccountAliasRuntime:
        if runtime.account_aliases is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "financial_account_alias_unavailable",
                "Financial Account alias service unavailable",
            )
        return runtime.account_aliases

    def owner_tokens_resource() -> OwnerTokenRuntime:
        if runtime.owner_tokens is None:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "owner_tokens_unavailable",
                "Owner token service unavailable",
            )
        return runtime.owner_tokens

    owner_dependency = Depends(owner)
    browser_mutation_dependency = Depends(browser_mutation)
    imports_dependency = Depends(imports)
    categories_dependency = Depends(categories)
    owner_transaction_actions_dependency = Depends(owner_transaction_actions_resource)
    owner_actors_dependency = Depends(owner_actors_resource)
    review_actions_dependency = Depends(review_actions_resource)
    owner_workspace_dependency = Depends(owner_workspace_resource)
    account_bootstrap_dependency = Depends(account_bootstrap_resource)
    account_aliases_dependency = Depends(account_aliases_resource)
    owner_tokens_dependency = Depends(owner_tokens_resource)
    agent_dependency = Depends(agent)
    agent_reader_dependency = Depends(agent_reader)
    agent_categorizer_dependency = Depends(agent_categorizer)
    agent_proposer_dependency = Depends(agent_proposer)
    shortcut_claim_creator_dependency = Depends(shortcut_claim_creator)
    apple_wallet_capture_dependency = Depends(apple_wallet_capture_resource)

    @app.post(
        "/api/v1/ingestions/apple-wallet",
        tags=["ingestions"],
        response_model=AppleWalletCaptureWire,
    )
    async def ingest_apple_wallet(
        request: Request,
        principal: TokenPrincipal = shortcut_claim_creator_dependency,
        capture: AppleWalletRuntime = apple_wallet_capture_dependency,
    ) -> JSONResponse:
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise ProblemError(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "apple_wallet_content_type_invalid",
                "Apple Wallet content type invalid",
            )
        body = await request.body()
        if len(body) > runtime.settings.apple_wallet_max_bytes:
            raise ProblemError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "apple_wallet_body_too_large",
                "Apple Wallet request too large",
            )
        try:
            outcome = capture.ingest(
                body,
                received_at=datetime.now(UTC),
                actor_id=principal.actor_id,
            )
        except (ArtifactStoreError, OSError, ValueError) as error:
            raise ProblemError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "apple_wallet_capture_unavailable",
                "Apple Wallet capture unavailable",
            ) from error
        response_status = (
            status.HTTP_200_OK
            if outcome.duplicate
            else (
                status.HTTP_201_CREATED
                if outcome.status.value == "accepted"
                else status.HTTP_202_ACCEPTED
            )
        )
        return JSONResponse(
            status_code=response_status,
            content={"status": outcome.status.value, "duplicate": outcome.duplicate},
        )

    @app.get("/api/v1/whoami", tags=["owner"])
    def whoami(identity: OwnerIdentity = owner_dependency) -> dict[str, str]:
        return {"login": identity.login, "name": identity.name}

    @app.get("/api/v1/imports", tags=["imports"], response_model=None)
    def list_imports(
        _identity: OwnerIdentity = owner_dependency,
        catalog: ImportCatalogRuntime = imports_dependency,
    ) -> dict[str, tuple[ImportRecord, ...]]:
        return {"items": catalog.list()}

    @app.get("/api/v1/imports/{extraction_id}", tags=["imports"], response_model=None)
    def get_import(
        extraction_id: UUID,
        _identity: OwnerIdentity = owner_dependency,
        catalog: ImportCatalogRuntime = imports_dependency,
    ) -> ImportRecord:
        try:
            return catalog.get(extraction_id)
        except ImportNotFoundError as error:
            raise ProblemError(
                status.HTTP_404_NOT_FOUND,
                "import_not_found",
                "Import not found",
            ) from error

    @app.get("/api/v1/categories", tags=["owner"], response_model=OwnerCategoryPageWire)
    def list_owner_categories(
        _identity: OwnerIdentity = owner_dependency,
        catalog: CategoryCatalogRuntime = categories_dependency,
    ) -> OwnerCategoryPageWire:
        return OwnerCategoryPageWire(
            items=[_owner_category(category) for category in catalog.list()]
        )

    @app.post(
        "/api/v1/categories",
        tags=["owner"],
        status_code=status.HTTP_201_CREATED,
        response_model=OwnerCategoryWire,
    )
    def create_owner_category(
        payload: OwnerCategoryPayload,
        _identity: OwnerIdentity = browser_mutation_dependency,
        catalog: CategoryCatalogRuntime = categories_dependency,
    ) -> OwnerCategoryWire:
        try:
            return _owner_category(catalog.create(payload.name, parent_id=payload.parent_id))
        except CategoryError as error:
            raise ProblemError(
                status.HTTP_400_BAD_REQUEST,
                "category_request_invalid",
                "Category request invalid",
            ) from error

    @app.get(
        "/api/v1/statement-adapters",
        tags=["owner"],
        response_model=OwnerStatementAdapterPageWire,
    )
    def list_statement_adapters(
        _identity: OwnerIdentity = owner_dependency,
        bootstrap: AccountBootstrapRuntime = account_bootstrap_dependency,
    ) -> OwnerStatementAdapterPageWire:
        return OwnerStatementAdapterPageWire(
            items=[
                OwnerStatementAdapterWire(
                    key=adapter.key,
                    institution=adapter.institution,
                    kind=adapter.kind.value,
                )
                for adapter in bootstrap.accepted_adapters()
            ]
        )

    @app.get(
        "/api/v1/financial-accounts",
        tags=["owner"],
        response_model=OwnerFinancialAccountPageWire,
    )
    def list_owner_financial_accounts(
        _identity: OwnerIdentity = owner_dependency,
        bootstrap: AccountBootstrapRuntime = account_bootstrap_dependency,
        aliases: AccountAliasRuntime = account_aliases_dependency,
    ) -> OwnerFinancialAccountPageWire:
        grouped = _aliases_by_account(aliases.list())
        return OwnerFinancialAccountPageWire(
            items=[
                _owner_financial_account(account, grouped.get(account.id, ()))
                for account in bootstrap.list()
            ]
        )

    @app.post(
        "/api/v1/financial-accounts",
        tags=["owner"],
        status_code=status.HTTP_201_CREATED,
        response_model=OwnerFinancialAccountWire,
    )
    def create_owner_financial_account(
        payload: OwnerFinancialAccountPayload,
        _identity: OwnerIdentity = browser_mutation_dependency,
        bootstrap: AccountBootstrapRuntime = account_bootstrap_dependency,
    ) -> OwnerFinancialAccountWire:
        try:
            account = bootstrap.bootstrap(
                FinancialAccountBootstrapCommand(
                    slug=payload.slug,
                    display_name=payload.display_name,
                    institution=payload.institution,
                    kind=FinancialAccountKind(payload.kind),
                    default_currency=payload.default_currency,
                    statement_adapter_key=payload.statement_adapter_key,
                    statement_account_identifier=payload.statement_account_identifier,
                    statement_password_secret=payload.statement_password_secret,
                )
            )
        except FinancialAccountSetupError as error:
            raise ProblemError(
                status.HTTP_400_BAD_REQUEST,
                "financial_account_setup_invalid",
                "Financial Account setup invalid",
            ) from error
        if not isinstance(account, FinancialAccountRecord):
            raise ProblemError(
                status.HTTP_400_BAD_REQUEST,
                "financial_account_setup_invalid",
                "Financial Account setup invalid",
            )
        return _owner_financial_account(account, ())

    @app.post(
        "/api/v1/financial-accounts/{account_id}/aliases",
        tags=["owner"],
        status_code=status.HTTP_201_CREATED,
        response_model=OwnerAliasWire,
    )
    def create_owner_financial_account_alias(
        account_id: UUID,
        payload: OwnerAliasPayload,
        _identity: OwnerIdentity = browser_mutation_dependency,
        bootstrap: AccountBootstrapRuntime = account_bootstrap_dependency,
        aliases: AccountAliasRuntime = account_aliases_dependency,
    ) -> OwnerAliasWire:
        try:
            bootstrap.get(account_id)
            alias = aliases.add_apple_wallet_card_for_account(
                account_id, card_label=payload.card_label
            )
        except FinancialAccountSetupError as error:
            raise ProblemError(
                status.HTTP_404_NOT_FOUND,
                "financial_account_not_found",
                "Financial Account not found",
            ) from error
        except FinancialAccountAliasError as error:
            raise ProblemError(
                status.HTTP_400_BAD_REQUEST,
                "financial_account_alias_invalid",
                "Financial Account alias invalid",
            ) from error
        return _owner_alias(alias)

    @app.get("/api/v1/tokens", tags=["owner"], response_model=OwnerTokenPageWire)
    def list_owner_tokens(
        _identity: OwnerIdentity = owner_dependency,
        tokens: OwnerTokenRuntime = owner_tokens_dependency,
    ) -> OwnerTokenPageWire:
        return OwnerTokenPageWire(items=[_owner_token(token) for token in tokens.list_active()])

    @app.post(
        "/api/v1/tokens",
        tags=["owner"],
        status_code=status.HTTP_201_CREATED,
        response_model=OwnerIssuedTokenWire,
    )
    def issue_owner_token(
        payload: OwnerTokenIssuePayload,
        _identity: OwnerIdentity = browser_mutation_dependency,
        tokens: OwnerTokenRuntime = owner_tokens_dependency,
    ) -> OwnerIssuedTokenWire:
        try:
            issued = tokens.issue(
                name=payload.name,
                actor_kind=AuditActorKind(payload.kind),
                scopes=frozenset(payload.scopes),
            )
        except ValueError as error:
            raise ProblemError(
                status.HTTP_400_BAD_REQUEST,
                "token_request_invalid",
                "Token request invalid",
            ) from error
        return _owner_issued_token(issued)

    @app.post(
        "/api/v1/tokens/{token_id}/rotate",
        tags=["owner"],
        response_model=OwnerIssuedTokenWire,
    )
    def rotate_owner_token(
        token_id: UUID,
        _identity: OwnerIdentity = browser_mutation_dependency,
        tokens: OwnerTokenRuntime = owner_tokens_dependency,
    ) -> OwnerIssuedTokenWire:
        try:
            issued = tokens.rotate(token_id)
        except TokenRotationError as error:
            raise ProblemError(
                status.HTTP_404_NOT_FOUND,
                "token_not_found",
                "Token not found",
            ) from error
        return _owner_issued_token(issued)

    @app.post(
        "/api/v1/tokens/{token_id}/revoke",
        tags=["owner"],
        response_model=OwnerRevokedTokenWire,
    )
    def revoke_owner_token(
        token_id: UUID,
        _identity: OwnerIdentity = browser_mutation_dependency,
        tokens: OwnerTokenRuntime = owner_tokens_dependency,
    ) -> OwnerRevokedTokenWire:
        if not tokens.revoke(token_id):
            raise ProblemError(
                status.HTTP_404_NOT_FOUND,
                "token_not_found",
                "Token not found",
            )
        return OwnerRevokedTokenWire(id=token_id, revoked=True)

    @app.get("/api/v1/transactions", tags=["owner"], response_model=OwnerTransactionPageWire)
    def list_owner_transactions(
        cursor: str | None = None,
        limit: int = 50,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
        _identity: OwnerIdentity = owner_dependency,
        workspace: OwnerWorkspaceRuntime = owner_workspace_dependency,
    ) -> JSONResponse:
        try:
            page = workspace.list_transactions(
                cursor=cursor,
                limit=limit,
                financial_account_id=financial_account_id,
                kind=kind,
                needs_review=needs_review,
            )
        except OwnerWorkspaceError as error:
            raise _owner_workspace_problem(error) from error
        return _owner_response(
            {
                "items": [_owner_transaction(transaction) for transaction in page.items],
                "next_cursor": page.next_cursor,
            }
        )

    @app.get(
        "/api/v1/transactions/{transaction_id}",
        tags=["owner"],
        response_model=OwnerTransactionWire,
    )
    def get_owner_transaction(
        transaction_id: UUID,
        _identity: OwnerIdentity = owner_dependency,
        workspace: OwnerWorkspaceRuntime = owner_workspace_dependency,
    ) -> JSONResponse:
        try:
            transaction = workspace.get_transaction(transaction_id)
        except OwnerWorkspaceError as error:
            raise _owner_workspace_problem(error) from error
        return _owner_response(
            _owner_transaction(transaction),
            etag=_transaction_etag(transaction),
        )

    @app.put(
        "/api/v1/transactions/{transaction_id}/category",
        tags=["owner"],
        response_model=OwnerTransactionWire,
    )
    def categorize_owner_transaction(
        transaction_id: UUID,
        payload: OwnerCategorizePayload,
        identity: OwnerIdentity = browser_mutation_dependency,
        actions: OwnerTransactionActionsRuntime = owner_transaction_actions_dependency,
        actors: OwnerActorRuntime = owner_actors_dependency,
        workspace: OwnerWorkspaceRuntime = owner_workspace_dependency,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> JSONResponse:
        expected_version = _expected_version(if_match, transaction_id)
        try:
            actions.categorize(
                OwnerCategorizationCommand(
                    transaction_id=transaction_id,
                    expected_version=expected_version,
                    category_id=payload.category_id,
                    actor_id=actors.resolve(identity),
                )
            )
            transaction = workspace.get_transaction(transaction_id)
        except OwnerTransactionActionError as error:
            raise _owner_transaction_action_problem(error) from error
        except OwnerWorkspaceError as error:
            raise _owner_workspace_problem(error) from error
        return _owner_response(
            _owner_transaction(transaction),
            etag=_transaction_etag(transaction),
        )

    @app.get("/api/v1/reviews", tags=["owner"], response_model=OwnerReviewPageWire)
    def list_owner_reviews(
        cursor: str | None = None,
        limit: int = 50,
        review_status: PendingReviewStatus = PendingReviewStatus.PENDING,
        _identity: OwnerIdentity = owner_dependency,
        workspace: OwnerWorkspaceRuntime = owner_workspace_dependency,
    ) -> JSONResponse:
        try:
            page = workspace.list_reviews(
                cursor=cursor,
                limit=limit,
                review_status=review_status,
            )
        except OwnerWorkspaceError as error:
            raise _owner_workspace_problem(error) from error
        return _owner_response(
            {
                "items": [_owner_review(review) for review in page.items],
                "next_cursor": page.next_cursor,
            }
        )

    @app.get("/api/v1/reviews/{review_id}", tags=["owner"], response_model=OwnerReviewWire)
    def get_owner_review(
        review_id: UUID,
        _identity: OwnerIdentity = owner_dependency,
        workspace: OwnerWorkspaceRuntime = owner_workspace_dependency,
    ) -> JSONResponse:
        try:
            review = workspace.get_review(review_id)
        except OwnerWorkspaceError as error:
            raise _owner_workspace_problem(error) from error
        return _owner_response(_owner_review(review), etag=_review_etag(review))

    @app.post(
        "/api/v1/reviews/{review_id}/decisions",
        tags=["owner"],
        response_model=OwnerReviewWire,
    )
    def decide_owner_review(
        review_id: UUID,
        payload: OwnerReviewDecisionPayload,
        identity: OwnerIdentity = browser_mutation_dependency,
        actions: ReviewActionsRuntime = review_actions_dependency,
        actors: OwnerActorRuntime = owner_actors_dependency,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> JSONResponse:
        expected_version = _expected_review_version(if_match, review_id)
        try:
            review = actions.decide(
                ReviewDecision(
                    review_id=review_id,
                    expected_version=expected_version,
                    choice=payload.choice,
                    actor_id=actors.resolve(identity),
                )
            )
        except (ReviewActionError, ReviewError) as error:
            raise _review_action_problem(error) from error
        return _owner_response(_owner_review(review), etag=_review_etag(review))

    @app.get("/api/v1/agent/transactions", tags=["agent"], response_model=AgentTransactionPageWire)
    def list_agent_transactions(
        facade: AgentFacadeRuntime = agent_dependency,
        _principal: TokenPrincipal = agent_reader_dependency,
        cursor: str | None = None,
        limit: int = 50,
    ) -> JSONResponse:
        try:
            page = facade.list_transactions(cursor=cursor, limit=limit)
        except AgentFacadeError as error:
            raise _agent_problem(error) from error
        return _agent_response(
            {"items": [item.to_wire() for item in page.items], "next_cursor": page.next_cursor}
        )

    @app.get(
        "/api/v1/agent/transactions/{transaction_id}",
        tags=["agent"],
        response_model=AgentTransactionWire,
    )
    def get_agent_transaction(
        transaction_id: UUID,
        facade: AgentFacadeRuntime = agent_dependency,
        _principal: TokenPrincipal = agent_reader_dependency,
    ) -> JSONResponse:
        try:
            transaction = facade.get_transaction(transaction_id)
        except AgentFacadeError as error:
            raise _agent_problem(error) from error
        return _agent_response(transaction.to_wire(), etag=_transaction_etag(transaction))

    @app.get("/api/v1/agent/categories", tags=["agent"], response_model=AgentCategoryPageWire)
    def list_agent_categories(
        facade: AgentFacadeRuntime = agent_dependency,
        _principal: TokenPrincipal = agent_reader_dependency,
    ) -> JSONResponse:
        return _agent_response(
            {"items": [category.to_wire() for category in facade.list_categories()]}
        )

    @app.get("/api/v1/agent/reviews", tags=["agent"], response_model=AgentReviewPageWire)
    def list_agent_reviews(
        facade: AgentFacadeRuntime = agent_dependency,
        _principal: TokenPrincipal = agent_reader_dependency,
    ) -> JSONResponse:
        return _agent_response({"items": [review.to_wire() for review in facade.list_reviews()]})

    @app.post(
        "/api/v1/agent/transactions/{transaction_id}/category",
        tags=["agent"],
        response_model=AgentTransactionWire,
    )
    def categorize_agent_transaction(
        transaction_id: UUID,
        payload: CategorizePayload,
        facade: AgentFacadeRuntime = agent_dependency,
        principal: TokenPrincipal = agent_categorizer_dependency,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> JSONResponse:
        key = _required_idempotency_key(idempotency_key)
        expected_version = _expected_version(if_match, transaction_id)
        try:
            result = facade.categorize(
                CategorizationCommand(
                    transaction_id=transaction_id,
                    expected_version=expected_version,
                    category_id=payload.category_id,
                    actor_id=principal.actor_id,
                ),
                principal=f"token:{principal.token_id}",
                idempotency_key=key,
            )
        except AgentFacadeError as error:
            raise _agent_problem(error) from error
        return _agent_response(
            result.body,
            etag=_transaction_etag_wire(result.body),
            replayed=result.replayed,
        )

    @app.post(
        "/api/v1/agent/transactions/{transaction_id}/proposals",
        tags=["agent"],
        response_model=AgentProposalWire,
    )
    def propose_agent_change(
        transaction_id: UUID,
        payload: ProposalPayload,
        facade: AgentFacadeRuntime = agent_dependency,
        principal: TokenPrincipal = agent_proposer_dependency,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> JSONResponse:
        key = _required_idempotency_key(idempotency_key)
        expected_version = _expected_version(if_match, transaction_id)
        try:
            result = facade.propose(
                ProposalCommand(
                    transaction_id=transaction_id,
                    expected_version=expected_version,
                    proposal_type=payload.proposal_type,
                    summary=payload.summary,
                    actor_id=principal.actor_id,
                ),
                principal=f"token:{principal.token_id}",
                idempotency_key=key,
            )
        except AgentFacadeError as error:
            raise _agent_problem(error) from error
        return _agent_response(result.body, status_code=202, replayed=result.replayed)

    if runtime.settings.web_root is not None:
        index = runtime.settings.web_root / "index.html"
        if not runtime.settings.web_root.is_dir() or not index.is_file():
            raise ValueError("web root must contain index.html")
        app.mount("/", StaticFiles(directory=runtime.settings.web_root, html=True), name="web")

    return app


def _owner_transaction(transaction: Any) -> dict[str, Any]:
    return {
        "id": str(transaction.id),
        "version": transaction.version,
        "financial_account": {
            "id": str(transaction.financial_account_id),
            "name": transaction.financial_account_name,
        },
        "counterparty": transaction.counterparty,
        "posted_amount": transaction.posted_amount.to_wire(),
        "authorized_amount": (
            transaction.authorized_amount.to_wire()
            if transaction.authorized_amount is not None
            else None
        ),
        "effective_date": transaction.effective_date,
        "kind": transaction.kind.value,
        "category_splits": [
            {
                "id": str(split.category_id),
                "name": split.category_name,
                "amount": split.amount.to_wire(),
            }
            for split in transaction.category_splits
        ],
        "reviews": [
            {
                "id": str(review.id),
                "condition_code": review.condition_code,
                "severity": review.severity.value,
                "version": review.version,
                "allowed_decisions": list(review.allowed_decisions),
            }
            for review in transaction.reviews
        ],
    }


def _owner_review(review: Any) -> dict[str, Any]:
    return {
        "id": str(review.id),
        "subject_type": review.subject_type,
        "subject_id": str(review.subject_id),
        "condition_code": review.condition_code,
        "severity": review.severity.value,
        "status": review.status.value,
        "version": review.version,
        "allowed_decisions": list(review.allowed_decisions),
        "context": review.context,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
    }


def _owner_category(category: CategoryRecord) -> OwnerCategoryWire:
    return OwnerCategoryWire(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        active=category.active,
    )


def _owner_alias(alias: FinancialAccountAliasRecord) -> OwnerAliasWire:
    return OwnerAliasWire(
        id=alias.id,
        alias_kind=alias.alias_kind,
        masked_value=alias.masked_value,
    )


def _aliases_by_account(
    aliases: tuple[FinancialAccountAliasRecord, ...],
) -> dict[UUID, tuple[FinancialAccountAliasRecord, ...]]:
    grouped: dict[UUID, list[FinancialAccountAliasRecord]] = {}
    for alias in aliases:
        grouped.setdefault(alias.financial_account_id, []).append(alias)
    return {account_id: tuple(items) for account_id, items in grouped.items()}


def _owner_financial_account(
    account: FinancialAccountRecord,
    aliases: tuple[FinancialAccountAliasRecord, ...],
) -> OwnerFinancialAccountWire:
    return OwnerFinancialAccountWire(
        id=account.id,
        slug=account.slug,
        display_name=account.display_name,
        institution=account.institution,
        kind=account.kind.value,
        default_currency=account.default_currency,
        statement_adapter_key=account.statement_adapter_key,
        active=account.active,
        password_configured=account.password_configured,
        inbox_ready=account.inbox_ready,
        aliases=[_owner_alias(alias) for alias in aliases],
    )


def _owner_token(token: TokenRecord) -> OwnerTokenWire:
    return OwnerTokenWire(
        id=token.id,
        name=token.name,
        prefix=token.prefix,
        scopes=list(token.scopes),
        created_at=token.created_at.isoformat(),
        last_used_at=None if token.last_used_at is None else token.last_used_at.isoformat(),
    )


def _owner_issued_token(issued: IssuedToken) -> OwnerIssuedTokenWire:
    return OwnerIssuedTokenWire(
        id=issued.id,
        name=issued.name,
        prefix=issued.prefix,
        scopes=sorted(scope.value for scope in issued.scopes),
        created_at=datetime.now(UTC).isoformat(),
        last_used_at=None,
        plaintext=issued.plaintext,
    )


def _owner_workspace_problem(error: OwnerWorkspaceError) -> ProblemError:
    if str(error) == "Transaction was not found":
        return ProblemError(
            status.HTTP_404_NOT_FOUND,
            "transaction_not_found",
            "Transaction not found",
        )
    if str(error) == "Pending Review was not found":
        return ProblemError(
            status.HTTP_404_NOT_FOUND,
            "review_not_found",
            "Pending Review not found",
        )
    return ProblemError(
        status.HTTP_400_BAD_REQUEST,
        "owner_workspace_request_invalid",
        "Owner workspace request invalid",
    )


def _owner_transaction_action_problem(error: OwnerTransactionActionError) -> ProblemError:
    if str(error) == "Transaction was not found":
        return ProblemError(
            status.HTTP_404_NOT_FOUND,
            "transaction_not_found",
            "Transaction not found",
        )
    if "stale" in str(error):
        return ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    return ProblemError(
        status.HTTP_400_BAD_REQUEST,
        "transaction_action_invalid",
        "Transaction action invalid",
    )


def _review_action_problem(error: ReviewActionError | ReviewError) -> ProblemError:
    if isinstance(error, ReviewConfigurationRequiredError):
        title = (
            "PayLah Financial Account configuration required"
            if error.problem_code == "paylah_account_configuration_required"
            else "Card alias configuration required"
        )
        return ProblemError(
            status.HTTP_409_CONFLICT,
            error.problem_code,
            title,
            extras={"next_step": error.next_step, "command": error.command},
        )
    if str(error) == "Pending Review was not found":
        return ProblemError(
            status.HTTP_404_NOT_FOUND,
            "review_not_found",
            "Pending Review not found",
        )
    if "stale" in str(error):
        return ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    return ProblemError(
        status.HTTP_400_BAD_REQUEST,
        "review_decision_invalid",
        "Review decision invalid",
    )


def _agent_problem(error: AgentFacadeError) -> ProblemError:
    if str(error) == "Transaction was not found":
        return ProblemError(
            status.HTTP_404_NOT_FOUND, "transaction_not_found", "Transaction not found"
        )
    if "stale" in str(error):
        return ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    if "idempotency key" in str(error):
        return ProblemError(
            status.HTTP_409_CONFLICT, "idempotency_key_conflict", "Idempotency key conflict"
        )
    return ProblemError(
        status.HTTP_400_BAD_REQUEST, "agent_request_invalid", "Agent request invalid"
    )


def _problem(code: str, title: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=Problem(
            type=f"https://billzebub.local/problems/{code}",
            title=title,
            status=status_code,
            detail=code,
        ).model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def _owner_response(
    body: dict[str, Any],
    *,
    etag: str | None = None,
) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if etag is not None:
        headers["ETag"] = etag
    return JSONResponse(status_code=status.HTTP_200_OK, content=body, headers=headers)


def _agent_response(
    body: dict[str, Any],
    *,
    status_code: int = status.HTTP_200_OK,
    etag: str | None = None,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if etag is not None:
        headers["ETag"] = etag
    if replayed:
        headers["Idempotent-Replay"] = "true"
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _transaction_etag(transaction: Any) -> str:
    return f'"transaction:{transaction.id}:v{transaction.version}"'


def _review_etag(review: Any) -> str:
    return f'"review:{review.id}:v{review.version}"'


def _expected_review_version(if_match: str | None, review_id: UUID) -> int:
    if if_match is None:
        raise ProblemError(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "resource_version_required",
            "Resource version required",
        )
    expected_prefix = f'"review:{review_id}:v'
    if not if_match.startswith(expected_prefix) or not if_match.endswith('"'):
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    try:
        version = int(if_match.removeprefix(expected_prefix).removesuffix('"'))
    except ValueError as error:
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        ) from error
    if version <= 0:
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    return version


def _transaction_etag_wire(body: dict[str, Any]) -> str:
    return f'"transaction:{body["id"]}:v{body["version"]}"'


def _expected_version(if_match: str | None, transaction_id: UUID) -> int:
    if if_match is None:
        raise ProblemError(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "resource_version_required",
            "Resource version required",
        )
    expected_prefix = f'"transaction:{transaction_id}:v'
    if not if_match.startswith(expected_prefix) or not if_match.endswith('"'):
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    try:
        version = int(if_match.removeprefix(expected_prefix).removesuffix('"'))
    except ValueError as error:
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        ) from error
    if version <= 0:
        raise ProblemError(
            status.HTTP_412_PRECONDITION_FAILED,
            "resource_version_stale",
            "Resource version is stale",
        )
    return version


def _required_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value) > 255:
        raise ProblemError(
            status.HTTP_400_BAD_REQUEST,
            "idempotency_key_required",
            "Idempotency key required",
        )
    return value.strip()


def _verify_writable_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path, prefix=".readiness-")
    try:
        os.write(descriptor, b"ready")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        Path(temporary_name).unlink(missing_ok=True)
