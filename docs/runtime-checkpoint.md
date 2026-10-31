# Production source checkpoint

Source of truth: [runtime-source-checkpoints specification](../openspec/specs/runtime-source-checkpoints/spec.md).

The [2026-10-31 checkpoint](../deploy/runtime-checkpoints/2026-10-31/manifest.json)
preserves the observed runtime source and the frontend inputs that reproduce its
dashboard. It is a source checkpoint, not a copy of the production database,
credentials, configuration values, or complete container filesystem.

The manifest records every application, migration, supporting script and registry
file captured from the runtime, the generated dashboard asset hashes, the
installed Python package versions and the native binary hash. Build inputs are
hashed separately. The [verification record](../deploy/runtime-checkpoints/2026-10-31/verification.md)
distinguishes the verified boundaries and remaining limitations.

## Verify the checkout

Run from the repository root, using Python 3.14, Bun 1.4.4 and Node 26.12.1:

```sh
python3 deploy/runtime-checkpoints/2026-10-31/verify.py
uv sync --frozen --all-extras --dev --python 3.14
cd frontend
bun install --frozen-lockfile
bun run typecheck
node node_modules/vite/bin/vite.js build
cd ..
python3 deploy/runtime-checkpoints/2026-10-31/verify.py --assets app/static
```

Use Node to execute Vite. Executing the Vite entrypoint directly with Bun changes
the generated chunk hashes. No production access is needed for these checks.

The verifier rejects changed, missing or additional runtime source files. Asset
verification checks both the file set and every file's content. To compare a
separately obtained native binary, add `--native /path/to/codex-lb-native-egress`.
The verifier does not fetch binaries or contact the production service.

The native helper was reproduced with the existing Docker build stage:

```sh
docker build --platform linux/arm64 --target native-egress-build -t runtime-checkpoint-native .
docker run --rm --network none --entrypoint cat runtime-checkpoint-native /tmp/codex-lb-native-egress > /tmp/checkpoint-native
python3 deploy/runtime-checkpoints/2026-10-31/verify.py --native /tmp/checkpoint-native
```

This only builds and extracts the helper. It does not start the application.
