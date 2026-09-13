import pytest
from scripts import check_private_files
from scripts.check_private_files import find_private_files, private_reason


def test_rejects_private_financial_artifacts() -> None:
    paths = [
        "fixtures/private/dbs.pdf",
        "artifacts/ab/source.pdf",
        "prototypes/apple-shortcut-capture/runtime/token",
        "deploy/secrets/paylah_password",
        ".env.production",
        "backup.dump",
    ]

    assert [path for path, _reason in find_private_files(paths)] == sorted(paths)


def test_allows_synthetic_and_example_configuration() -> None:
    assert private_reason("fixtures/synthetic/card-statement.txt") is None
    assert private_reason(".env.example") is None
    assert private_reason("src/billzebub/runtime.py") is None


def test_check_fails_when_git_tracks_a_private_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        check_private_files,
        "git_visible_files",
        lambda: ["fixtures/private/real-statement.pdf"],
    )

    assert check_private_files.main() == 1
