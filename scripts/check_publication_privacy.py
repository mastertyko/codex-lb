"""Fail closed on unreviewed secrets or personal data in Git publication content."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github/publication-privacy-allowlist.json"
ZERO = "0" * 40
EMAIL = re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[A-Za-z]{2,}")
HOST_PATH = re.compile(r"/(?:Users|Volumes|home)/[^\s\"'`<>]+|[A-Za-z]:\\Users\\[^\s\"'`<>]+")
PRIVATE_HOST = re.compile(r"\b[\w.-]+\.ts\.net\b")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
SENSITIVE_NAME = re.compile(r"(?:^|/)(?:\.env(?:\..*)?|id_rsa|id_ed25519|credentials\.json|auth\.json)$")
SYNTHETIC_DOMAINS = ("example.com", "example.org", "example.net", "example.invalid", "example.test")


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule: str
    fingerprint: str


def git(*args: str, cwd: Path = ROOT) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Git publication inspection failed")
    return result.stdout


def revision(value: str, *, cwd: Path = ROOT) -> str:
    return git("rev-parse", "--verify", "--end-of-options", value + "^{commit}", cwd=cwd).decode().strip()


def finding(path: str, line: int, rule: str, content: bytes) -> Finding:
    return Finding(path, line, rule, hashlib.sha256(content).hexdigest())


def personal_findings(path: str, content: bytes) -> list[Finding]:
    found: list[Finding] = []
    if SENSITIVE_NAME.search(path) and path.rsplit("/", 1)[-1] != ".env.example":
        found.append(finding(path, 0, "sensitive-filename", content))
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return [*found, finding(path, 0, "binary-review", content)]
    if b"\0" in content:
        return [*found, finding(path, 0, "binary-review", content)]
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.decode("utf-8", errors="replace")
        for email in EMAIL.findall(line):
            domain = email.rsplit("@", 1)[1].lower()
            if not (
                domain in SYNTHETIC_DOMAINS
                or domain.endswith((".example", ".invalid", ".test", ".localhost", ".users.noreply.github.com"))
                or domain == "users.noreply.github.com"
            ):
                found.append(finding(path, number, "personal-email", raw))
        if HOST_PATH.search(line):
            found.append(finding(path, number, "operator-path", raw))
        if PRIVATE_HOST.search(line):
            found.append(finding(path, number, "private-host", raw))
        for candidate in IPV4.findall(line):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if any(address in block for block in PRIVATE_NETWORKS):
                found.append(finding(path, number, "private-address", raw))
    return found


PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
)


def tree_files(commit: str, *, cwd: Path = ROOT, paths: set[str] | None = None) -> dict[str, bytes]:
    entries = git("ls-tree", "-rz", commit, cwd=cwd).split(b"\0")
    names: list[str] = []
    objects: list[bytes] = []
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        decoded = name.decode()
        if paths is not None and decoded not in paths:
            continue
        if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            raise RuntimeError("Publication includes an unsupported Git object")
        if PurePosixPath(decoded).is_absolute() or ".." in PurePosixPath(decoded).parts:
            raise RuntimeError("Publication includes an unsafe Git path")
        names.append(decoded)
        objects.append(oid)
    result = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=cwd, input=b"\n".join(objects) + b"\n", capture_output=True, check=True
    )
    output = result.stdout
    offset = 0
    files: dict[str, bytes] = {}
    for name in names:
        end = output.index(b"\n", offset)
        size = int(output[offset:end].rsplit(b" ", 1)[1])
        offset = end + 1
        files[name] = output[offset : offset + size]
        offset += size + 1
    return files


def allowed_findings(policy: Path = POLICY) -> set[tuple[str, str, str]]:
    rows = json.loads(policy.read_text())
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or set(row) != {"path", "rule", "sha256", "reason"}
        or any(not isinstance(value, str) or not value.strip() for value in row.values())
        or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
        for row in rows
    ):
        raise RuntimeError("Publication privacy exceptions require a review reason")
    return {(row["path"], row["rule"], row["sha256"]) for row in rows}


def scan(commit: str, commits: list[str], *, cwd: Path = ROOT, policy: Path = POLICY) -> list[Finding]:
    if shutil.which("gitleaks") is None:
        raise RuntimeError("Gitleaks is required; install the pinned version from the publication documentation")
    allowed = allowed_findings(policy)
    results: set[Finding] = set()
    seen: set[tuple[str, str]] = set()
    # Inspect each new commit's changed blobs, plus the complete final tree.
    # This catches content removed by a later commit, including initial commits.
    for current in dict.fromkeys([commit, *commits]):
        changed = None
        if current != commit:
            changed = set(
                git("diff-tree", "--root", "-m", "--no-commit-id", "--name-only", "-r", "-z", current, cwd=cwd)
                .decode()
                .split("\0")
            )
        files = tree_files(current, cwd=cwd, paths=changed)
        metadata_name = "commit-metadata"
        while metadata_name in files:
            metadata_name += "_"
        files[metadata_name] = git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", current, cwd=cwd)
        with tempfile.TemporaryDirectory(prefix="publication-privacy-") as temporary:
            directory = Path(temporary)
            content_root = directory / "tree"
            content_root.mkdir()
            for name, data in files.items():
                digest = hashlib.sha256(data).hexdigest()
                if (name, digest) in seen:
                    continue
                seen.add((name, digest))
                target = content_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                results.update(personal_findings(name, data))
            report = directory / "findings.json"
            config = directory / "scanner.toml"
            config.write_text("[extend]\nuseDefault = true\n")
            ignore = directory / "scanner.ignore"
            ignore.write_text("")
            process = subprocess.run(
                [
                    "gitleaks",
                    "dir",
                    "--no-banner",
                    "--redact",
                    "--ignore-gitleaks-allow",
                    "--config",
                    str(config),
                    "--gitleaks-ignore-path",
                    str(ignore),
                    "--report-format",
                    "json",
                    "--report-path",
                    str(report),
                    str(content_root),
                ],
                cwd=directory,
                capture_output=True,
                check=False,
                env={key: value for key, value in os.environ.items() if not key.startswith("GITLEAKS_")},
            )
            if process.returncode not in (0, 1) or not report.is_file():
                raise RuntimeError("Gitleaks failed; raw scanner output withheld")
            for item in json.loads(report.read_text()):
                path = Path(item["File"])
                if not path.is_absolute():
                    path = directory / path
                name = path.relative_to(content_root).as_posix()
                number = int(item["StartLine"])
                lines = files[name].splitlines()
                raw = lines[number - 1] if 0 < number <= len(lines) else files[name]
                results.add(finding(name, number, "gitleaks:" + item["RuleID"], raw))
    return sorted(item for item in results if (item.path, item.rule, item.fingerprint) not in allowed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", default="HEAD")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--base")
    scope.add_argument("--all-history", action="store_true")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--pre-push", action="store_true")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.remote):
            raise RuntimeError("Invalid remote name")
        ranges = [(args.head, args.base)]
        if args.pre_push:
            ranges = []
            for line in sys.stdin:
                _local_ref, local_sha, _remote_ref, remote_sha = line.split()
                if local_sha != ZERO:
                    ranges.append((local_sha, None if remote_sha == ZERO else remote_sha))
        unresolved: set[Finding] = set()
        for head, base in ranges:
            head = revision(head)
            excluded = (
                ["^" + revision(base)] if base else [] if args.all_history else ["--not", "--remotes=" + args.remote]
            )
            commits = git("rev-list", head, *excluded).decode().splitlines()
            unresolved.update(scan(head, commits))
        if unresolved:
            for item in sorted(unresolved):
                print(f"BLOCKED {item.path}:{item.line} [{item.rule}] sha256={item.fingerprint}")
            return 1
        print("Publication privacy check passed: no unreviewed findings.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        print("Publication privacy check failed: tooling, policy or Git input could not be verified.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
