# Pool-main reanalysis — Wave 2B1 v1.0.2

Version 1.0.2 corrects the fail-closed support handling encountered after the
v1.0.1 run had already certified the dynamic core, post-outcome audit, and
remaining A1/A2 stage. The post-result same-benefactor-only descriptive subgroup
does not satisfy the frozen recipient-model gate (at least 100 supported rows
and both exposure arms). The corrected audit now records the exact row, arm, and
outcome counts and marks an affected post-result sensitivity as unsupported.
Supported models are unchanged. Primary models, estimands, treatment and outcome
definitions, weights, inference, and multiple-testing rules are unchanged.

## Resume after the reported v1.0.1 failure

This is the command for the run that stopped at `a1_evidence_gap` after
authenticating and adopting all earlier certified stages:

```bash
cd "$HOME/Desktop/Lichess_Desktop" && /usr/bin/shasum -a 256 -c Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2.zip.sha256 && /usr/bin/ditto -x -k Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2.zip . && /bin/chmod 700 Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RESUME_AFTER_V101_FAIL.command Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RUN_WAVE2B1.command && /usr/bin/caffeinate -dimsu /bin/bash Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RESUME_AFTER_V101_FAIL.command
```

Expected remaining runtime: **4–8 hours**, most likely about **5–6 hours** on
the same Mac and XT_Pro. The completed A3 gate, dynamic core, post-outcome audit,
and remaining A1/A2 result are authenticated and reused. Because the A1 audit
script identity changed, its failed v1.0.1 private cache is moved to a timestamped,
recoverable backup and rebuilt (about 15–40 minutes). Nothing is deleted.

## Fresh run

Run this package on the Mac attached to `XT_Pro`. It rebuilds the foundational
dynamics and dyad-history chain under the certified 24-month pool/non-adjacent
main sample. It does **not** import any 47.6M-row sample-dependent cache as a
current result.

## One terminal command

```bash
cd "$HOME/Desktop/Lichess_Desktop" && /usr/bin/shasum -a 256 -c Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2.zip.sha256 && /usr/bin/ditto -x -k Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2.zip . && /bin/chmod 700 Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RUN_WAVE2B1.command && /usr/bin/caffeinate -dimsu /bin/bash Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RUN_WAVE2B1.command
```

Expected fresh-run runtime: **8–14 hours**; budget an overnight run.

The launcher uses these defaults:

- Project: `/Volumes/XT_Pro/lichess_kindness`
- Certified sample: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`
- Workers: `10` (producers capped at 8 where their frozen implementation requires it)
- DuckDB memory limit: `12GB`
- Per-worker second-wave memory: `3GB`
- Free-space gate: `80 GiB`
- Return directory: `~/Desktop/Lichess_Desktop`

It first looks for the compatible Python environment created for Wave 1 or
Wave 2A, so a normal run makes no network request. If no compatible environment
exists, it stops. Dependency download is an explicit opt-in:

```bash
POOL_MAIN_ALLOW_PIP=1 ./Pool_Main_Sample_Reanalysis_Wave2B1_v1_0_2/RUN_WAVE2B1.command
```

## What this tranche rebuilds

1. Arm-blind A3 all-game chronology linkage and outcome-selection gate.
2. Frozen A1/A3/B1 dynamic core and its three-primary Holm family.
3. Core post-outcome audit, remaining A1/A2 analyses, and both A1 evidence audits.
4. Second-wave feasibility, B2 timing/randomization, sampled user and dyad histories,
   prespecified results, postprimary robustness, and independent E1 audit.
5. Full-panel pre-focal first-versus-repeat meeting analysis (C7R).

The canonical 7.76-billion-row all-game chronology is reused because Wave 2A
authenticated it as sample-invariant. Every sample-dependent exposure, support,
propensity, history join, model, and aggregate listed above is rebuilt.

## Resume behavior

The run is intentionally resumable. Re-run the same command after interruption.
Stable run IDs and private receipts cause completed stages to authenticate and
skip; partial producer checkpoints resume under the isolated Wave 2B1 project
view. To resume explicitly at a later stage, append `--start-at STAGE`, where
`STAGE` is printed in the prior log. Upstream stages must already be certified.

Do not delete or move
`derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1` while the run is
in progress.

## Expected return

On success, the launcher writes a matched pair to `~/Desktop/Lichess_Desktop`:

- `POOL_MAIN_REANALYSIS_WAVE2B1_RESULTS_<UTC>.zip`
- `POOL_MAIN_REANALYSIS_WAVE2B1_RESULTS_<UTC>.zip.sha256`

Upload both files. The ZIP is aggregate-only and receives an independent
privacy scan, member manifest, CRC test, and SHA-256 sidecar.

## Scope boundary

The chooser-leniency IV is already running as a separate branch and is not
duplicated here; its requested role-selection decomposition must be checked when
the branches are merged. Campaign-1 recovery and targeted-memory/ply retrofits
remain for Wave 2B2. Patron matching and unified manuscript tables, figures,
abstract count, and Sections 5–6 remain blocked until Wave 3.

Do not update the manuscript from this tranche alone.
