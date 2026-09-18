from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NAS_SCRIPTS = REPO_ROOT / "scripts" / "nas"
UPGRADE_SCRIPT = NAS_SCRIPTS / "upgrade.sh"
DEPLOY_SCRIPT = NAS_SCRIPTS / "deploy-initial.sh"
BACKUP_SCRIPT = NAS_SCRIPTS / "backup.sh"
COMMON_SCRIPT = NAS_SCRIPTS / "common.sh"
COMPOSE_FILE = REPO_ROOT / "compose.nas.yaml"
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "nas-deployment.md"
API_UP_WAIT = "up --detach --wait --wait-timeout 120 --no-deps api"
WORKER_UP_WAIT = "up --detach --wait --wait-timeout 120 --no-deps --remove-orphans worker"

DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${BILLZEBUB_COMPOSE_LOG}"
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
  if [[ "${BILLZEBUB_COMPOSE_HAS_WAIT:-1}" == "1" ]]; then
    printf '%s\n' "Usage: docker compose up [OPTIONS]"
    printf '%s\n' "  --wait             Wait for services to be running|healthy"
    printf '%s\n' "  --wait-timeout int Maximum duration in seconds to wait"
  else
    printf '%s\n' "Usage: docker compose up [OPTIONS]"
  fi
  exit 0
fi
exit 0
"""

BACKUP_STUB = """#!/usr/bin/env bash
set -euo pipefail
printf 'backup\n' >>"${BILLZEBUB_BACKUP_LOG}"
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


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _compose_env(
    tmp_path: Path,
    *,
    ready_url: str,
    has_wait: bool = True,
) -> dict[str, str]:
    docker_bin = tmp_path / "docker"
    backup_script = tmp_path / "backup.sh"
    compose_log = tmp_path / "compose.log"
    backup_log = tmp_path / "backup.log"
    _write_executable(docker_bin, DOCKER_STUB)
    _write_executable(backup_script, BACKUP_STUB)
    compose_log.write_text("", encoding="utf-8")
    backup_log.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "DOCKER_BIN": str(docker_bin),
            "BILLZEBUB_BACKUP_SCRIPT": str(backup_script),
            "BILLZEBUB_READY_URL": ready_url,
            "BILLZEBUB_READY_ATTEMPTS": "2",
            "BILLZEBUB_READY_SLEEP": "0",
            "BILLZEBUB_COMPOSE_LOG": str(compose_log),
            "BILLZEBUB_BACKUP_LOG": str(backup_log),
            "BILLZEBUB_COMPOSE_HAS_WAIT": "1" if has_wait else "0",
        }
    )
    return env


def _run_script(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _subcommand(line: str) -> str:
    rest = line.removeprefix("compose ")
    while rest.startswith(("--project-name ", "--file ")):
        rest = rest.split(" ", 2)[2]
    return rest


def _operations(env: dict[str, str]) -> list[str]:
    return [
        _subcommand(line)
        for line in Path(env["BILLZEBUB_COMPOSE_LOG"]).read_text(encoding="utf-8").splitlines()
        if line.startswith("compose ") and not line.endswith(" up --help")
    ]


def test_nas_scripts_are_valid_bash() -> None:
    for script in (UPGRADE_SCRIPT, DEPLOY_SCRIPT, BACKUP_SCRIPT, COMMON_SCRIPT):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_upgrade_builds_before_recreate_and_serializes_api_then_worker(
    tmp_path: Path, ready_url: str
) -> None:
    env = _compose_env(tmp_path, ready_url=ready_url)
    result = _run_script(UPGRADE_SCRIPT, env)

    assert result.returncode == 0, result.stderr
    assert "API recreate window was" in result.stdout
    assert Path(env["BILLZEBUB_BACKUP_LOG"]).read_text(encoding="utf-8") == "backup\n"

    operations = _operations(env)
    assert operations[0] == "build api worker"
    assert any(
        command.startswith("up --detach --wait --wait-timeout 120 --no-recreate postgres")
        for command in operations
    )
    assert API_UP_WAIT in operations
    assert WORKER_UP_WAIT in operations
    assert operations.index("build api worker") < operations.index(API_UP_WAIT)
    assert operations.index(API_UP_WAIT) < operations.index(WORKER_UP_WAIT)
    joined = "\n".join(operations)
    assert "stop " not in joined
    assert "--replace-probe" not in joined
    assert "enable-tailscale-serve" not in joined


def test_upgrade_omits_wait_flags_when_compose_lacks_them(tmp_path: Path, ready_url: str) -> None:
    env = _compose_env(tmp_path, ready_url=ready_url, has_wait=False)
    result = _run_script(UPGRADE_SCRIPT, env)

    assert result.returncode == 0, result.stderr
    operations = _operations(env)
    assert "up --detach --no-recreate postgres" in operations
    assert "up --detach --no-deps api" in operations
    assert "up --detach --no-deps --remove-orphans worker" in operations
    assert all("--wait" not in command for command in operations)


def test_upgrade_health_gate_rejects_unready_api(tmp_path: Path) -> None:
    env = _compose_env(tmp_path, ready_url="http://127.0.0.1:1/health/ready")
    result = _run_script(UPGRADE_SCRIPT, env)

    assert result.returncode == 1
    assert "readiness did not succeed" in result.stderr
    operations = _operations(env)
    assert "build api worker" in operations
    assert API_UP_WAIT in operations
    assert WORKER_UP_WAIT not in operations


def test_deploy_initial_serializes_api_then_worker(tmp_path: Path, ready_url: str) -> None:
    env = _compose_env(tmp_path, ready_url=ready_url)
    result = _run_script(DEPLOY_SCRIPT, env)

    assert result.returncode == 0, result.stderr
    assert "Initial deployment completed and the API is ready." in result.stdout
    operations = _operations(env)
    assert operations[0] == "build api worker"
    assert "up --detach --wait --wait-timeout 120 postgres" in operations
    assert API_UP_WAIT in operations
    assert WORKER_UP_WAIT in operations
    assert operations.index(API_UP_WAIT) < operations.index(WORKER_UP_WAIT)


def test_upgrade_documentation_describes_build_first_and_serve_blip() -> None:
    script = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    docs = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "stop api worker" not in script
    assert "--replace-probe" not in script
    assert "billzebub_up_service postgres --no-recreate" in script
    assert "billzebub_up_service api --no-deps" in script
    assert "billzebub_up_service worker --no-deps --remove-orphans" in script
    assert "rebuilds the application image while the existing API and worker keep serving" in docs
    assert "PostgreSQL is never stopped" in docs
    assert "typically a few seconds" in docs
    assert "--replace-probe` is only the initial cutover" in docs
    assert "Database(Settings()).ping()" in compose
    assert "typesafe" not in compose.casefold()
    worker_block = compose.split("worker:")[1].split("migrate:")[0]
    assert "- egress" in worker_block
    assert "internal: false" in compose.split("egress:")[1]
    assert "typesafe" not in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").casefold()
    assert "--extra" not in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
