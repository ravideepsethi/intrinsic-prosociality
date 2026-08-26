# Dynamics Paper 2 Campaign 1 v1.0.7 non-profile recovery record

**Written after the v1.0.0 fail-closed run and before C7 focal outcomes, C12
experience outcomes, or C13 ambient-kindness outcomes were read:** 2026-08-25.

## Observed technical failure

The v1.0.0 run conserved C12's focal sample perfectly:

- rows: 345,138;
- distinct game IDs: 345,138;
- invalid speed codes: 0;
- invalid recipient rating bands: 0;
- minimum storage bucket: 0;
- maximum storage bucket: 14.

It nevertheless failed because the assertion required minimum bucket 0 and
maximum bucket 15.

## Root cause and correction

C12 uses `hash(recipient_id, 2026082202) % 50 = 0` for the frozen 2% sample and
the same hash modulo 16 to align focal opportunities with recipient-history
Parquet partitions. Since `gcd(50,16)=2`, a hash divisible by 50 has an even
residue modulo 16. The only reachable partitions are therefore
`0,2,4,6,8,10,12,14`. Bucket 15 is impossible by construction.

The recovery changes neither the seed, sample rule, focal rows, identities,
outcomes, controls, estimands, nor history join. It changes only the assertion
and bucket loop to the mathematically reachable set. A regression test now
freezes that relationship.

## C6/C10 preservation

The v1.0.0 run completed C6/C10 before C12 failed. Its returned result ZIP was
authenticated against the user's SHA-256 sidecar. The recovery package embeds
and authenticates those aggregate-only outputs and imports them into the final
result tree. It does not repeat the completed chronology scan or alter the
estimates.

The original C6 table accidentally labels the `c6_rated_games_90d`
denominator diagnostic in `events_per_1000_rated_games`. Its coefficient and
standard error are actually measured in rated games during the next 90 days.
The authenticated original files remain unchanged; the recovery adds an
explicit metadata-correction record. No numerical estimate changes.

## C7 exhaustive low-support analysis

The original outcome-blind C7 gate found 33 benefactor-facing opportunities,
below its frozen threshold of 1,000, without reading the focal kindness outcome.
The failed gate remains reported and the planned secondary interpretation is
not restored. Consistent with the user's prior instruction not to reserve or
prohibit analyses, the recovery reads the focal outcome and exports:

1. the planned latest reversed-arm HDFE attempt;
2. the same-speed HDFE attempt;
3. the exclusive-history HDFE attempt;
4. all category counts and kindness rates; and
5. an unadjusted difference, naive standard error, and Fisher exact diagnostic.

Every such estimate is labeled exploratory and low-support when the gate fails.
Failed or nonidentified model attempts are retained as results rather than
causing selective omission. C7 never enters Holm family D.

## Disclosure

This record is necessarily post-failure but remains pre-outcome for C7, C12,
and C13. The technical C12 correction is deterministic from hash arithmetic.
The C7 decision implements the user's already stated exhaustive-analysis rule.
All outputs, including nulls, adverse signs, and failed fits, must be retained.
