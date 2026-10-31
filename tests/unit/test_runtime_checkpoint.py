from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

VERIFIER = Path(__file__).resolve().parents[2] / "deploy/runtime-checkpoints/2026-10-31/verify.py"


@pytest.mark.parametrize("mutation", [None, "changed", "missing", "extra", "asset", "input", "native", "symlink"])
def test_checkpoint_cli_detects_content_drift(tmp_path: Path, mutation: str | None) -> None:
    paths = ("app/main.py", "frontend/package.json", "assets/index.html", "native")
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    digest = hashlib.sha256(b"fixture\n").hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_files": {"app/main.py": digest},
                "build_inputs": {"frontend/package.json": digest},
                "frontend_assets": {"index.html": digest},
                "native_sha256": digest,
            }
        )
    )
    if mutation == "changed":
        (tmp_path / "app/main.py").write_text("changed\n")
    elif mutation == "missing":
        (tmp_path / "app/main.py").unlink()
    elif mutation == "extra":
        (tmp_path / "app/extra.py").write_text("extra\n")
    elif mutation == "asset":
        (tmp_path / "assets/extra.js").write_text("extra\n")
    elif mutation == "input":
        (tmp_path / "frontend/package.json").write_text("changed\n")
    elif mutation == "native":
        (tmp_path / "native").write_text("changed\n")
    elif mutation == "symlink":
        (tmp_path / "app/main.py").unlink()
        (tmp_path / "app/main.py").symlink_to(tmp_path / "native")
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--root",
            str(tmp_path),
            "--manifest",
            str(manifest),
            "--assets",
            str(tmp_path / "assets"),
            "--native",
            str(tmp_path / "native"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (0 if mutation is None else 1), result.stdout + result.stderr
