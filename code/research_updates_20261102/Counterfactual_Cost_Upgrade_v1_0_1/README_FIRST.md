# Counterfactual cost upgrade — v1.0.1

This package computes a new rating-cost candidate from the cached pre-update
states, compares it with the paper's existing cost, and validates both against
recorded rating changes. It preserves the existing data and analysis outputs.

Version 1.0.1 repairs the v1.0.0 stop `Claimed win without mating material`.
The cached material flag is the project's historical piece-count screen,
not the platform's side-specific rule. For example, a lone knight can win
against an opponent with a pawn under the platform rule, although it fails
the historical screen. The earlier `Pool_Rating_Validation` correctly included
all confirmed chooser wins. This release restores that same primary validation
sample and computes platform material from cached piece counts and final FEN.
The original draw label is preserved; a separate audit counts disagreements.

The corrected code uses a fresh run identity. It does not reuse v1.0.0 monthly
outputs. Rerunning this version resumes this version's completed months.

## Run

Save the ZIP and its `.sha256` file in `~/Desktop/Lichess_Desktop`. Use the
terminal command supplied with the package. The launcher defaults to:

- Project: `/Volumes/XT_Pro/lichess_kindness`.
- Transfer files and logs: `~/Desktop/Lichess_Desktop`.
- Ten independent month workers, two hash workers, one numerical thread per worker.
- 11 GiB memory budget; streaming batches of 32,768 rows.

Expected first-run time: **20–60 minutes** on a modern Mac with an external SSD.
This is a planning estimate; no production data are present in the development
environment. Allow another few minutes if dependencies need installing. Keep
at least **12 GiB** free on the project drive; 20 GiB is preferable. Only a
compact cost sidecar is written, rather than another copy of the complete panel.

The code reports progress and ETAs, saves each completed month, and writes
25/50/75/100% aggregate report ZIPs to `Lichess_Desktop`. Rerun the same command
to resume. A completed run verifies and reuses its outputs. `caffeinate` keeps
the Mac awake. Inputs and package files are checked before use.

## Inputs

The preferred input is the existing manifest:

`derived/replication/author_exclusion_v100_PRIVATE/AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json`

Its 24 monthly Parquets are authenticated, traced to the pinned original
41,534,331-row main sample, and checked again for both author accounts. The
expected retained total is 41,534,289 rows. If the manifest is absent, the code
uses the original certified main panel and applies the same two-account
exclusion itself. That fallback requires every original file to match the
bundled authoritative SHA-256 hash and the original completion receipt.

The required RD, volatility, rating, payoff, outcome, material, role, and source
fields are already in the published main-panel schema. The reconstruction is
recomputed from cached pre-update states and must reproduce the stored costs
within 0.0000001 rating points before any adjustment is made.

No API requests, new PGNs, Stockfish work, or historical replay are performed.
The actual rating histories remain intact, including author-involving history.

## What changes

- Positive rating gains receive the documented speed-specific multiplier.
- The platform's 400-point rating floor, 700-point change limit, sanity-reset
  branch, and historical ordering of these operations are reproduced.
- Each outcome starts from the same pre-update state.
- The chooser's draw/win changes and cost, and the opponent's draw/loss
  changes and benefit, are written separately.
- The platform material predicate uses both players' pieces and, where needed,
  bishop-square colors. Its result is recorded separately from the historical
  material screen and kind-draw label.
- When the platform predicate rules out a win and the recorded outcome is
  consistent, the action cost is zero. Any contradictory recorded win remains
  in observed-win validation but has a NULL action cost and a diagnostic flag.
- The original kind-draw outcome remains unchanged. A candidate draw label
  using the platform predicate and counts of added/removed draws are supplied
  separately for review.
- A separate November 2024 refactor sensitivity recomputes outcome-specific
  volatility for the brief source-code window in which the skip flag was absent.

The result is explicitly a **conditional candidate**, not a newly certified
exact reconstruction of every historical server update. Before April 17, 2025,
the gain factors were runtime settings absent from Git; the documented later
values are assumed for those earlier games. Bot status is also absent from the
main-panel schema. Unknown accounts use the human branch and are counted as
unknown. See `METHODS.md` for the exact source history and interpretation.

## Outputs

Heavy, private outputs stay on the project drive:

`derived/replication/counterfactual_cost_upgrade_v100_PRIVATE/<run>/`

- `months/YYYY-MM/costs_PRIVATE.parquet`: game-level cost sidecars.
- `COST_CANDIDATES_READY_PRIVATE.json`: input identity, output hashes, row
  identities and the `(month, game_id)` join contract.
- Monthly checkpoints and resume receipts.

Sidecars retain the hypothetical `chooser_win_minus_draw_candidate` for every
row, separately from the feasible `chooser_cost_candidate`. The latter can be
zero or NULL. Use `analysis_eligible_cost` for meaningful cost comparisons.

The final shareable files in `Lichess_Desktop` are:

- `COST_UPGRADE_<run>_100.zip`
- `COST_UPGRADE_<run>_100.zip.sha256`

Upload those two files for review. They contain aggregate CSV/Parquet tables,
a summary, methods and source provenance; no game IDs, account IDs or usernames.

The report includes paired validation by outcome, month, speed, board state,
rating uncertainty and rating-change sign; conditional integer-display bracket
coverage; exact cost medians and upper quantiles; forgone-point totals;
month/speed changes; and the November sensitivity. Observed-outcome validation
does not directly observe the other potential outcome. No counterfactual is
fitted to that game's realized update.

`material_audit.csv` and `.parquet` cross-tabulate historical and platform
material classifications, observed outcomes, month, speed and competitive
status. `SUMMARY.md` also displays the material disagreement and conflict
counts. The run completes its numerical audit even if unresolved material
conflicts remain; those conflicts must be reviewed before adopting the costs.

This package does not overwrite the primary cost variables or rerun manuscript
regressions automatically. Review the factor assumptions and validation first;
the private sidecars support a later authenticated join and refit.

## Optional inputs

The standard command needs no extra inputs. If independently authenticated
historical information is available, pass either or both:

`--bot-status /absolute/path/status.parquet`

Columns must be `username_norm` (string) and `is_bot` (Boolean). Conflicting
records stop the run. Missing accounts remain explicitly unknown. A current
snapshot is not automatically proof of historical status; document its meaning.

`--factor-calendar /absolute/path/factors.json`

Format:

```json
{"periods":[{"start_utc":"2023-11-01T00:00:00Z","end_utc":"2025-11-18T00:00:00Z",
 "factors":{"bullet":1.015,"blitz":1.005,"rapid":1.015,"classical":1.015,"ultrabullet":1.013},
 "evidence":"Describe the actual historical evidence here"}]}
```

This illustrates the file format, not an authenticated historical calendar.
Periods must cover every input completion timestamp exactly once. Changing any
input, code, factor calendar, environment or numerical setting creates a new
run identity; it never mutates an earlier result.

For lower memory use: `--workers 6 --memory-gb 8`. Larger bot-status maps cause
the launcher to reduce the effective worker count automatically.
