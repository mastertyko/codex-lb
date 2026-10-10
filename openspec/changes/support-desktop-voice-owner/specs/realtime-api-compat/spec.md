## ADDED Requirements

### Requirement: Desktop Voice does not weaken pooled call bindings
Existing private pool-created call routes MUST continue requiring their registered proxy-key-scoped owner binding and exact-owner policy. An unknown, expired or abandoned binding MUST NOT fall back to Desktop Voice, another account or a caller credential. The separate Desktop Voice capability MUST be entered only through its explicit routes with both registered gateway admission and authenticated caller identity.

#### Scenario: Old route receives unknown external call
- **WHEN** an external call is presented to an existing pooled Live route
- **THEN** the existing binding denial remains unchanged and no new Desktop Voice path is attempted
