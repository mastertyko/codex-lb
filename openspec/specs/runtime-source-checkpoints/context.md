# Runtime checkpoint context

Production hotfix overlays can combine source from several local branches. A
commit label alone cannot identify the resulting runtime. The checkpoint keeps
the actual source bytes and hashes their complete file set, including migrations
and supporting scripts. It does not include production configuration values,
secrets, databases, logs, account records or the container's writable data.

For example, the 2026-10-31 checkpoint records 795 runtime source/support files
and 90 generated dashboard assets. It reconstructs the frontend build inputs
and compares generated assets by content, not merely by bundle filenames.

The native helper and Python dependency versions are separate provenance
boundaries. A source match does not prove an identical operating system image.
The captured digest identifies the original image; the branch is not advertised
as a byte-reproducible container image or a new production deployment.

Source files remain unchanged even when a general development gate detects an
existing issue. Such failures belong in the verification record. Editing runtime
code to satisfy a gate would create a new version instead of preserving the
observed one. Future corrective development should use a separate change.

See [operator instructions](../../../docs/runtime-checkpoint.md) and the
[verification record](../../../deploy/runtime-checkpoints/2026-10-31/verification.md).
