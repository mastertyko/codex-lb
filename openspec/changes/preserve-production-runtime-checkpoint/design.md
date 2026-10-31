## Capture boundary

Use the published fork base as a history anchor, then replace application source
with the observed runtime files. Preserve the captured schema graph. Restore the
matching frontend build inputs, rather than combining arbitrary dirty worktrees.
The checkpoint records SHA-256 hashes for runtime source and generated assets.

## Exactness and verification

Application source parity and generated frontend parity are separate checks.
Verification must fail on missing, added or changed application source files.
Record the original image digest and native binary hash; source parity alone
does not establish a byte-identical container image. Record dependency and
toolchain evidence separately. Tests use local temporary storage only.

## Preservation constraint

Do not repair or reformat captured runtime code to make a generic gate pass:
that would cease to be the requested snapshot. Fix defects in checkpoint tooling
and report pre-existing source or infrastructure limitations accurately.
