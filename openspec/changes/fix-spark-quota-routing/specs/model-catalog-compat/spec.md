## ADDED Requirements

### Requirement: Fresh additional-quota evidence can establish account support

For a model canonically mapped to a separately metered additional quota, account selection MUST allow fresh account-specific additional-quota telemetry to establish model support when an authoritative general per-account model catalog omits that model. The system MUST continue to enforce registry plan and service-tier restrictions and MUST apply the existing additional-quota freshness, exhaustion, account-health, cooldown, capacity, security, and routing gates before selecting an account. This behavior MUST NOT apply to unknown models or to an unrelated additional-limit key supplied independently of the requested model.

#### Scenario: Fresh Spark quota overrides general account-catalog omission

- **GIVEN** an authoritative general account catalog omits `gpt-5.3-codex-spark` for a plan-compatible active account
- **AND** that account has fresh, non-exhausted `codex_spark` quota telemetry
- **WHEN** account selection is requested for `gpt-5.3-codex-spark`
- **THEN** the general account-catalog omission does not remove that account from consideration
- **AND** the account proceeds through the remaining additional-quota and routing gates

#### Scenario: Catalog-supported account-level service-tier exclusion remains authoritative

- **GIVEN** an authoritative general per-account catalog includes a mapped separately metered model for two plan-compatible accounts
- **AND** the authoritative requested service-tier account index includes only one of those accounts
- **AND** both accounts have fresh, non-exhausted additional-quota telemetry for the model
- **WHEN** account selection requests that model and service tier
- **THEN** the account absent from the requested service-tier account index is not selected
- **AND** quota evidence does not reclassify that catalog-supported account as model-catalog-omitted

#### Scenario: Plan incompatibility remains authoritative

- **GIVEN** a requested separately metered model is mapped to an additional quota
- **AND** an account's plan is excluded by the model registry's plan or requested service-tier restrictions
- **WHEN** account selection evaluates that account
- **THEN** the account is not selected even if additional-quota telemetry exists

#### Scenario: Missing or stale quota evidence fails closed

- **GIVEN** the general account catalog omits a mapped separately metered model
- **AND** no plan-compatible account has fresh additional-quota telemetry for that model
- **WHEN** account selection is requested
- **THEN** selection fails with the existing additional-quota data-unavailable behavior
- **AND** the system does not route based only on bootstrap metadata

#### Scenario: Explicit unrelated quota cannot bypass model support

- **GIVEN** a caller supplies an additional-limit key that is not the requested model's canonical quota mapping
- **WHEN** the general per-account catalog excludes an account for that model
- **THEN** the supplied quota key does not override the account-catalog exclusion
