# C9 ply sensitivity, v1.0.0

This is a new sensitivity analysis for the completed pool/observed-nonadjacent
main-sample C9 result. It was specified after that result was observed. It
does not replace the original confirmatory C9 estimate, change the Campaign
Holm family, or claim preregistration. The code and this scope are frozen in
the package before any sensitivity estimates are run on the private data.

## Sources and population

- Main panel: 41,534,331 opportunities, fingerprint
  `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
- Fixed C9/B1 population: 55,359 repeat granters, 832,948 fair opportunities,
  and 234,993 grants. Use the same B1 rows, cross-fitted static propensities
  and ordering as completed C9 configuration
  `55d5cbb276393949039b72b65ffb2dd9cb57ed5dbff15b4ed012ecda4d6f88bd`.
- Read ply directly from authenticated B1 `current_ply_count`; the completed
  C9 non-outcome bridge already checked this field against Stage 07.
- Reuse the completed all-rated-game session cache, authenticated by its
  published SHA-256
  `c287dc17fb6cdf2f127038293cc0ecae8e884f8208e5aac48dfd96649d3fffc9`.
  Sessions use gaps of less than 30 minutes between consecutive game starts,
  with all rated games contributing to the session construction. These are
  not observed end-to-start idle times. No new sessionization occurs.

Authentication rehashes the 24 panel Parquets, the small B1/propensity inputs,
the executed B2 source, the session cache and the completed reference batches.
No main-panel rows, PGNs, raw chronology rows, profile data or API responses
are read by this sensitivity estimator. It reads only the authenticated
derived B1 rows and session cache needed for the calculations.

## Statistics and anchors

The statistic is the pooled kind-draw rate at eligible later opportunities
within seven days of the first grant. Each observed or simulated sequence
has its own first grant, time window and same-session/later-session partition.
The anchor itself is excluded. Later rows at the same timestamp and rows
exactly seven days after the anchor follow the original C9 inclusion rule.

Five masks are applied, retaining the complete original B1 opportunity
universe for assigning grants:

| Rule | Anchor eligibility | Later-opportunity eligibility |
|---|---|---|
| all | Any original first grant | All |
| outcome_gt4 | Any original first grant | Strict ply >4 |
| outcome_gt10 | Any original first grant | Strict ply >10 |
| outcome_gt20 | Any original first grant | Strict ply >20 |
| anchor_and_outcome_gt10 | Original first grant has ply >10 | Strict ply >10 |

The both-long rule excludes a chooser for that draw if its first grant is
short or has missing ply. It does not redefine the anchor as the first later
grant in a long game. The eligible-anchor and contributing-chooser counts
are recomputed per draw and reported alongside numerator/denominator counts.
Missing ply is excluded by strict threshold masks. Negative, infinite or
nonintegral ply values cause a failure rather than silent recoding.

This mask design asks whether the original C9 timing pattern is present in
long-game choices. It does not select a new cohort of users who have at least
two long-game grants or rebuild B1/B2 histories under a long-game sample.

## Two conditional-randomization benchmarks

1. **Original law, reproduced:** exactly the inherited B2 conditional Bernoulli
   law, fixing each chooser's total number of grants and its static propensity
   vector. It is not a uniform shuffle unless all relevant weights are equal.
   The original seed 2026082201, 250-draw batch boundaries and RNG calls are
   preserved. The package regenerates the original assignments and evaluates
   the new masks; the saved C9 aggregate arrays cannot themselves supply the
   ply-restricted statistics.
2. **Ply-band-conditioned law:** independently within each chooser-by-ply-band
   stratum, fix the observed grant count and sample using the original B2
   conditional Bernoulli algorithm and the corresponding static odds. Bands
   are <=4, 5–10, 11–20, 21–40, 41–80, >80, and missing. Counts zero or equal
   to stratum size are deterministic. Total grants per chooser are therefore
   also fixed. The independent stream uses seed components
   `[2026082201, 20260911, 1, batch_start, batch_stop]`.

There are 4,999 sequences under each law. The first grant and both session
partitions are recomputed from each complete simulated sequence under each
law; no observed first-grant position or observed partition is reused.

The principal composition sensitivity is the **later-session all-row result
under the ply-band-conditioned law**. It asks whether the excess remains
relative to a benchmark that already permits each chooser's different grant
frequencies across the specified game-length bands. The long-game masks are
reported together, without selecting a threshold by significance.

Conditioning on realized chooser-band grant counts is a descriptive
randomization benchmark, not a causal adjustment or a new confirmatory
experiment. It can absorb part of a real time-varying process as well as
composition. The check conditions on coarse bands, not exact ply, every
within-band difference, session-specific generosity, or all unobserved
time-varying circumstances. A positive result does not uniquely identify
a psychological state or the causal effect of first granting.

## Mandatory reproduction and inference

Before publication, the regenerated unrestricted arrays must match all
20 completed original C9 checkpoint batches and the corresponding B2
numerator/denominator arrays at 6 hours, 24 hours and 7 days, draw by draw.
The observed C9 numerators/denominators, null means and raw p values must
also reproduce the uploaded reference. This includes the original later
session result: 9,902/22,455, excess 11.547473 pp, raw p=.0004. Failure stops
publication. The original sources are copied without scientific edits;
the new masked statistic and conditioned benchmark are separate code.

For each law/mask, report same-session and later-session observed counts,
rates, null mean rates, excesses and doubled-tail plus-one p values. Report
the same-minus-later excess contrast using the joint simulated differences.
The null mean is the mean of pooled rates across draws, not the ratio of
mean numerators to mean denominators. With 4,999 draws the smallest possible
doubled-tail plus-one p value is .0004. All sensitivity p values are raw,
outside the original Holm family. Null distribution quantiles are not effect
confidence intervals; no standard error is manufactured from a p value.

A comparison requires a positive observed denominator and finite null rates
in all 4,999 draws. Otherwise it is marked NOT_ESTIMABLE with support counts;
unsupported draws are never silently discarded to obtain a p value. Overall
completion then carries an explicit support warning. The authenticated
baseline reproduction remains mandatory regardless of sensitivity support.

## Resources, restart and remaining work

No network access occurs. Up to ten spawned workers process twenty batches;
the runtime uses the estimated dynamic-programming table sizes to cap workers
within a 12 GiB planning budget by default. This is an estimate, not an OS
memory limit. Each fully completed batch is saved and hash-authenticated.
One-sided interrupted checkpoints are preserved separately before recomputing
that batch. Corrupt completed pairs and changed configurations fail closed.

The new state is isolated under `c9_ply_v100`. The existing C9/Patron lock is
respected. Successful original C9 results and private caches are read-only.
Only aggregate results, configuration, support and receipts are exported.

Expected compute is **5–20 minutes** on the prior Mac setup, excluding a wait
for another job. This planning estimate uses the original C9 runtime of
about 193 seconds and allows for the additional conditioned sampler and
masked counts, while avoiding chronology reconstruction. Full private-data
runtime cannot be benchmarked in the package-build environment.

C13 (if its claim is retained), global Holm reconciliation and integrated
manuscript updates remain separate. The 15/60-minute session alternatives
and C9 singleton-dyad appendix result are not included. Preserve the caveats:
first observed grant in the locked panel, not necessarily the first lifetime
grant; fixed repeat-granter scope; timing evidence, not a causal claim.
