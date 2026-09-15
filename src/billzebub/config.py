"""Typed runtime configuration with fail-closed NAS validation."""

from __future__ import annotations

import stat
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    NAS = "nas"


class Settings(BaseSettings):
    """Configuration shared by the API, worker, migrations, and CLI."""

    model_config = SettingsConfigDict(
        env_prefix="BILLZEBUB_",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://billzebub:billzebub-development-only@127.0.0.1:54329/billzebub_test"
    )
    database_url_file: Path | None = None
    artifact_root: Path = Path(".tmp/artifacts")
    artifact_max_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    statement_inbox_root: Path = Path(".tmp/statement-inbox")
    statement_password_root: Path = Path(".tmp/statement-passwords")
    statement_stable_seconds: float = Field(default=30.0, gt=0, le=3600)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    trust_tailscale_headers: bool = False
    tailscale_allowed_logins: tuple[str, ...] = ()
    development_identity: str | None = None
    worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    apple_wallet_timezone: str | None = None
    apple_wallet_max_bytes: int = Field(default=16 * 1024, gt=0, le=1024 * 1024)
    web_root: Path | None = None
    categorizer_enabled: bool = True
    categorizer_min_confidence: Decimal = Field(
        default=Decimal("1.000"), ge=Decimal("0"), le=Decimal("1")
    )

    @field_validator("artifact_root", "statement_inbox_root", "statement_password_root")
    @classmethod
    def resolve_runtime_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("database_url_file", "web_root")
    @classmethod
    def resolve_optional_runtime_path(cls, value: Path | None) -> Path | None:
        return value.expanduser().absolute() if value is not None else None

    @field_validator("tailscale_allowed_logins")
    @classmethod
    def normalize_logins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(login.strip().casefold() for login in value if login.strip()))

    @field_validator("apple_wallet_timezone")
    @classmethod
    def validate_apple_wallet_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Apple Wallet timezone must be an IANA timezone") from error
        return value

    @model_validator(mode="after")
    def validate_security_mode(self) -> Self:
        if self.environment is not Environment.NAS:
            return self
        if not self.trust_tailscale_headers:
            raise ValueError("NAS mode requires trusted Tailscale headers")
        if not self.tailscale_allowed_logins:
            raise ValueError("NAS mode requires at least one allowlisted Tailscale login")
        if self.development_identity is not None:
            raise ValueError("NAS mode forbids a development identity")
        if self.database_url_file is None:
            raise ValueError("NAS mode requires a private database URL file")
        self._read_database_url_file()
        return self

    @property
    def database_url_value(self) -> str:
        """Reveal the URL only at the database construction seam."""
        if self.database_url_file is not None:
            return self._read_database_url_file()
        return self.database_url.get_secret_value()

    def _read_database_url_file(self) -> str:
        if self.database_url_file is None:
            raise ValueError("database URL file is not configured")
        try:
            metadata = self.database_url_file.lstat()
        except OSError as error:
            raise ValueError("database URL file is unavailable") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or self.database_url_file.is_symlink()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("database URL file is not private")
        try:
            value = self.database_url_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValueError("database URL file is unavailable") from error
        if not value or len(value) > 4096:
            raise ValueError("database URL file is invalid")
        return value
