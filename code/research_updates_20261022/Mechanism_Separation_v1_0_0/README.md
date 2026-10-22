# Mechanism separation — v1.0.0

Run this package on the Mac with XT_Pro attached. It implements the agreed
regular-player analyses and reuses the certified panel, rating states, engine
evaluations, and all-game chronology. It launches no API collection, identity
recovery, historical rating replay, or Stockfish work.

## Run

Place the ZIP and its `.sha256` sidecar in `~/Desktop/Lichess_Desktop`, then:

```bash
cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Mechanism_Separation_v1_0_0.zip.sha256
ditto -x -k Mechanism_Separation_v1_0_0.zip .
bash Mechanism_Separation_v1_0_0/RUN_MECHANISMS.command
```

The launcher verifies the package, runs the short software tests, keeps the Mac
awake, and saves a dated terminal log. It searches existing Python environments
first. If none contains the required packages, it creates an isolated `.venv`
inside this package; it does not update an existing environment. No credentials
or network access are needed for the analysis itself.

**Planning estimate:** allow **4–12 hours for the first full run**, with wide
uncertainty. This is not a production benchmark. The new activity extraction
reads the existing chronology, and the 20-repetition recovery simulation refits
models on the full observed design. Those are likely to dominate. The code
prints progress and a heartbeat every 45 seconds. The synthetic 19,200-row
estimator/report exercise took about 12 seconds in the validation environment;
that does not establish the production runtime.

Defaults are up to 10 preprocessing workers and an 8 GB aggregate DuckDB buffer
budget. Memory-intensive history joins use at most four workers; recovery uses
at most two simultaneous full-design refits. Other large applications should be
closed on an 18 GB Mac. Retain tens of GB of free external-drive space for
activity summaries, prepared rows, spill files, and restart caches.

Rerun the same command after an interruption. Completed month extractions,
model fits, validation folds, and individual simulations are reused. It does
not rerun completed rating or engine stages. Changed input bytes or incompatible
run settings stop with an explicit message instead of mixing results.

## What it runs

1. **Support and mechanics first:** regularity attrition by month, actual payoff
   distributions, mechanical kappa(g) curves, within-chooser stake support and
   the stakes-correlation gate. Regularity uses strictly prior **recorded game
   starts**, because the available chronology does not authenticate completion
   times; the fields are labeled accordingly. Focal games cannot count as prior.
2. **Model comparison and information:** seven specified models, exact chooser
   conditional logit, full-sample and logit-sample descriptive LPM surfaces,
   index-scale K interactions, two forward validation blocks, and the recovery
   confusion table. The second activity tier and clearly-losing state are
   separate sensitivities. Authenticated historical cues activate matched
   baseline/augmented information tests. `INDISTINGUISHABLE` is a permitted result.
3. **Cost or bundle diagnostic:** exact ties and a +/-25-gap sensitivity. Separate
   stakes are reported only when support passes. Otherwise the result is one
   opponent-RD bundle association, explicitly not an own-cost bound.
4. **Policy prediction deliverable:** exact old/new payoff predictions and
   pairwise power screens. The actual post-policy cohort test requires the
   unresolved sample/calibration/censor inputs. In their absence, only clearly
   labeled pre-policy planning transport is produced. Post-policy behavioral
   outcomes are not opened by this release.

The code does **not** automatically release causal mechanism shares, label a
residual “deference,” interpret a bundle coefficient as own cost, or treat an
underpowered policy comparison as evidence for the displayed-gap model.

## Real dependencies, recorded separately

- The certified 157-column panel does not contain authenticated game-time
  provisional/title/Patron cues. The August 2026 Patron snapshot cannot answer
  what wings were visible during earlier games. `CUE_AVAILABILITY.json` records
  this; unavailable cues are not converted to zeros.
- Post-change pool/previous-adjacency membership, chronology through April,
  actual-stratum calibration, fixed preimplementation cohort eligibility and a
  source-supported censor are still needed for the actual color comparison.
  `POLICY_STATUS.json` records the dependencies. Prediction uncertainty and
  awareness remain explicit; this is not an automatic behavioral GO decision.

`INPUT_CONTRACTS.md` documents how existing authenticated sources can activate
those branches. Missing optional inputs do not prevent the pre-policy analyses.
The package does not pretend to have built post-change pool membership from
the pre-period certificate.

## Outputs to return

The last line names:

```text
~/Desktop/Lichess_Desktop/MECHANISM_RESULT_<UTC timestamp>.zip
~/Desktop/Lichess_Desktop/MECHANISM_RESULT_<UTC timestamp>.zip.sha256
```

Upload both. The ZIP contains aggregate Parquet/CSV tables, PDF/PNG figures,
support and model statuses, input checksums, and the frozen specification.
It contains no private opportunity rows or account intercepts. A partial result
ZIP is also written if a stage fails, so the cause can be reviewed without
repeating completed work.

Private reusable cache:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/mechanism_separation_v100_PRIVATE
```

Public report copies:

```text
/Volumes/XT_Pro/lichess_kindness/output/mechanism_separation_v100
```

## Optional stage commands

The default runs everything that current inputs support. For a support-only
first run, append `--phase support`; then run the original command to continue.
Other phases are `prepare`, `models`, `recovery`, `cost`, and `policy`.
Phases after preparation require its saved outputs. The default scientific
simulation count is 20; changing `--simulation-reps` changes the run identity
and must not be mixed into an existing cache.

Use `--workers 6 --memory-gb 6` to reduce resource use. Resource changes do not
change the scientific run identity. `MECHANISM_PYTHON` can select a known existing
Python interpreter. `MECHANISM_PROJECT_ROOT` and `MECHANISM_DESKTOP` can override
the two default roots.

Detailed definitions, assumptions and limitations are in `METHODS.md` and
`FROZEN_PLAN.json`. `VALIDATION.md` records the software checks performed before
delivery; it does not certify the unavailable production data.
