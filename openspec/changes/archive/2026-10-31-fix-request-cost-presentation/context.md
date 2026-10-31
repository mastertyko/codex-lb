## Scope and rationale

The production audit independently checked 4,435 priced requests against the current OpenAI API rates and found no arithmetic errors for the recorded pricing tiers. It found 16 Luna prewarms whose positive USD 0.0000002 cost became zero in API serialization. A presentation fix is sufficient; rewriting prices or historical rows would change valid accounting data.

## Examples and edge cases

A two-token Luna prewarm must show `< $0.01` in the table and `< $0.000001` in details. Exact zero stays `$0.00`; missing cost stays unavailable. For requested Priority with recorded and reported default, the price tier is Standard and the basis is the upstream-reported tier. For recorded/requested Ultrafast with reported default, the price tier is Ultrafast and the basis is the requested tier, explicitly unconfirmed.

## Constraints and verification

The display represents an API-equivalent token estimate, not a Pro subscription balance or invoice. It does not prove the actual execution speed when tier observations disagree. Test API serialization, historical saved totals, rendered tier provenance, zero/null boundaries and separate component rounding. Verify the production overlay preserves source outside this change, then inspect real prewarm and Ultrafast rows after deploy.
