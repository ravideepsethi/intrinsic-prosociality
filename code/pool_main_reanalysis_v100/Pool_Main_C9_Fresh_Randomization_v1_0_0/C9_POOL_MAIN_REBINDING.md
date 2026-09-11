# C9 new-main-sample rerun: frozen scope and source binding

Version 1.0.0, 2026-09-11. The author has authorized re-estimating the paper's
analyses on the new pool/nonadjacent main sample and has prioritized the
remaining analyses needed for writing. This rerun carries forward C9's
existing specification. It is not a newly preregistered hypothesis or an
independent replication of the earlier nested sample.

## Recovered producer

The original production archive was recovered from the author's saved files:

`Dynamics_Paper2_Campaign1_C9_IGNITION_TRANSFER_PRODUCTION_v1_0_0_r1_20260825.zip`

Archive SHA-256: `a2c2048d5329fc883ead00147ed2a00bb00b1380dfad7a5db50da44a0be0e5ba`.
Producer SHA-256: `e553af77d16cf944a956b4ae266c3468806e08257a4aa1bff6fb953c619d8830`.
Both match the August authority record. The package includes the unchanged
producer, not the serialization-only recovery runner.

The wrapper calls the original mapping, all-game session construction,
outcome-blind support, conditional sampling, partitioning, summary, and B2
reproduction functions. It rebinds sample-cardinality constants, points to the
executed and hashed new-sample B2 loader, writes to separate private/public
directories, and serializes component rows using a union schema. The union
schema repairs the known August CSV failure without changing estimates.
Original source and science-function AST hashes are recorded in the output.

## New sample and null

The 41,534,331-opportunity main panel uses
`source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`.
It certifies the observed adjacency screen, not literal immediate-rematch
classification for every game. The authenticated B1 subset contains 55,359
repeat granters, 832,948 fair opportunities, and 234,993 grants.

Every draw preserves each chooser's grant total and the fixed cross-fitted
static propensities. The law is the inherited fixed-total conditional
Bernoulli law; it is not uniform over grant placements when propensities
differ. Keep this distinction in the paper's methods description.

There are 4,999 draws in 20 batches (250 each, final batch 249), using seed
2026082201 with the inherited batch-specific seed components. C9 recomputes
the pseudo-first grant and all partitions in every draw. Old-sample C9 arrays
are never read. The already certified new-sample B2 arrays are read only for
validation after the new C9 arrays are computed; they are not substituted
for any C9 statistic. B2's seed is deliberately retained for exact inheritance.

## Estimands and sessions

- Primary, inherited family-D member: later-session kindness excess within
  seven days of the observed/pseudo-first grant, with a two-sided
  plus-one randomization p-value.
- Secondary: same-session minus later-session excess within seven days;
  same-speed-pool minus cross-speed-pool excess within 24 hours.
- Sessions use consecutive starts of **all rated games**, with a break at
  a gap of at least 30 minutes. This is the original start-to-start fallback;
  it is not an end-to-start measure. Ordinary games can bridge timeout gaps.
- Same/cross pool means canonical `api_speed`, not API `source`, which is
  already restricted to pool in the main sample.

The primary rate is kindness per eligible post-anchor opportunity, pooled
over the inherited repeat-granter cohort. It is not the probability of at
least one later grant per chooser. The grant that anchors the window is excluded.

## Publication gates

The runner checks the main-panel SHA-256 hashes, new B1/propensity hashes,
executed B2 code and report hashes, and every B2 checkpoint. The chronology
manifest is SHA-256 bound; selected chronology files are checked for sizes,
Parquet row counts, required columns and UTC footer ranges. It does not claim
to rehash every byte of the all-game chronology.

The non-outcome B1-to-game bridge must be complete and unique. Session
resolution must be 100%; unresolved sessions are never assigned synthetic
values or silently dropped. Support is recorded before outcome estimation.

Publication requires exact equality of all 4,999 draws' B2 numerator and
denominator arrays at 6h, 24h and 7d, plus reproduction of the certified
new-sample B2 summary within its original 1e-12 floating-point tolerance.
Both partition decompositions must conserve the corresponding B2 totals.
Every pooled partition must have support in the observed sequence and every
draw. A failed check stops publication and preserves the private checkpoints.

## Remaining scope and interpretation

This package closes the source-location gap and reruns the original 30-minute
C9 primary and its two secondary contrasts. It does **not** close the C9 ply
retrofit, 15/60-minute session sensitivities, C13 ambient exposure, or the
paper-wide Holm reconciliation. Those labels remain explicit in the report.
The original game-stage-composition caveat remains until its separate
robustness analysis is completed. Do not substitute the raw C9 p-value for a
final family-adjusted p-value, or resize the family because another result is
missing. The C1 reconciliation/quarantine is not touched by this package.

Inherited limits: first observed grant in the locked panel, not necessarily
first lifetime grant; repeat-granter scope; timing evidence, not a causal
claim. A positive result would not uniquely identify habits, identity, or
salience, or rule out persistent unobserved state composition.

## Execution and restart

No network, Lichess API, PGN, Patron profile, Git fetch, commit, or push is used.
All sessions are constructed from the existing canonical rated-game chronology.
New private caches and randomization states stay on XT_Pro. Returned reports
contain aggregates, provenance and receipt hashes, without account-level rows.

Expected first run: **45-120 minutes**, a planning estimate rather than a
benchmark of this full rerun. Most uncertainty is in mapping, filtering and
sorting roughly 217 million or fewer user-game records out of 150 selected
chronology files (2.324 billion source rows, approximately 45 GB). The older
64,331-user C9 cohort had 217,135,654 user-game rows; the new cohort is smaller.
The new B2 run took about 78 seconds, but that excludes C9's session construction
and extra partitions and is not an estimate of this job's total runtime.

Allow 80 GiB free workspace for DuckDB spill. Default: ten workers and a 12-GB
DuckDB limit. Numerical worker libraries use one thread each; the session
construction and randomization phases run sequentially.

The session cache and each 250-draw batch are checkpointed. On interruption,
rerun the same command. Completed authenticated checkpoints are reused;
an interrupted unfinished session build starts again. Incomplete one-sided
C9 batch checkpoints are preserved in the new run's interrupted-checkpoints
folder before that batch is retried. Invalid completed hashes stop the run.
The launcher prints a dated log, and the runner prints 30-second heartbeats.

The final aggregate report ZIP and SHA-256 sidecar are written to
`~/Desktop/Lichess_Desktop`. Upload both files beginning `POOL_MAIN_C9_FRESH_RESULTS_`.
