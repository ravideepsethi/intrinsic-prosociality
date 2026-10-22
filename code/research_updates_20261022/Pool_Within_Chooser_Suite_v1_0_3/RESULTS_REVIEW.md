# Within-chooser v102: verified results and remaining S4 check

The weighting repair succeeded. Main state models, inverse-account weighting,
chooser-by-speed fixed effects, and selected-profile Patron interactions pass
their saved numerical checks. Only S4 (exact opening-ply adjustment) remains
uncertified. The complete suite is therefore still partial.

## Authentication and sample

- Uploaded archive SHA-256:
  `e9bce31cbd75c7021850611912837a10060a98fe535982b220cc2a39073bb1ef`.
- ZIP CRC clean; 252/252 report manifest entries verified.
- Source fingerprint:
  `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
- Common sample: 41,534,331 opportunities, 570,091 grants, 3,224,173 accounts.
  No complete-control exclusions. 819,297 singleton chooser units contribute no
  within-chooser variation; 40,715,034 rows are in nonsingleton chooser units.
- Recorded runtime: 447.4078 seconds before archiving, or 7.46 minutes, with ten
  worker processes and one numerical thread per worker.

## Main results

Adjusted grant-probability differences in percentage points; chooser-clustered
standard errors in parentheses. These are regression contrasts, not raw rates.

| Contrast | Main chooser FE | Account-weighted | Chooser × speed FE |
|---|---:|---:|---:|
| Competitive vs. losing: standardized | 1.774 (0.011) | 2.319 (0.018) | 1.755 (0.011) |
| Competitive vs. losing: plies 11–20 | 1.909 (0.014) | 2.383 (0.025) | 1.887 (0.014) |
| Competitive vs. losing: plies 21–40 | 1.667 (0.010) | 2.173 (0.015) | 1.648 (0.010) |
| Competitive vs. losing: plies 41–80 | 1.541 (0.010) | 2.105 (0.018) | 1.523 (0.010) |
| Equal: plies 21–40 vs. 0–4 | -2.275 (0.019) | -2.507 (0.032) | -2.266 (0.019) |
| Equal: plies 41–80 vs. 0–4 | -2.603 (0.020) | -2.899 (0.036) | -2.588 (0.021) |

Competitive means the disconnected opponent's evaluation is at least -100 cp;
clearly losing means at most -300 cp. Competitive-state and game-stage shares
are held fixed across models. Board-state contrasts compare positions within
ply bands; the final two rows compare game stages within roughly equal positions.
The 0–4 band actually begins at ply 2 in this sample.

All columns adjust for month-by-speed effects, both recorded clocks and
missingness, rating gap, forgone win premium, pre-game rating uncertainty and
chooser rating. Main and weighted columns absorb chooser FE; column 3 absorbs
chooser-by-speed FE. Weighting is 1/N_i per observation, so each chooser has total
raw weight one. This changes the regression projection; it is not an average of
person-specific causal effects.

The main standardized contrast is 1.773919 pp (SE 0.010527; 95% pointwise CI
1.753286–1.794552). The corresponding account-weighted result is 2.318900 pp
(SE 0.017583; CI 2.284438–2.353363), and chooser-by-speed FE gives 1.755000 pp
(SE 0.010689; CI 1.734050–1.775951). The S1/S2/S3 ladder is 1.801/1.788/1.774 pp.

The substantive result is systematic state dependence within people: the same
chooser grants more often when the absent opponent remains competitive, and
less often after more play within roughly equal positions. These patterns
cannot be explained entirely by stable differences in generosity across people.
They do not establish causal effects of deservingness, time invested, or rating
cost: time-varying circumstances and selection into observed actions remain.
All comparisons condition on the remaining player acting.

## Numerical status

| Model/family | Current status |
|---|---|
| A, S1, S2, main S3 | Saved estimates pass; recovered and exported |
| Inverse-account weighting | Completed and numerical checks passed |
| Chooser × speed FE | Completed and numerical checks passed |
| Patron interactions | Completed; selected-sample diagnostic only |
| S4 exact opening ply | Score conservation fails; do not report as finalized |
| Prior rating/payoff and recipient-FE analyses | Authenticated copies, not rerun |

The state module failed after saving S3, so its combined table was not written.
Recovery reproduces the saved coefficient vectors from moments and exports their
unchanged covariance arrays. Main S3's score error is 1.36e-12; score-versus-moments
error is 2.60e-15. The inverse-weight result has score error 8.11e-13 and now passes
the positive-weight nullspace check that failed in v101.

S4's score error remains 3.12768e-6, above the unchanged 1e-7 threshold. Its largest
saved residual-score sum is +0.304561 for early_ply_13, whereas the moment-implied
value is about -4e-9. The original moment checks passed. This localizes an
inconsistency between the two calculation passes; it does not identify the exact
operation or numerical backend causing it. Do not label it a proven BLAS bug or
resolve it by relaxing the guard.

## Patron diagnostic

The selected returned-profile model includes 28,798,483 opportunities from
1,231,798 accounts, including 4,680 Patrons and 150,952 Patron opportunities.
At plies 21–40, the Patron-minus-non-Patron difference in the within-chooser
competitive-versus-losing contrast is +3.109 pp (SE 0.333); at plies 41–80 it is
+3.382 pp (SE 0.336). The all-stage standardized interaction is not identified.

The 12,735,848 unclassified opportunities contain only 62 grants. The profile
frame was selected using kindness history, and status was measured after the
game window. Thus these are selected-sample diagnostics, not population Patron
comparisons or causal effects of donating.

## Targeted next run

Pool_Within_Chooser_Suite_v1_0_3 authenticates the returned report and the existing
narrow private Parquet cache, then reruns S4 alone. It reuses the valid estimates.
Independent columnwise centering, prediction and score reductions plus
cross-pass design hashes provide an alternative calculation and sharper failure
diagnostics. The same specification and original numerical tolerances remain.

Production-width synthetic tests match independent full-dummy WLS contrasts to
5.1e-15 and contrast variances to 1.1e-16. Fault-injection and end-to-end complete/
partial-report tests pass. The private dataset is not available in this review
environment, so S4 has not yet been rerun on the real data.

Expected runtime: 3–6 minutes with ten workers; allow 10 minutes plus environment
setup. The package includes the full command in LAUNCH_MAC.txt. Upload the new
v103 result ZIP and its SHA sidecar when it finishes.
