"""Verify the source checkpoint without contacting any service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast


class Manifest(TypedDict):
    source_files: dict[str, str]
    build_inputs: dict[str, str]
    frontend_assets: dict[str, str]
    native_sha256: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_under(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink()) and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def check_files(root: Path, expected: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for name, digest in sorted(expected.items()):
        path = root / name
        if path.is_symlink():
            failures.append(f"symlink: {name}")
        elif not path.is_file():
            failures.append(f"missing: {name}")
        elif sha256(path) != digest:
            failures.append(f"changed: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("manifest.json"))
    parser.add_argument("--assets", type=Path, help="Rebuilt app/static directory; enables asset verification")
    parser.add_argument("--native", type=Path, help="Linux ARM64 native binary; enables binary verification")
    args = parser.parse_args()
    manifest = cast(Manifest, json.loads(args.manifest.read_text()))
    failures = check_files(args.root, manifest["source_files"])
    actual = {
        f"{folder}/{name}"
        for folder in ("app", "scripts", "config")
        for name in files_under(args.root / folder)
        if folder != "app" or not name.startswith("static/")
    }
    failures.extend(f"unexpected source: {name}" for name in sorted(actual - manifest["source_files"].keys()))
    failures.extend(check_files(args.root, manifest["build_inputs"]))
    if args.assets is not None:
        expected_assets = manifest["frontend_assets"]
        failures.extend(check_files(args.assets, expected_assets))
        failures.extend(
            f"unexpected asset: {name}"
            for name in sorted(files_under(args.assets) - expected_assets.keys() - {".gitkeep"})
        )
    if args.native is not None:
        failures.extend(check_files(args.native.parent, {args.native.name: manifest["native_sha256"]}))
    if failures:
        print("Checkpoint verification FAILED:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"PASS: {len(manifest['source_files'])} runtime files and {len(manifest['build_inputs'])} build inputs")
    if args.assets is not None:
        print(f"PASS: {len(manifest['frontend_assets'])} rebuilt assets")
    if args.native is not None:
        print("PASS: native binary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
