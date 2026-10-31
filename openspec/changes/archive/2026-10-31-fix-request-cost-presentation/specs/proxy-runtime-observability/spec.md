## MODIFIED Requirements

### Requirement: Small positive estimated request costs remain visible
The request-log API MUST preserve unrounded USD estimates and available cost components so that a positive amount cannot become zero during serialization. The request-log table MUST distinguish a positive estimated cost that would round to zero cents from exact zero. Request details MUST show estimated USD costs with up to six fractional digits and use a less-than indicator for smaller positive amounts. Independently rounded component breakdowns MUST be marked approximate. These display changes MUST NOT change recorded cost or pricing calculations; a saved total MUST remain authoritative when current pricing differs.

#### Scenario: Prewarm has a small positive estimated cost
- **WHEN** a request has estimated cost USD 0.00002
- **THEN** the table displays `< $0.01` and details display `$0.00002`
- **AND** exact zero still displays as zero and unknown cost remains unavailable

#### Scenario: Prewarm has a positive cost below one millionth of a dollar
- **WHEN** a request has estimated cost USD 0.0000002
- **THEN** the API preserves that positive value in its total and available components
- **AND** the table displays `< $0.01` and details display `< $0.000001`
- **AND** reading the request does not rewrite its saved cost

#### Scenario: Saved cost differs from the current catalog
- **WHEN** the saved total differs from the newly calculated total beyond relative floating-point tolerance
- **THEN** the API preserves the saved total and omits the conflicting component breakdown
- **AND** an exact saved zero MUST NOT be considered equal to a positive calculated amount

## ADDED Requirements

### Requirement: Request cost estimates identify their pricing tier and basis
For an available request estimate the dashboard MUST identify its recorded pricing tier and show the requested and upstream-reported tiers separately in request details. `default` and `auto` MUST display as Standard pricing, and `priority` and `fast` MUST display as Fast pricing. A recorded tier matching the upstream-reported tier MUST be described as upstream-reported. A recorded tier matching only the requested tier MUST be marked as a requested, unconfirmed estimate. Missing or unsupported recorded tier metadata MUST remain unknown; the dashboard MUST NOT infer a confirmed tier from a requested tier alone. External model-source estimates MUST NOT be labeled as OpenAI API-equivalent pricing. The dashboard MUST explain that API-equivalent estimates do not represent actual subscription consumption or an invoice.

#### Scenario: Upstream reports Standard despite requested Fast
- **WHEN** requested tier is `priority` and recorded and actual tiers are `default`
- **THEN** the price tier is Standard and the basis is upstream-reported
- **AND** details retain requested `priority` and upstream `default`

#### Scenario: Requested Ultrafast supplies the estimate
- **WHEN** recorded and requested tiers are `ultrafast` and the upstream tier is `default`, `auto`, or unavailable
- **THEN** the dashboard labels the pricing tier Ultrafast and the basis requested and unconfirmed
- **AND** it does not claim that upstream confirmed Ultrafast execution

#### Scenario: Historical cost has no recorded pricing tier
- **WHEN** a request has a saved cost but lacks a recorded pricing tier
- **THEN** the price tier is shown as not recorded and its basis remains unknown
- **AND** the saved cost is still displayed
