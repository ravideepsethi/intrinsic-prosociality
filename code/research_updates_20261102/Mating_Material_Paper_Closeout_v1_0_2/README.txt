MATING MATERIAL — PAPER CLOSEOUT v1.0.2 — ACCURATE-SUM REPAIR

Save/extract this folder in ~/Desktop/Lichess_Desktop and run:
  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Paper_Closeout_v1_0_2/RUN_PAPER_CLOSEOUT.command"

Expected remaining runtime: provisionally 90–150 minutes, plus about 1–2
minutes of startup tests. This allows for the two other matching fits,
three shared-account covariance calculations, material sensitivity and
balance models. Drive I/O can extend the range. The launcher prints start
and estimated finish in Toronto time, accounting for daylight-saving
changes, prevents sleep, and prints progress during long operations.

REPAIR OF THE REVIEWED STOP
Version 1.0.1 completed the 11,432,259-row ordinary comparison frame and
all 128 overlap-matching partitions, then stopped in the final weight-sum
check. The failed return did not contain those two totals. The old check
was independently reproduced with exactly balanced synthetic weights at
the same arm sizes: ordinary SQL SUM accumulated a relative discrepancy
of 1.14e-10, above its 1e-11 tolerance. Compensated sums agreed exactly.

This repair uses compensated sums for weighted moments and covariance.
It retains the original tolerance and independently checks row counts,
weight totals, squared weights and weighted outcomes against the stored
cell formulas. It does not rescale weights or change sample/estimator
rules. A genuine discrepancy still stops, with an aggregate diagnostic
saved to the return ZIP before the exception.

The original scientific configuration 2854da0567adc386 and private folder
are preserved. The source frame and completed overlap-matching partitions
are authenticated and reused. Do not delete the private work directory.
No frame or overlap matching rebuild is required. The other two matching
specifications and remaining analyses still run. The completed parent IV,
material/score inputs and original manuscript files are read only.

The memory repair is retained: whole matching cells and game-ID joins
are partitioned into 128 groups, with streaming score attachment and
material selection. The ordinary SQL limit remains 1.5 GB, one thread,
and the Arrow queue remains 64 MiB plus one batch excluding overhead.

WHAT RUNS
1. Verify the completed material IV run 12093d55b7ee9f73, its reports,
   private Parquets, the original material manifest, and required columns.
2. Ordinary draw versus ordinary loss, using three versions of the original
   empirical-cell overlap estimator on the corrected comparison frame.
3. One strict absolute final-material <4 sensitivity on corrected spaced
   receipt exposures, using the original validated-FEN and ply rule.
4. Recent-history balance for spaced, spaced without environment controls,
   and repeated-recipient fixed-effect models.
5. Export one aggregate return ZIP and manuscript-ready LaTeX tables.

The comparison frame in step 2 is deliberately updated: it now uses the
completed 90-day, all-time-score-supported frame, with no receipt cooldown.
Its histories and activity cover the 90 days immediately before the game.
This is NOT the old 1,290,237-game comparison with older histories and
spacing. The estimator is unchanged: empirical-cell overlap weights,
common support in both arms, and the original shared-three-account HC1
covariance. Ordinary draws include stalemate and recorded regular draws;
ordinary losses include checkmate and resignation. It remains observational.
Both the zero-coded grant outcome and reaching a choice are reported.

COMPLETED WORK IS REUSED
No Stockfish evaluations, API data retrieval, rating replay, donor-score
rebuild, or previously completed model is requested. Original result
folders are read only. Work is isolated in:
 /Volumes/XT_Pro/lichess_kindness/derived/replication/
 mating_material_paper_closeout_v100_PRIVATE/<configuration>/

Resources: 11 GiB target budget on the 18 GB Mac; at most two material
month workers (3 GB each), at most four fixed-effect projection threads,
one other heavy model at a time. Shared-account covariance is partitioned
into 128 narrow buckets. At least 20 GiB of free disk space is checked.
The pinned environment from the completed IV batch is reused.

If interrupted, run the same command. Checksum-verified model and monthly
material checkpoints are reused. A failed final fit resumes from its completed matching partitions;
previously completed specifications are retained. Do not
delete private work to resume. Changing input bytes/signatures stops reuse.

RETURN ONE FILE
The launcher prints:
 MATERIAL_PAPER_CLOSEOUT_<configuration>_RETURN.zip
in your Lichess_Desktop folder. Return that ZIP, including if a stage stops.
It contains aggregate results, status, diagnostics and logs; individual
Parquet rows, FENs and account identities are not exported.

PAPER STATUS
This package does not falsely mark the manuscript complete. It contains
the October 31 source draft as an archive, authenticated completed reports,
a result-to-manuscript map, and an integration note. After the returned
results are checked, retained tables, prose, abstract, figures and appendix
must be reconciled, then the final PDF compiled and visually checked.

Retained main claims: position and stage gradients, stable state-specific
granting, Patron association, receipt IV, assignment/entry diagnostics,
ordinary-ending instrument placebo, and ordinary draw/loss mechanism check.
The minimal closeout omits the two-instrument Hansen extension, spaced
complier demographics, clearly-worse receipt IV, receipt-position/stakes
heterogeneity, the redundant extra balance ladder/implied-bias projection,
and the adjacent-payoff check. Their estimates must not remain in the
revised paper. Existing computed one-instrument variants remain available.

Scientific limits to preserve: active-resolution selection; significant
joint history imbalance; undetected disconnection-specific chat; generated
scores treated as fixed; public Patron snapshot observed after play;
conditional-independence/monotonicity assumptions in one-factor comparisons.
Do not select prose or retained models to obtain a desired p-value.

INCLUDED MANUSCRIPT ASSETS
The paper/ directory includes regenerated position-stage and IV-score
figures, eight updated main-table fragments and a four-page preview PDF,
734 completed result files with checksums, and reconciliation notes.
These assets reuse verified outputs; they are not a completed manuscript.
The startup suite includes comparisons with the v1.0.0 estimator, dense
WLS and covariance oracles, and interruption at the exact v1.0.1 stop.
It checks that all completed matching partitions are reused, reproduces
the false stop at 11.43 million synthetic rows, and rejects genuinely
altered weights, omitted rows and altered outcomes. See VALIDATION.json
and TEST_RESULTS.txt for executed checks and the separate scale test.

Numeric reference: DuckDB's fsum uses compensated (Kahan) summation.
https://www.duckdb.org/docs/current/sql/functions/aggregates
The implementation is tested against the pinned DuckDB 1.3.2, not an
upgraded database version.
