# Pool-main C13 and Campaign family-D reconciliation, v1.0.0

## Purpose and authority

Rebuild C13's ambient-kindness association on the certified 24-month pool /
observed-nonadjacent sample, then return it with a reconciliation of the fixed
five-member Campaign family D. C13 is exploratory (`X`) and is not a family-D
member. This package does not reopen the C1 lineage dispute or estimate C1,
C2 or C5. It does not update the paper automatically.

The panel has 41,534,331 opportunities, 570,091 kind draws, 15,207,423 fair
opportunities and 419,463 fair kind draws. Its fingerprint is
`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
The predicate is `source = 'pool' AND previous_classification_status =
'not_mutually_adjacent_observed'`. This certifies the observed adjacency
screen; it is not a certification of literal end-to-start immediate rematches.

The original C13 producer is `campaign1_c13_v104.py`, SHA-256
`2b8e19fe130c5387ea9097eb011332918ef4761ea67afd7df30f91e2f69c535d`.
Its shared estimator is `campaign1_nonprofile_common_v102.py`, SHA-256
`f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c`.
Both originals are supplied unchanged. Execution copies change only certified
sample counts and the old-sample support assertion/labels. The old count of
17,101,141 supported rows cannot be imposed on a different panel. The SQL,
models, controls, clustering, numerical tolerances and retry policy are retained.
The exact source edits are serialized in `SOURCE_BINDING.json`.

## C13 construction and order of operations

1. Authenticate the report, package and all 24 monthly panel files.
2. Rebuild a denominator-only fair-opportunity base. Use UTC decision day from
   `api_last_move_at_ms`, speed pool and chooser rating band (<1600,
   1600–1999, 2000–2399, 2400+).
3. Build daily opportunity totals and leave-one-chooser-out rolling counts.
   The primary uses the preceding 28 complete UTC days, t−28 through t−1,
   in the focal speed × chooser-rating-band cell. Subtract the focal chooser's
   opportunities using normalized username; numeric chooser ID is used for
   fixed effects and clustering. No focal-day events enter the lag window.
4. Apply the fixed threshold of 5,000 other-chooser fair opportunities. Check
   row conservation, unique game IDs and nonnegative denominators. Freeze and
   hash this new support before opening the new ambient-kindness numerator.
   The new count and distribution are measured, not guessed from the old panel.
5. Join fair-kindness outcomes and require the certified 419,463 total. Build
   lagged numerators using the same leave-one-chooser-out identities and windows.
   Authenticate 0 ≤ numerator ≤ denominator for every constructed definition.
6. Estimate the original 19-model family. The primary and adjusted-quartile
   models run first, followed by the remaining frozen attempts. A successful
   attempt or a retained numerical/support failure is checkpointed immediately.
   Reordering independent attempts does not change the samples or estimators.

The primary model relates current kind draw to a one-percentage-point increase
in lagged ambient kindness. It includes chooser, speed × chooser-rating-band,
calendar-week, evaluation-bin, hour-of-week and tournament fixed effects, with
the original eight numeric controls and their original missingness treatment:
draw payoff, win premium, both clocks, both ratings and both rating deviations.
Inference uses the original one-way chooser-cluster correction and two-sided
normal-reference p values. No new sampling or smaller estimation panel is used.

The 19 attempts are seven linear exposure definitions (cell 14/28/56 days,
cell 28 days with seven complete days of washout, and speed-only 14/28/56 days),
a quadratic companion, four chooser-rating-band splits, six speed splits,
and adjusted ambient quartiles. The washout window is t−35 through t−8.
The original strict absorption policy (tolerance 1e−9; 2,000 iterations) and
extended retry for absorption nonconvergence only (1e−7; 25,000 iterations)
are preserved. Every subgroup attempt and failure remains visible.

C13 measures an association. Lagging and removing the chooser's own events
prevent mechanical self-inclusion but do not identify a causal peer effect.
It remains outside the confirmatory family, including if a coefficient is
significant. The sample reset is not an independent replication of the nested
old sample. The old C13 estimate is not used as a target for new coefficients.

## Family D: what is and is not closed

Membership remains C1, C2, C5, C6 and C9. Neither C13, C7X, Patron nor the C9
ply sensitivities replaces a missing member or increases this family.

| Member | Current input used here | Disposition |
|---|---|---|
| C1 | No authenticated new-sample primary in the bound reports | Missing; old and quarantined lineages excluded |
| C2 | No authenticated new-sample session ahead-minus-behind primary | Missing; old coefficient excluded |
| C5 | No authenticated new-sample snapshot-experience U statistic | Missing; activity gradients and Patron models are different estimands |
| C6 | Wave 2B2B1 primary and pooled support gate | Authenticated, retained in family |
| C9 | Completed fresh C9 primary and exact B2 reproduction receipt | Authenticated; implementation precondition cleared |

The report authenticates the two source archives and every transferred member.
It selects the unrestricted C6 primary, not a favorable ply sensitivity, and
the C9 later-session seven-day primary, not a component or new ply diagnostic.
The C6 pooled 4,000/4,000 support gate is checked explicitly.

The reconciler computes Holm step-down over all five slots. For missing raw
p values it reports **bounds**, not fabricated estimates: setting missing
slots to one supplies conservative upper bounds on adjusted p values for
the observed members; setting them to zero supplies lower bounds. C1/C2/C5
raw-p cells remain missing. Their use of one in the conservative calculation
does not mean those hypotheses were estimated and returned p=1.

Current authenticated raw p values are C6 = 0.0000016653539481830944 and
C9 = 0.0004. Their conservative five-slot Holm upper bounds are respectively
0.000008326769740915472 and 0.0016, so both reject at 5% under every possible
completion of the three missing p values. Exact final family-adjusted values
remain open until the missing current-sample authorities are supplied, or an
explicitly documented nonrejection disposition is adopted for those slots.
The package never labels this partial family as fully estimated or exactly closed.

## Runtime, resources, restart and outputs

Plan for **4–8 hours** of C13 compute on the prior Mac, excluding queue time.
The old full C13 stage took 16,763.856 seconds (about 4.7 hours) on 17.3 million
fair rows and reused denominator inputs. This new run has 15.2 million fair
rows and rebuilds the denominator caches. The estimate is not a private-data
benchmark; disk throughput, memory pressure and extended retries may lengthen it.
Aggregate-only family reconciliation should take **under one minute**.

Up to ten threads are used for panel hashing and DuckDB cache construction.
Models run one at a time. DuckDB defaults to an 8 GB memory limit and spills
to the external drive. The original NumPy estimator has no hard memory cap;
the DuckDB setting must not be read as a cap on total process memory.

Private state is under
`derived/replication/pool_main_reanalysis_v100_PRIVATE/c13_family_d_v100`.
Reports are under `output/pool_main_reanalysis_v100/c13_family_d_v100`.
Completed data caches and individual model attempts are authenticated and
reused. Incomplete file/receipt pairs are preserved separately before retry.
Corrupted complete pairs or changed configurations stop the run. No prior
wave output is overwritten. The existing shared C9/Patron compute lock is
respected, including an active C9 ply sensitivity run.

The Desktop output ZIP contains aggregate C13 results, all model attempts,
support and source receipts, and the family-D reconciliation. It contains no
Parquet, NumPy cache, PGN or account-level table. No API, profile, Patron,
all-game chronology or Git operation is performed. A partial report includes
completed aggregate model attempts and clearly identifies the unfinished run.

Repeat the same Terminal command to resume. A completed run is verified and
re-collected without re-estimation. `--holm-only` performs only the aggregate
reconciliation and does not read private panel rows.
