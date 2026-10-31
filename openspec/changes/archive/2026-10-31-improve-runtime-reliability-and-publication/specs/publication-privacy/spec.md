## ADDED Requirements

### Requirement: Publication privacy gate
The repository SHALL provide a local pre-push gate and CI check that scan every published tip tree and every newly published commit for secrets and private personal data before treating publication checks as passed. Findings SHALL report only file paths, locations and rule identifiers, never matched values. Reviewed exceptions SHALL be tied to exact content and a reason. Missing scanner tooling, unresolved revisions, unreadable files or scanner errors SHALL fail the gate.

#### Scenario: Secret removed before the tip
- **WHEN** a newly published commit contains a secret that a later commit removes
- **THEN** the publication gate SHALL still reject the history

#### Scenario: New personal data
- **WHEN** an unreviewed personal email, operator path or private infrastructure address enters the publication
- **THEN** the gate SHALL fail without printing the value

#### Scenario: Repository scanner settings attempt to suppress a secret
- **GIVEN** a publication tree contains scanner configuration, ignore files or inline allow comments that hide a credential
- **WHEN** the publication gate runs
- **THEN** it uses an isolated configuration extending the scanner's built-in rules and an empty ignore file
- **AND** it reports the credential unless its exact content has a separately reviewed publication-policy exception
