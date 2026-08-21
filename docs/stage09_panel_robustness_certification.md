# Stage 09 24-month panel-robustness certification

- **Certification status:** `STAGE09_PANEL_ROBUSTNESS_24M_CERTIFIED_OK`
- **Canonical sample:** November 2023 through October 2025
- **Certification timestamp:** `2026-08-21T13:49:49Z`

## Scope and authority

Stage 09 reads the frozen Stage 07 panel and authenticated Stage 08 authority.
It produces panel-only density/support diagnostics, exact-zero sensitivity,
speed/rating/tournament heterogeneity, engine-evaluation cutoff sensitivity,
and economic-magnitude benchmarks. Patron/profile data and opening metadata are
not inputs to this certified panel output.

## Producer identity

- Script: `code/09_build_panel_robustness.py`
- Version: `1.1.0`
- SHA-256: `f0b3d8d638523e22e4bc3b665d3067a261bcfb1c3d2831d9bf8fb81e6c521431`
- Production Git parent: `a7ce86a06c406cf7cfbeb4927cdf40ba5bce4bee`
- Stage 07 success SHA-256: `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`
- Stage 08 success SHA-256: `a2fd1a868299cba8499de1e72365dbeb4e49ec77768e01e8af84f58f3ceac958`
- Stage 09 success-receipt SHA-256: `5107e4dabd11054724691f6c3c6937e495b8b15648302ecd578217e81d55b6e7`
- Ordered output-manifest SHA-256: `2321277ae52a54629919c9e982a4c16a6dcf5bfaeaf62c74dbf74366693150a9`
- Authenticated output files: 13

## Certified sample

| Quantity | Value |
| --- | ---: |
| Rows and unique games | 47,587,020 |
| Kind draws | 669,503 |
| Fair rows | 17,328,130 |
| Clearly-worse rows | 26,090,163 |
| Excluded-middle rows | 4,168,727 |
| Standard-fair exact-zero payoff rows | 244,300 |

## Fairness gradient and cutoff robustness

Under the canonical `fair >= -100` and `clearly worse <= -300` definitions,
the kind-draw rate is 2.811% in fair
positions and 0.501% in
clearly-worse positions. The descriptive gap is
2.310 percentage points and the
rate ratio is 5.61.

Across the six chooser-fixed-effect models using fair thresholds -50, -100,
and -150 and payoff bandwidths 2 and 6, the favorable coefficient ranges from
0.404 to 0.447 percentage points. The rate gradient also
persists across every nonoverlapping fair/clearly-worse threshold pair in the
reported grid.

## Exact-zero sensitivity

Excluding exact-zero payoffs gives strict-positive coefficients of
0.410
points (SE 0.008)
in the two-point window and
0.446
points (SE 0.007)
in the six-point window.

When exact zero is a separate category, its coefficient is
0.367
points in the two-point window and
0.377
points in the six-point window. The strictly positive coefficient remains
approximately 0.410--0.447 points. Exact-zero mass therefore does not generate
the favorable/non-loss result.

## Heterogeneity and support

Every estimable speed, chooser-rating-tier, and tournament-status subgroup has
a positive favorable coefficient. Across the reported subgroup/bandwidth grid,
coefficients range from 0.229 to 2.063 percentage
points.

Within standard-fair positions, the right-side share excluding exact zero is
approximately one half in narrow symmetric payoff windows. The running-variable
tables also document a large exact-zero mass. These are support and heaping
diagnostics, not evidence for a conventional regression-discontinuity design.

## Economic magnitude

The certified descriptive benchmarks report approximately
400,270 excess fair-position kind draws
relative to the clearly-worse rate and approximately
47,997 excess favorable-within-fair
kind draws relative to the costly-within-fair rate. These are descriptive
counterfactual counts, not causal estimands.

## v1.0 to v1.1 QA resolution

All eleven common v1.0 files were authenticated and compared. Nine are
byte-identical. The density and aggregate economic-magnitude CSVs differ only by
machine-scale parallel floating-point aggregation: maximum absolute differences
`1.021e-14` and `1.863e-08`, respectively. All counts, text fields, schemas,
row order, and substantive numerical results agree. Tables R11 and R12 are the
only new files. The typed comparison is recorded in
`provenance/stage09/semantic_equivalence_stage09_v1_0_to_v1_1.json`.

## Opening-familiarity status

The companion opening plan is certified: 4,737,283 unique targets, including
2,157,351 reusable seed rows and 2,579,932 rows still requiring acquisition.
The recovered legacy rule is `ply_count <= 10`. The plan contains 8,600
requests of at most 300 IDs and 22 macro-batches of at most 120,000 IDs.

The opening target plan is certified, but full metadata acquisition and the
24-month opening-familiarity analysis are **not** yet complete. Opening API work
must not run concurrently with the active patron/profile acquisition.

## Interpretation and repository boundary

The results support a robust fairness gradient and a favorable/non-loss payoff
gradient. They do not establish that zero is a uniquely located causal kink.

The repository stores the exact Stage 09 success receipt, the full 13-file hash
manifest, compact key results, semantic-equivalence audit, design/QA notes, and
sanitized opening-plan certification. It does not store row-level data,
generated result-table CSVs, target game IDs, Parquet files, API responses,
completion ledgers, or caches.
