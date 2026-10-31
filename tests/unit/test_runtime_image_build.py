from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_runtime_image as builder


@pytest.fixture
def build_repo(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    for name in builder.INPUTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + name)
    (root / ".gitignore").write_text("private.env\n")
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Fixture")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "fixture@example.test")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "private.env").write_text("ignored local configuration")
    return root


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    record = tmp_path / "docker-record.json"
    executable = binary_dir / "docker"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "record = pathlib.Path(os.environ['FIXTURE_DOCKER_RECORD'])\n"
        "image_id = 'sha256:' + 'a' * 64\n"
        "if sys.argv[1] == 'build':\n"
        "    labels = dict(sys.argv[i+1].split('=', 1) for i, v in enumerate(sys.argv) if v == '--label')\n"
        "    source = pathlib.Path(sys.argv[-1])\n"
        "    files = sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file())\n"
        "    record.write_text(json.dumps({'files': files, 'labels': labels}))\n"
        "    pathlib.Path(sys.argv[sys.argv.index('--iidfile') + 1]).write_text(image_id)\n"
        "else:\n"
        "    labels = json.loads(record.read_text())['labels']\n"
        "    if os.environ.get('FIXTURE_BAD_LABEL'): labels['org.opencontainers.image.revision'] = 'wrong'\n"
        "    print(json.dumps({'id': image_id, 'os': 'linux', 'architecture': 'arm64', 'labels': labels}))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FIXTURE_DOCKER_RECORD", str(record))
    return record


def build(root: Path, receipt: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, builder.__file__, "--tag", "fixture:local", "--receipt", str(receipt)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("kind", ["unstaged", "staged", "untracked"])
def test_dirty_source_is_rejected_before_docker(build_repo, fake_docker, tmp_path, kind):
    (build_repo / ("untracked.txt" if kind == "untracked" else "Dockerfile")).write_text("changed")
    if kind == "staged":
        subprocess.run(["git", "add", "Dockerfile"], cwd=build_repo, check=True)
    receipt = tmp_path / "receipt.json"
    assert build(build_repo, receipt).returncode == 1
    assert not fake_docker.exists()
    assert not receipt.exists()


def test_clean_commit_only_context_and_verified_portable_receipt(build_repo, fake_docker, tmp_path):
    receipt = tmp_path / "receipt.json"
    assert build(build_repo, receipt).returncode == 0
    context = json.loads(fake_docker.read_text())
    result = json.loads(receipt.read_text())
    assert context["files"] == sorted([*builder.INPUTS, ".gitignore"])
    assert result["revision"] == builder.git(build_repo, "rev-parse", "HEAD").decode().strip()
    assert result["revision"] == context["labels"][builder.REVISION_LABEL]
    assert result["build_inputs_sha256"] == context["labels"][builder.INPUTS_LABEL]
    assert result["image_id"] == "sha256:" + "a" * 64
    assert result["platform"] == "linux/arm64"
    assert str(tmp_path) not in receipt.read_text()
    assert builder.git(build_repo, "status", "--porcelain") == b""


def test_mismatched_image_cannot_get_a_receipt(build_repo, fake_docker, tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_BAD_LABEL", "1")
    receipt = tmp_path / "receipt.json"
    assert build(build_repo, receipt).returncode == 1
    assert not receipt.exists()


def test_existing_receipt_cannot_be_reused(build_repo, fake_docker, tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("previous build")
    assert build(build_repo, receipt).returncode == 1
    assert receipt.read_text() == "previous build"
    assert not fake_docker.exists()
