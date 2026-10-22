COUNTDOWN FEASIBILITY 1.0.0

PURPOSE
Run a local feasibility pass for the material-countdown threshold on the
author-excluded 24-month pool/nonadjacent main panel. This package produces
descriptive counts, grant rates, material profiles, and support/overlap tables.
It does not fit the proposed discontinuity models or produce causal estimates.

There are zero API requests, zero Stockfish evaluations, and zero IV refits.
The package never modifies the input panels. It authenticates their recorded
SHA256 hashes before reading them and checks that they remain unchanged.

RUN ON THE MAC
Place Countdown_Feasibility_v1_0_0.zip and its .zip.sha256 file in
~/Desktop/Lichess_Desktop, then paste the command supplied with the download.
The launcher uses an existing Python 3.10+ environment with duckdb and pyarrow,
including the environments from the recent author-exclusion runs. It does not
install or download anything. COUNTDOWN_PYTHON may point to another interpreter.
It verifies its package hashes and runs its small synthetic tests before starting.

Direct invocation after extracting:
  /bin/bash RUN_COUNTDOWN_FEASIBILITY.command \
    --project "/Volumes/XT_Pro/lichess_kindness" \
    --workers 4 --memory-gb 11 \
    --result-dir "$HOME/Desktop/Lichess_Desktop"

INPUT DISCOVERY
The runner searches known author-exclusion producer directories for completed
excluded_AUTH.json receipts. It checks their policy, pinned original main-report
lineage, monthly hashes, receipt agreement, and 24-month coverage. Equivalent
continuation receipts are accepted. Different datasets require an explicit
--input-manifest "/absolute/path/to/excluded_AUTH.json" choice.
If no newer receipt exists, it accepts the original
AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json contract. It does not infer sample
membership from an arbitrary Parquet file or use the included-author panel.

Full-width input fields were checked against the original author-exclusion and
Remaining v1.4.0 producers. The preferred sources are fen_after_last_move and the
ten chooser/disconnected piece-count columns already in those panels.
Every nonmissing FEN is checked for rank widths, legal piece symbols, one king
per side, and side-to-move orientation. Where both sources are valid, all ten
counts must agree. Cached counts are used when FEN is absent. Missing both is
reported explicitly; no new data are fetched. Full chess-position legality is
not re-evaluated. Existing role, author, timeout and 100k-node evaluation
semantics are checked for every row.

DEFINITIONS
Material deficit = chooser material minus disconnected-player material.
Piece values: pawn 1; knight 3; bishop 3; rook 5; queen 9; king 0.
Thus deficit >=4 denotes the disconnected player being at least four points
behind. Promotions are counted as the pieces actually on the board.

Finite lost: non-mate raw evaluation strictly below -100 cp, from the
disconnected player's perspective. Finite competitive: at least -100 cp.
Mate cases stay separate and never enter finite evaluation bins.

Calendar periods use final-move UTC timestamps:
  pre: before 2025-07-19
  buffer: 2025-07-19 through 2025-08-10
  post: 2025-08-11 onward
These are proposed calendar proxies, not a claim that deployment was observed.

Clock restrictions use the disconnected player's last-observed clock. Identical
cutoffs apply in both periods: ultraBullet/bullet 40 seconds, blitz 60, rapid 120,
classical 300. Tables include unrestricted, strictly above this cutoff, and
strictly above twice this cutoff. They are proxy sensitivities: the recorded
clock is not a disconnection clock and cannot establish common exposure time.
Both players' clock bins are used in overlap cells.

Stages are ply <=10, 11-20, 21-40, 41-80, and 81+. Eval10 is 10*floor(cp/10).
Clock bins are [0,10), [10,20), [20,40), [40,60), [60,120), [120,300), [300,+inf).
These choices describe feasibility and do not freeze a later regression model.

OUTPUTS
The Desktop receives aggregate-only ZIPs plus SHA256 at 6, 12, and 18 completed
months (025/050/075), and a final 100 ZIP after all aggregate tables finish.
The percentages describe pipeline checkpoints, not elapsed-time percentages.
Check STATUS.json: 100 can report PARTIAL_MATERIAL_COVERAGE, not only COMPLETE.

Reports include:
  monthly_coverage.csv           Counts and source/clock/evaluation coverage.
  overall_coverage.csv           Whole-sample coverage and unique choosers.
  profile_by_month.csv           All deficits by month, speed and evaluation region.
  profile_by_period_clock.csv    Deficits 0-8 by period and clock restriction.
  competitive_threshold.csv      Competitive positions with deficit >=4.
  eval_clock_distributions.csv   Deficits 2-5 by evaluation, stage and both clocks.
  clock_lower_tail_by_week.csv   Last-clock minima and approximate lower quantiles.
  composition_top30.csv          Most frequent piece-count combinations at 2-5.
  chooser_overlap.csv            Choosers observed at both deficits 3 and 4.
  overlap_summary.csv            Shared evaluation/stage/clock cells at 2-5.

Counts, sums, and unique chooser counts are exact. Quantiles labeled approx are
approximate. Grant rates are unadjusted percentages. Unique chooser counts must
not be added across months/cells. No standard errors or causal bias bounds are
computed. The top-30 composition table reports the retained share of each group.
Support cells contain finite-lost observations with both clocks observed and a
supported API speed. Material/evaluation/clock missingness remains visible in
the coverage tables. Other-speed rows remain in overall/monthly reports but are
excluded from restricted-sample and overlap tables.

Private monthly features and support-cell Parquets are saved under:
  derived/replication/countdown_feasibility_v100_PRIVATE/<run key>/PRIVATE/
Game/account IDs and positions are never included in the exported report ZIPs.
The feature cache is intended to be reusable by the later model package.

RESUME AND FAILURES
Rerun the same command with the same package and project to resume. Every source
file is rehashed; completed private months are verified and reused without
rewriting. Completed final tables and support cells are also verified and reused.
An interrupted aggregate stage reruns the aggregate tables from the monthly cache.
Changed inputs or changed checkpoints stop the run rather than silently mix data.
One countdown process per project is allowed. There are no background processes
after the launcher exits. Use Ctrl-C if necessary, then rerun to resume.

Exit 0: COMPLETE. Exit 2: BLOCKED or PARTIAL_MATERIAL_COVERAGE. Read STATUS.json
in the latest checkpoint ZIP; the private ERROR.txt preserves a traceback for
blocked runs. Upload the final 100 ZIP and its SHA256, or the blocked report ZIP
if processing stops. A missing-input report includes a bounded local cache
inventory. It never triggers downloads or reconstructs unverified membership.

RESOURCES AND TIMING
Default: at most four worker processes within an 11 decimal-GB target budget.
Lower budgets automatically reduce concurrency. DuckDB limits are below this
budget to reserve space for Python, Arrow, decompression, and operating overhead;
the budget is a scheduling target, not an operating-system-enforced RSS cap.
At least 8 GiB free disk is required initially; temporary spill may need more.
Avoid another heavy analysis on the same drive at the same time.

The source is hashed sequentially within each monthly task, then selected columns
are scanned for checks and projection. Only narrow cached columns are read for
the final summaries. There are no repeated per-model panel builds or FE solves.
The actual first completed months determine the projection ETA. The aggregate
stage estimates remaining time from completed table queries. Both are rough;
different months/tables and external-drive contention can change the rate.
Synthetic tests do not establish a reliable runtime on the full external-drive
dataset. Do not treat the projection ETA as the total-run ETA.

VALIDATION
See VALIDATION.txt for environment and checks. The tests use synthetic data;
they do not claim that this session ran the full private Mac dataset.
