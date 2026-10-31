# Publication privacy

The local gate scans actual Git publication content rather than untracked runtime state. Gitleaks runs in an isolated directory with redacted reports and without repository or environment suppressions. An additional scan covers common personal/infrastructure identifiers. The final tree is always checked; changed blobs and metadata from newly published commits catch removed-later content.

Exceptions are exact path/rule/content fingerprints with a reason. Existing public upstream images, attribution and synthetic test addresses establish the reviewed baseline; replacement data receives a new fingerprint and therefore requires a new review. Exceptions are not a way to publish real operator information. Binary content requires review because text rules cannot inspect images reliably.

Example: a token added in commit A and removed in commit B still blocks a push containing both commits. A new image blocks until its actual content has been reviewed; renaming an approved image does not silently inherit the old path's exception.

Use `scripts/push_checked.sh` so pre-push receives Git's actual refs. This per-invocation hook leaves other worktrees' configuration alone. CI uses the same gate but runs after upload; it cannot substitute for the local check. Missing tools or uncertain input fail closed. A passed pattern scan still needs a diff/history review for data the rules cannot recognize.
