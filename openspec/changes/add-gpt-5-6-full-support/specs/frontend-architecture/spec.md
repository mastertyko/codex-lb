## ADDED Requirements

### Requirement: Server-driven reasoning selectors distinguish max from Codex Ultra

Dashboard model metadata and automation create/edit surfaces MUST support the wire-level `max` reasoning effort when a model advertises it. They MUST NOT present Codex-native `ultra` as a server-forwarded reasoning value because Ultra's distinguishing multi-agent behavior is performed by the Codex client. The Codex-native model catalog MUST remain free to advertise `ultra` for compatible models.

#### Scenario: Dashboard model metadata exposes max

- **WHEN** a model registry entry advertises `max`
- **THEN** the dashboard `/api/models` representation includes `max` in its supported reasoning efforts

#### Scenario: Dashboard policy metadata filters Ultra

- **WHEN** a model registry entry advertises both `max` and `ultra`
- **THEN** server-driven dashboard selectors include `max`
- **AND** they omit `ultra`

#### Scenario: Automation can persist max effort

- **WHEN** an operator creates or updates an automation for a model that advertises `max`
- **THEN** backend and frontend schemas accept and preserve `reasoningEffort: "max"`
- **AND** the automation request forwards `reasoning.effort: "max"`
