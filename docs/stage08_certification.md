# Stage 08 24-month core-results certification

**Certification status:** `STAGE08_CORE_24M_CERTIFIED_OK`
**Canonical sample:** November 2023 through October 2025
**Certification timestamp:** `2026-08-19T03:47:53Z`

## Scope and authority

Stage 08 reads only the frozen Stage 07 analysis panel and produces the
panel-only core paper results: Tables 1–9, Appendix split-half tables, and
analytical data for Figures 2, 3, A1, A2, A3, and A4. It authenticates every
one of the 24 Stage 07 inputs before estimation.

The canonical machine-specific output root is:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/paper_results_core_24m_sf100k
```

Patron/profile analyses, opening familiarity, abandonment/reentry,
post-sample holdouts, the November 2025 color breakpoint, historical
rating-rule validation, publication rendering, and the planned million-node
engine audit are outside this stage.

## Producer identity

- Script: `code/08_make_core_paper_results.py`
- Version: `1.2.0`
- SHA-256: `e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f`
- Production Git commit: `f8702654a5280763022f78c43e438d8621224164`
- Stage 07 success SHA-256: `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`
- Stage 08 success-receipt SHA-256: `a2fd1a868299cba8499de1e72365dbeb4e49ec77768e01e8af84f58f3ceac958`
- Ordered output-manifest SHA-256: `1cde9cfb91ca90c50901f03e3480edead9aec09dff069107b6f749e879435556`
- Authenticated output files: 30

## Certified sample

| Quantity | Certified value |
| --- | ---: |
| Rows | 47,587,020 |
| Unique choosers | 3,556,701 |
| Kind draws | 669,503 |
| Overall kind-draw rate | 1.407% |
| Fair rows | 17,328,130 |
| Clearly-worse rows | 26,090,163 |
| Excluded-middle rows | 4,168,727 |

## Fairness gradient

| Disconnected-player position | Rows | Kind draws | Kind rate |
| --- | ---: | ---: | ---: |
| `disconnected_clearly_better` | 3,517,357 | 128,259 | 3.646% |
| `disconnected_better` | 3,314,026 | 80,471 | 2.428% |
| `roughly_equal` | 10,496,747 | 278,440 | 2.653% |
| `modestly_worse_excluded` | 4,168,727 | 51,492 | 1.235% |
| `clearly_worse` | 26,090,163 | 130,841 | 0.501% |

Across the three fair/competitive bins, the kind-draw rate is
2.811%. It is 0.501% when the disconnected player is
clearly worse: a 2.310-percentage-point gap and a 5.61-fold
ratio. These are descriptive contrasts, not randomized treatment effects.

## Rating-price threshold

The main Table 2 specifications compare favorable and costly draws within
symmetric payoff windows, absorb chooser fixed effects, control linearly for
the win premium, and cluster by chooser.

| Payoff window | Favorable coefficient (pp) | SE (pp) | t |
| --- | ---: | ---: | ---: |
| ±0.5 | 0.233 | 0.010 | 23.42 |
| ±1 | 0.316 | 0.008 | 38.39 |
| ±2 | 0.409 | 0.008 | 54.10 |
| ±4 | 0.435 | 0.007 | 58.63 |
| ±6 | 0.445 | 0.007 | 60.09 |

The favorable-draw coefficient is positive in every bandwidth, ranging from
0.233 to 0.445 percentage points. In the raw 2×2 decomposition, making the draw
favorable instead of costly is associated with a 0.549-point
increase in fair positions but only 0.011 points when the
disconnected player is clearly worse.

In the chooser-fixed-effect specification with controls, the implied favorable
premium declines from 0.487
points at −100 centipawns to 0.286
points at +600 centipawns.

## Persistent heterogeneity

Among choosers observed in both 12-month halves, those who ever made a kind
choice in the first half have a second-half kind rate of
14.949%, compared with
1.038% for those who never
did—a 14.40-fold ratio.

At the minimum-four-opportunity cutoff:

- the random MD5 split gives second-half rates of
  16.747% versus
  0.946% and an
  unweighted Pearson correlation of
  0.590; and
- the temporal split gives second-half rates of
  14.709% versus
  0.978% and an
  unweighted Pearson correlation of
  0.532.

These are strong out-of-sample persistence facts. The `ever_kind` comparison
is a predictive classification rather than a causal effect or a structural
type estimate.

## Numerical and robustness certification

- The production run authenticated all Stage 07 inputs and passed transactional
  output QA.
- The exact two-way Schur fixed-effect absorber has scaled residual group means
  below `1e-12` in every Table 4 quantile specification.
- The SciPy-free Spearman implementation was exercised by the hardened tied-rank
  and full split-half numerical tests before production.
- All 30 generated files match the certified byte counts and SHA-256 hashes in
  the output manifest.

Table 5 requires a substantive guardrail: the zero-cutoff slope-asymmetry
statistic is robust to flexible win-premium controls, but several nonzero
placebo cutoffs also reject slope smoothness—3 of 8 in the half-point window
and 6 of 8 in the one-point window at `|t| >= 1.96`. The placebo grid therefore
does not show that the slope kink is unique to zero. This does not negate the
separate Table 2 zero-threshold level contrast, but the paper should not market
the piecewise-slope result as a uniquely localized discontinuity.

## Repository boundary

The repository stores the exact success receipt, full 30-file hash manifest,
quantile-edge receipts, compact key-results certification, design and QA notes,
and this human-readable certification. It does not store the 47.6-million-row
panel, caches, or generated table and figure-data CSVs.

Stage 08 is frozen at the identities above. Later extensions must add and
authenticate their own external inputs rather than silently reusing legacy
10k-node outputs.
