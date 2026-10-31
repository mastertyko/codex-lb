# Checked publication and source builds

Specifications: [publication privacy](../../openspec/specs/publication-privacy/spec.md) and [deployment installation](../../openspec/specs/deployment-installation/spec.md).

## Before a push

Install Gitleaks v8.30.1 using its official release or the pinned Go module:

```sh
go install github.com/zricethezav/gitleaks/v8@v8.30.1
python3 scripts/check_publication_privacy.py --head HEAD --base origin/main
scripts/push_checked.sh origin HEAD
```

Put the installed executable on `PATH`. The push wrapper selects `.github/hooks` for that invocation only, preserving other worktrees' Git configuration. It scans the refs Git actually intends to push, including each newly published commit and the complete final tree. A secret deleted by a subsequent commit still blocks the push. Ref deletion requires no content scan.

The CI `Publication privacy` job uses immutable event base/head revisions, a full checkout and the same scanner. This CI check is a second check after publication; the local pre-push gate is what prevents a rejected Git upload. For a first publication with no baseline, use `--all-history`.

Output contains paths, line numbers, rule names and content fingerprints, never matched values. Missing Gitleaks, invalid policy, unresolved commits and scanner failures block the check. The scanner covers Gitleaks rules plus personal emails, operator paths, private IPv4/Tailscale addresses, sensitive filenames and unreviewed binary assets. Pattern detection does not replace review: names, images, encoded data and novel secret formats may need human inspection.

Reviewed public upstream assets, attribution and synthetic examples have exact-content exceptions in `.github/publication-privacy-allowlist.json`. Changing their contents triggers review again. Review the underlying finding privately before adding an exception; never upload a raw scanner report, account export or screenshot to explain one. Git author/committer metadata and messages are scanned too; use a public GitHub noreply identity for new publication commits.

## Build a traceable image

Start with a clean, committed checkout. Keep the receipt outside the checkout and choose a new path per build:

```sh
python3 scripts/build_runtime_image.py \
  --tag codex-lb:verified \
  --platform linux/arm64 \
  --receipt ../build-receipt.json
```

The command exports `git archive HEAD` into a temporary context, so ignored local files cannot enter the build. It preserves the lockfiles and verifies the resulting image's source revision, build-input fingerprint, platform and image ID before writing the receipt. Staged, unstaged or untracked changes fail before Docker starts. An existing receipt cannot be reused.

The receipt contains source/lockfile hashes and the local image content ID. It is not a registry manifest digest, proof of a completed deployment, or a promise of byte-identical rebuilds: base-image tags and operating-system package updates can change. Publish and deploy a selected image only through the authorized deployment workflow, then verify that runtime's digest and schema independently.

The historical `deploy/runtime-checkpoints/2026-10-31` manifest belongs to its original checkpoint commit. Later fixes intentionally change source and build outputs; compare that manifest at the preserved checkpoint revision, not at a newer implementation branch.
