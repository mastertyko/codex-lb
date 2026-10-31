from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_publication_privacy as privacy


def commit(root: Path, message: str = "fixture") -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return privacy.revision("HEAD", cwd=root)


@pytest.fixture
def publication_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Fixture")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "fixture@example.test")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    (root / "scripts").mkdir()
    shutil.copyfile(Path(privacy.__file__), root / "scripts/check_publication_privacy.py")
    (root / ".github").mkdir()
    exceptions = [
        {"path": item.path, "rule": item.rule, "sha256": item.fingerprint, "reason": "Public scanner rule constants"}
        for item in privacy.personal_findings(
            "scripts/check_publication_privacy.py", Path(privacy.__file__).read_bytes()
        )
    ]
    (root / ".github/publication-privacy-allowlist.json").write_text(json.dumps(exceptions))
    commit(root)
    return root


@pytest.fixture
def fake_gitleaks(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    scanner = binary_dir / "gitleaks"
    scanner.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, re, sys\n"
        "assert '--redact' in sys.argv and '--ignore-gitleaks-allow' in sys.argv\n"
        "assert not any(key.startswith('GITLEAKS_') for key in os.environ)\n"
        "if os.environ.get('FIXTURE_SCANNER_FAIL'):\n"
        "    print('sensitive-scanner-diagnostic', file=sys.stderr)\n"
        "    sys.exit(3)\n"
        "rows = []\n"
        "for path in pathlib.Path(sys.argv[-1]).rglob('*'):\n"
        "    if not path.is_file(): continue\n"
        "    for number, line in enumerate(path.read_bytes().splitlines(), 1):\n"
        "        if re.search(rb'ghp_' + rb'[A-Za-z0-9]{36}', line):\n"
        "            rows.append({'File': str(path), 'StartLine': number, 'RuleID': 'github-pat'})\n"
        "pathlib.Path(sys.argv[sys.argv.index('--report-path') + 1]).write_text(json.dumps(rows))\n"
        "sys.exit(1 if rows else 0)\n"
    )
    scanner.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + os.environ["PATH"])
    return binary_dir


def check(root: Path, *args: str, hook_input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check_publication_privacy.py", *args],
        cwd=root,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("payload", "rule"),
    [
        ("fixture-person@" + "mailhost.example.com", "personal-email"),
        ("/" + "Users/fixture-operator/local", "operator-path"),
        ("10." + "23.42.9", "private-address"),
        ("fixture-node." + "ts.net", "private-host"),
        ("ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "gitleaks:github-pat"),
    ],
)
def test_cli_blocks_and_redacts_sensitive_content(publication_repo, fake_gitleaks, payload, rule):
    (publication_repo / "note.txt").write_text(payload)
    head = commit(publication_repo)
    # Even a zero-diff invocation must inspect the entire tip tree.
    result = check(publication_repo, "--base", head)
    assert result.returncode == 1
    assert f"[{rule}]" in result.stdout
    assert payload not in result.stdout + result.stderr


def test_pre_push_checks_removed_content_and_commit_metadata(publication_repo, fake_gitleaks):
    base = privacy.revision("HEAD", cwd=publication_repo)
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    private_email = "fixture-person@" + "mailhost.example.com"
    (publication_repo / "removed.txt").write_text(secret)
    commit(publication_repo, "fixture contact " + private_email)
    (publication_repo / "removed.txt").unlink()
    head = commit(publication_repo)
    result = check(
        publication_repo,
        "--pre-push",
        hook_input=f"refs/heads/fixture {head} refs/heads/fixture {base}\n",
    )
    assert result.returncode == 1
    assert "removed.txt:1 [gitleaks:github-pat]" in result.stdout
    assert "commit-metadata:" in result.stdout
    assert secret not in result.stdout + result.stderr
    assert private_email not in result.stdout + result.stderr


def test_review_exception_is_exact_content_not_a_path_exemption(publication_repo, fake_gitleaks):
    original = "fixture-person@" + "mailhost.example.com"
    path = publication_repo / "note.txt"
    path.write_text(original)
    policy_path = publication_repo / ".github/publication-privacy-allowlist.json"
    policy = json.loads(policy_path.read_text()) + [
        {
            "path": "note.txt",
            "rule": "personal-email",
            "sha256": hashlib.sha256(original.encode()).hexdigest(),
            "reason": "Synthetic review fixture",
        }
    ]
    policy_path.write_text(json.dumps(policy))
    commit(publication_repo)
    assert check(publication_repo).returncode == 0
    path.write_text("changed-" + original)
    commit(publication_repo)
    assert check(publication_repo).returncode == 1


def test_synthetic_examples_pass_and_scanner_environment_cannot_suppress(publication_repo, fake_gitleaks, monkeypatch):
    (publication_repo / "note.txt").write_text("fixture@example.test https://example.invalid 127.0.0.1")
    commit(publication_repo)
    monkeypatch.setenv("GITLEAKS_CONFIG", "/does-not-exist")
    assert check(publication_repo).returncode == 0


def test_scanner_failure_is_closed_and_redacted(publication_repo, fake_gitleaks, monkeypatch):
    monkeypatch.setenv("FIXTURE_SCANNER_FAIL", "1")
    result = check(publication_repo)
    assert result.returncode == 2
    assert "sensitive-scanner-diagnostic" not in result.stdout + result.stderr


def test_missing_scanner_invalid_policy_and_revision_fail_closed(publication_repo, monkeypatch):
    monkeypatch.setattr(privacy.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Gitleaks is required"):
        privacy.scan("HEAD", [], cwd=publication_repo)
    policy = publication_repo / ".github/publication-privacy-allowlist.json"
    policy.write_text('[{"reason": ""}]')
    with pytest.raises(RuntimeError, match="review reason"):
        privacy.allowed_findings(policy)
    assert check(publication_repo, "--head", "unresolvable-fixture-revision").returncode == 2


def test_pre_push_ref_deletion_needs_no_scan(publication_repo):
    result = check(
        publication_repo, "--pre-push", hook_input=f"(delete) {privacy.ZERO} refs/heads/fixture {'a' * 40}\n"
    )
    assert result.returncode == 0


@pytest.mark.parametrize("data", [b"picture\0data", b"\xff\xd8\xff"])
def test_new_binary_assets_require_review(data):
    assert privacy.personal_findings("new-image.jpg", data)[0].rule == "binary-review"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="real Gitleaks smoke runs in publication CI")
def test_real_gitleaks_detects_a_removed_synthetic_token(publication_repo):
    base = privacy.revision("HEAD", cwd=publication_repo)
    (publication_repo / "removed.txt").write_text("token = " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
    commit(publication_repo)
    (publication_repo / "removed.txt").unlink()
    commit(publication_repo)
    result = check(publication_repo, "--base", base)
    assert result.returncode == 1
    assert "[gitleaks:github-pat]" in result.stdout


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="real Gitleaks smoke runs in publication CI")
def test_repository_scanner_config_cannot_suppress_secret_detection(publication_repo):
    base = privacy.revision("HEAD", cwd=publication_repo)
    (publication_repo / ".gitleaks.toml").write_text('[allowlist]\nregexes = [".*"]\n')
    (publication_repo / ".gitleaksignore").write_text("payload.txt:github-pat:1\n")
    (publication_repo / "payload.txt").write_text(
        "token = " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8 # gitleaks:allow"
    )
    commit(publication_repo)
    result = check(publication_repo, "--base", base)
    assert result.returncode == 1
    assert "[gitleaks:github-pat]" in result.stdout
