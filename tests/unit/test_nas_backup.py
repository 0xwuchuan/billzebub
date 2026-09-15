from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from tests.unit.test_nas_upgrade import (
    BACKUP_SCRIPT,
    DEPLOYMENT_DOC,
    UPGRADE_SCRIPT,
    _operations,
    _run_script,
    _write_executable,
)

SYNTHETIC_PASSWORD = "synthetic-password"  # pragma: allowlist secret

BACKUP_DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail

pgpassword_for_exec=""
redacted_args=()
args=("$@")
i=0
while (( i < ${#args[@]} )); do
  arg="${args[$i]}"
  if [[ "$arg" == "-e" || "$arg" == "--env" ]]; then
    spec="${args[$((i + 1))]:-}"
    redacted_args+=("$arg")
    if [[ "$spec" == "PGPASSWORD" ]]; then
      pgpassword_for_exec="${PGPASSWORD:-}"
      redacted_args+=("PGPASSWORD")
    elif [[ "$spec" == PGPASSWORD=* ]]; then
      pgpassword_for_exec="${spec#PGPASSWORD=}"
      redacted_args+=("PGPASSWORD=<redacted>")
    else
      redacted_args+=("$spec")
    fi
    i=$((i + 2))
    continue
  fi
  if [[ "$arg" == PGPASSWORD=* ]]; then
    pgpassword_for_exec="${arg#PGPASSWORD=}"
    redacted_args+=("PGPASSWORD=<redacted>")
    i=$((i + 1))
    continue
  fi
  redacted_args+=("$arg")
  i=$((i + 1))
done
printf '%s\n' "${redacted_args[*]}" >>"${BILLZEBUB_COMPOSE_LOG}"

if [[ "${1:-}" != "compose" ]]; then
  exit 0
fi
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-name|--file)
      shift 2
      ;;
    *)
      break
      ;;
  esac
done
if [[ "${1:-}" == "up" && "${2:-}" == "--help" ]]; then
  printf '%s\n' "Usage: docker compose up [OPTIONS]"
  printf '%s\n' "  --wait             Wait for services to be running|healthy"
  printf '%s\n' "  --wait-timeout int Maximum duration in seconds to wait"
  exit 0
fi

is_pg_dump=0
is_pg_restore=0
for arg in "$@"; do
  case "$arg" in
    pg_dump) is_pg_dump=1 ;;
    pg_restore) is_pg_restore=1 ;;
  esac
done

if [[ "$is_pg_dump" == 1 ]]; then
  if [[ -z "$pgpassword_for_exec" ]]; then
    echo "pg_dump: error: connection to server failed: fe_sendauth: no password supplied" >&2
    exit 1
  fi
  printf 'pg_dump_password=1\n' >>"${BILLZEBUB_BACKUP_EXEC_LOG}"
  printf 'FAKE-CUSTOM-DUMP'
  exit 0
fi
if [[ "$is_pg_restore" == 1 ]]; then
  exit 0
fi
exit 0
"""


class ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health/ready":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def ready_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadyHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/health/ready"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _backup_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    backup_root = tmp_path / "backups"
    secrets_root = tmp_path / "secrets"
    backup_root.mkdir()
    secrets_root.mkdir()
    return backup_root, secrets_root, secrets_root / "postgres-password"


def _backup_env(
    tmp_path: Path,
    *,
    write_password: bool = True,
    password: str = SYNTHETIC_PASSWORD,
) -> dict[str, str]:
    docker_bin = tmp_path / "docker"
    backup_root, secrets_root, password_file = _backup_paths(tmp_path)
    compose_log = tmp_path / "compose.log"
    exec_log = tmp_path / "exec.log"
    _write_executable(docker_bin, BACKUP_DOCKER_STUB)
    compose_log.write_text("", encoding="utf-8")
    exec_log.write_text("", encoding="utf-8")
    if write_password:
        password_file.write_text(f"{password}\n", encoding="utf-8")
        password_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    env = os.environ.copy()
    env.update(
        {
            "DOCKER_BIN": str(docker_bin),
            "BILLZEBUB_BACKUP_ROOT": str(backup_root),
            "BILLZEBUB_SECRETS_ROOT": str(secrets_root),
            "BILLZEBUB_COMPOSE_LOG": str(compose_log),
            "BILLZEBUB_BACKUP_EXEC_LOG": str(exec_log),
        }
    )
    env.pop("BILLZEBUB_BACKUP_SCRIPT", None)
    env.pop("PGPASSWORD", None)
    return env


def _dump_files(env: dict[str, str]) -> list[Path]:
    return sorted(Path(env["BILLZEBUB_BACKUP_ROOT"]).glob("*.dump"))


def test_backup_passes_pgpassword_from_host_secret(tmp_path: Path) -> None:
    env = _backup_env(tmp_path)
    result = _run_script(BACKUP_SCRIPT, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Database backup completed and verified.\n"
    assert SYNTHETIC_PASSWORD not in result.stdout
    assert SYNTHETIC_PASSWORD not in result.stderr
    assert ".dump" not in result.stdout
    assert Path(env["BILLZEBUB_BACKUP_EXEC_LOG"]).read_text(encoding="utf-8") == (
        "pg_dump_password=1\n"
    )

    dumps = _dump_files(env)
    assert len(dumps) == 1
    assert dumps[0].read_text(encoding="utf-8") == "FAKE-CUSTOM-DUMP"
    assert dumps[0].stat().st_mode & 0o777 == 0o600
    assert not list(Path(env["BILLZEBUB_BACKUP_ROOT"]).glob(".pending.*"))

    compose_log = Path(env["BILLZEBUB_COMPOSE_LOG"]).read_text(encoding="utf-8")
    assert SYNTHETIC_PASSWORD not in compose_log
    assert "exec -T -e PGPASSWORD postgres pg_dump" in compose_log
    assert "pg_restore --list" in compose_log


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ("missing", "Database secret is unavailable."),
        ("empty", "Database secret is unavailable."),
        ("symlink-file", "Database secret is unavailable."),
        ("symlink-dir", "Database secret is unavailable."),
        ("missing-backup", "Private backup storage is unavailable."),
    ],
)
def test_backup_fails_closed_without_usable_secret(
    tmp_path: Path, mutate: str, message: str
) -> None:
    env = _backup_env(tmp_path)
    backup_root = Path(env["BILLZEBUB_BACKUP_ROOT"])
    secrets_root = Path(env["BILLZEBUB_SECRETS_ROOT"])
    password_file = secrets_root / "postgres-password"

    if mutate == "missing":
        password_file.unlink()
    elif mutate == "empty":
        password_file.write_text("\n", encoding="utf-8")
    elif mutate == "symlink-file":
        target = tmp_path / "elsewhere-password"
        target.write_text(f"{SYNTHETIC_PASSWORD}\n", encoding="utf-8")
        password_file.unlink()
        password_file.symlink_to(target)
    elif mutate == "symlink-dir":
        real_secrets = tmp_path / "real-secrets"
        real_secrets.mkdir()
        (real_secrets / "postgres-password").write_text(
            f"{SYNTHETIC_PASSWORD}\n", encoding="utf-8"
        )
        password_file.unlink()
        secrets_root.rmdir()
        secrets_root.symlink_to(real_secrets)
    elif mutate == "missing-backup":
        backup_root.rmdir()
    else:
        raise AssertionError(mutate)

    env["PGPASSWORD"] = SYNTHETIC_PASSWORD
    result = _run_script(BACKUP_SCRIPT, env)

    assert result.returncode == 1
    assert message in result.stderr
    assert SYNTHETIC_PASSWORD not in result.stdout
    assert SYNTHETIC_PASSWORD not in result.stderr
    assert _dump_files(env) == []
    assert Path(env["BILLZEBUB_BACKUP_EXEC_LOG"]).read_text(encoding="utf-8") == ""


def test_upgrade_keeps_using_backup_script_with_pgpassword(
    tmp_path: Path, ready_url: str
) -> None:
    env = _backup_env(tmp_path)
    env.update(
        {
            "BILLZEBUB_READY_URL": ready_url,
            "BILLZEBUB_READY_ATTEMPTS": "2",
            "BILLZEBUB_READY_SLEEP": "0",
        }
    )
    result = _run_script(UPGRADE_SCRIPT, env)

    assert result.returncode == 0, result.stderr
    assert "Upgrade completed and the API is ready." in result.stdout
    assert Path(env["BILLZEBUB_BACKUP_EXEC_LOG"]).read_text(encoding="utf-8") == (
        "pg_dump_password=1\n"
    )
    assert _dump_files(env)
    operations = _operations(env)
    assert operations[0] == "build api worker"
    assert any(command.startswith("exec -T -e PGPASSWORD postgres pg_dump") for command in operations)
    assert "stop " not in "\n".join(operations)


def test_backup_documentation_describes_pgpassword_from_host_secret() -> None:
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    docs = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    upgrade = UPGRADE_SCRIPT.read_text(encoding="utf-8")

    assert 'password_file="$secrets_root/postgres-password"' in script
    assert "exec -T -e PGPASSWORD postgres pg_dump" in script
    assert all(
        "PGPASSWORD" not in line and "postgres-password" not in line
        for line in script.splitlines()
        if line.lstrip().startswith("echo")
    )
    assert "supplies it as `PGPASSWORD` to `pg_dump`" in docs
    assert "refuses to run if that secret is missing" in docs
    assert 'backup_script="${BILLZEBUB_BACKUP_SCRIPT:-$project_root/scripts/nas/backup.sh}"' in upgrade
    assert '"$backup_script"' in upgrade
