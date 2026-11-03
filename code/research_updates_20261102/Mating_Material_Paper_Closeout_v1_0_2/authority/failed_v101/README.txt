MATING MATERIAL — PAPER CLOSEOUT v1.0.1 — MEMORY REPAIR

Save/extract this folder in ~/Desktop/Lichess_Desktop and run:
  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Paper_Closeout_v1_0_1/RUN_PAPER_CLOSEOUT.command"

Expected runtime: provisionally 60–120 minutes, plus about 1–2 minutes of
startup tests. This is a planning range, not a production benchmark.
The launcher prints start and estimated finish in Toronto time, accounting
for daylight-saving changes. It prevents sleep while running. Drive I/O
can extend the range. Every substantial stage prints a heartbeat.

REPAIR OF THE REVIEWED STOP
The previous preflight passed. Its ordinary-comparison build attempted a
large three-way join followed by a global sort and exceeded DuckDB's limit.
This execution repair keeps the same configuration 2854da0567adc386, sample,
weights and estimators. It streams the sorted score attachment, partitions
game-ID joins and whole matching cells into 128 groups, and streams final
material selection. All original identity/result checks are retained.

The ordinary comparison now uses one SQL thread and a 1.5 GB SQL limit,
with a 64 MiB Arrow queue plus one batch (excluding library overhead).
Completed partitions are verified and reused after interruption. The
completed parent analyses and their private inputs remain untouched.
The original v1.0.0 folder and its incomplete scratch files can remain.

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
material checkpoints are reused. An interrupted ordinary specification is
restarted, while previously completed specifications are retained. Do not
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
Fourteen tests pass, including comparison with the v1.0.0 estimator,
interrupted-partition resume, and the full closeout export. The validation
record also contains the separate large synthetic memory test.
