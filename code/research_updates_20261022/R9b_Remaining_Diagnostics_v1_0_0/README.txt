R9b remaining diagnostics — version 1.0.0

This is a runner for the research Mac, not a completed R9b results report.
The individual research data are on /Volumes/XT_Pro/lichess_kindness and are
not available in the chat workspace. Figure 5 is complete: it is rendered
from the certified run's aggregate H_figure5 data, without new estimation.

Run RUN_R9B.command with bash, using the project venv. Provisional runtime:
2–4 hours. Missing ENV history scans, SSD throughput, and the additional
fixed-effect fits determine the actual runtime. Progress messages update the
ETA every 30 seconds during scheduled work. Completed stages survive a
restart; run the identical command again. The launcher uses caffeinate.

The parent is fixed at 4028bf3e1857. R9b writes to a separate
derived/replication/r9b_remaining_diagnostics_v100_PRIVATE/<configuration>
directory. It does not write into R9, 2a4e617b40bc, or the earlier runs.
No API requests, Stockfish evaluations, or new comparison-frame sampling.

OUTPUTS

The Desktop/Lichess_Desktop folder receives R9B_REPORT_<id>_025.zip,
_050.zip, _075.zip, and _100.zip, each with a .zip.sha256 sidecar.
The launcher also writes R9B_run_<UTC timestamp>_<pid>.log there.
Return the _100 ZIP, its SHA256 sidecar, and the log. If the run stops,
return the most recent checkpoint ZIP and the log. Only R9B_COMPLETE
means the full requested run completed. Earlier checkpoints are partial.

Report tables are aggregate CSV, JSON, and Parquet. They contain no account
or game records, raw instruments, individual influence vectors, or row-level
data. Local input files, identity hashes, and caches remain on the Mac.

WHAT IS RUN

J.1: same-row OLS on all 2,682,329 S0 exposures, with ENV-indicator primary
and X0 beside it. The first stage, both reduced forms, and 2SLS coefficient
and SE must reproduce R9 in both control sets before later models proceed.

J.2: separate absolute UTC start-hour and last-move-hour fixed effects,
with FS, RF (later granting and reach), 2SLS and OLS. These are calendar-hour
effects, not merely the 24 hours of a typical day. Absolute start-hour FE
already absorb the original date and hour-of-week effects, so redundant
labels are removed computationally with no change to the column space.
Last-move-hour effects are added to the original FE.

J.3: the eight original expanded_logic.specifications() exposure definitions:
primary 90-day spacing; repeated recipients pooled; repeated recipients with
recipient FE; 30-day spacing; no spacing; first-exposure reference with
common controls; primary without recipient history and volume; first-exposure
reference without recipient history and volume. All use updated pooled
Score A and its three donor-set history controls. Frozen spacing and first
flags are retained; removing an author does not trigger replacement selection.
Original wider-frame histories/outcomes are reproduced before replacing them
with the same author-clean history/outcome rules as R9; S0 overlap must agree.

J.4: all 15 traits without recipient history/volume controls; repeated-row
recipient-FE balance, with already-controlled traits explicitly marked as
non-independent evidence. Joint all-available and recent-seven tests; Holm
uses the frozen 15-trait family, treating unavailable/controlled tests as p=1.
Balance coefficients are trait SD per native residual-score SD.

J.5: raw and adjusted subgroup first stages, with controls/FE refitted in
each subgroup. Speed uses base seconds + 40 times increment, with cuts at
180, 480, and 1500 seconds. Rating cuts are 1200, 1600, and 2000.
Prior-choice groups are no competitive choice, choices but no grant, and
at least one grant in the frozen 90-day history ending seven days before
exposure. Every month is requested; empty/unsupported months are reported
explicitly. Support requires at least 2,000 exposures and 20 receipts and
nonreceipts. Complier traits match Table D.6: rating; recent rated-game
volume; competitive choices, grant-ever, no-choice, disconnections and
receipts; four speed shares. Means are instrument-weighted margins, not
observed account groups. Negative weights are retained and their mass is
reported. Ratio inference uses the joint numerator/denominator moment and
the same shared-account-OR-date covariance.

J.6: competitive-only donors at minimum five and three, noncompetitive-only
donors at minimum five, and pooled-A companions on each identical supported
row set. The two-score model requires at least five of each type; a pooled-A
companion on that intersection is included. Competitive is cell//100 >= 2,
equivalent to recipient-perspective evaluation >= -100 cp, within the exact
eligible pooled donor universe. The complementary donor set is noncompetitive.
Both use the SAME donor-month state reference as pooled A. This is a change
in donor population, not a refitted alternative reference model. The three
primary history controls remain the pooled A controls in every model, as
specified; added competitive-history controls are not silently introduced.

The joint model reports conditional instrument slopes, their partial R2,
the joint first-stage Wald F and partial R2, RF coefficients, 2SLS, and a
Hansen J. The J statistic is evaluated at the efficient two-step GMM fit,
using shared-account-OR-date CR0 moments from the preliminary 2SLS residuals;
the displayed receipt estimate remains 2SLS. A singular or nonpositive
moment covariance is reported as unsupported, never repaired by clipping.
Method reference: official linearmodels IVGMMResults.j_stat documentation:
https://bashtage.github.io/linearmodels/iv/iv/linearmodels.iv.results.IVGMMResults.j_stat.html

J.7: reuse authenticated dose.parquet features from the completed receipt
mechanisms run 08b0e91f184f, the source of Receipt_Cohort_Tests run
59b081ee15d6. Identity, treatment and outcomes must agree with S0 exactly.
Four receipt-by-position terms and two stake interactions are instrumented
by Score A times the same modifiers. Position bands are [-100,0), [0,100),
[100,300), and [300,infinity). Near-equal pools the first two using their
exposure counts. Stakes are centered and divided by five rating points.
Additional controls and conditional-F definition match the original producer;
the instrument is excluded from the ordinary controls. ENV-indicator is
added in the primary column. Report both outcomes, all six conditional F
statistics, their minimum, band effects, well-ahead minus near-equal, the
two stake interactions, premium IQR translation, and their joint covariance.
These secondary models retain their additional identification assumptions.

J.8 is omitted. No earlier entry or ordinary-ending frames are rerun.
The earlier S3.7 material is left as earlier-score material, per the latest
instruction. This package does not delete it or edit the manuscript.

J.9 / FIGURE 5

figure5/Figure5_Score_A.pdf is the vector figure; PNG is the preview.
Figure5_bins.csv contains the exact 20 plotted aggregates. The caption and
code/draw_figure5.py document the rendering. No bins or intervals were refit.

UNITS AND INFERENCE

Instrument slopes use 100 * 0.04979005187533171, retaining the full certified
SD behind the rounded 0.04979. OLS/2SLS receipt effects are pp per receipt;
stake interactions are pp per five rating points; complier traits retain
their natural units; balance uses trait SD per native score SD. Every table
labels its units explicitly. All reported intervals are normal Wald 95%.
No AR intervals are computed in the new producer.

RESOURCE AND VALIDATION CONTRACT

Up to ten spawned workers, one BLAS/Arrow thread per worker, with explicit
RAM reservations against an 11 GiB planning budget. The budget is an estimate,
not an OS-enforced process limit. Decoded Parquet columns are projected; FWL
uses one owned matrix. The largest fits run alone when required. ENV scans
run at most two workers at 3 GB DuckDB each; unfinished OOM tasks retry alone
at 8 GB. All writes are staged and hash-bound for restart.

The original R9 alternating-projection solver is retained. For new nearly
nested FE such as last-move-hour, iteration-limit failures can finish the
same projection with sparse normalized LSMR. Every resulting residual must
pass the original FE orthogonality tolerance; coefficients are never accepted
merely because an iterative solver returned. Nonconvergence still stops.

VALIDATION.json and validation.log document synthetic numerical and operational
checks. They are software validation, not a production-data run. The actual
Mac run independently checks source receipts, score oracles, S0 bridges,
and exact R9 coefficient/SE reproduction. No coefficients for J.1–J.7
are presented as already computed by this package.
