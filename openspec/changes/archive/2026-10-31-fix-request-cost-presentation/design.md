## Decisions

Keep floating-point USD values unrounded at the request-log API boundary. The existing display formatter owns rounding and minimum-positive indicators. Compare unrounded recomputed and saved totals with relative floating-point tolerance, without an absolute tolerance that would treat a small positive amount as zero. Saved cost remains authoritative when the catalog changes.

Derive presentation from existing `serviceTier`, `requestedServiceTier` and `actualServiceTier`; do not persist redundant provenance. Display `default`/`auto` as Standard pricing, `priority`/`fast` as Fast, and Flex/Ultrafast by name. A matching upstream tier is identified as upstream-reported; a matching requested tier without a matching upstream tier is explicitly unconfirmed. Missing or unsupported recorded tiers remain unknown. External model-source estimates must not be described as OpenAI API-equivalent pricing.

Use an approximation sign for the cost breakdown because individual display amounts are rounded separately. Preserve all private production pricing and routing adaptations by overlaying only the changed source files and rebuilt frontend onto the verified running image.
