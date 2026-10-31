"""Build an image from a clean commit and record portable, verified provenance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

INPUTS = (
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
    "crates/codex-lb-egress/Cargo.toml",
    "crates/codex-lb-egress-worker/Cargo.toml",
    "crates/codex-lb-protocol/Cargo.toml",
    "crates/codex-lb-responses/Cargo.toml",
    "frontend/package.json",
    "frontend/bun.lock",
)
REVISION_LABEL = "org.opencontainers.image.revision"
INPUTS_LABEL = "io.codex-lb.build-inputs.sha256"


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def build(root: Path, tag: str, platform: str, receipt: Path) -> dict[str, object]:
    if receipt.exists():
        raise FileExistsError("Choose a new receipt path for each build")
    root = Path(git(root, "rev-parse", "--show-toplevel").decode().strip())
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("A clean committed source tree is required")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    inputs = {name: hashlib.sha256(git(root, "show", f"{revision}:{name}")).hexdigest() for name in INPUTS}
    inputs_digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="codex-lb-committed-build-") as directory:
        temporary = Path(directory)
        context = temporary / "source"
        context.mkdir()
        archive = git(root, "archive", "--format=tar", revision)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(context, filter="data")
        image_id_path = temporary / "image-id"
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                platform,
                "--iidfile",
                str(image_id_path),
                "--tag",
                tag,
                "--label",
                f"{REVISION_LABEL}={revision}",
                "--label",
                f"{INPUTS_LABEL}={inputs_digest}",
                str(context),
            ],
            check=True,
        )
        image_id = image_id_path.read_text().strip()
        inspected = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    image_id,
                    "--format",
                    '{"id":{{json .Id}},"os":{{json .Os}},'
                    '"architecture":{{json .Architecture}},"labels":{{json .Config.Labels}}}',
                ]
            )
        )
    if inspected["id"] != image_id or inspected["labels"].get(REVISION_LABEL) != revision:
        raise RuntimeError("Built image revision could not be verified")
    if inspected["labels"].get(INPUTS_LABEL) != inputs_digest:
        raise RuntimeError("Built image dependency provenance could not be verified")
    actual_platform = inspected["os"] + "/" + inspected["architecture"]
    if actual_platform != platform:
        raise RuntimeError("Built image platform differs from the requested platform")
    result: dict[str, object] = {
        "schema_version": 1,
        "revision": revision,
        "image_id": image_id,
        "platform": actual_platform,
        "build_inputs": inputs,
        "build_inputs_sha256": inputs_digest,
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--platform", choices=("linux/arm64", "linux/amd64"), default="linux/arm64")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(Path.cwd(), args.tag, args.platform, args.receipt)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Build failed: {type(error).__name__}; no verified receipt was produced.")
        return 1
    print(f"Verified image {result['image_id']} from commit {result['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
