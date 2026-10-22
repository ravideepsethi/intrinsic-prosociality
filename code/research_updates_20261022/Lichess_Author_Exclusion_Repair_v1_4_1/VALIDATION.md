# v1.4.1 local validation

- Returned ZIP SHA256 and all 688 report entries verified.
- Corrected comparisons: 256/256 tables aligned, zero membership mismatches, 27,041 point estimates, maximum movement 0.0209698 included SE; no sign, approximate 95% zero-boundary, or identification-status changes.
- 38 local tests pass: five policy, six extension, six continuation, five v130 repair, nine remaining-family, one covariance-export, and six new v141 regression tests.
- New tests also verify adoption of completed v140 fits and audits without refitting, with rejection of altered reports. Tests cover authenticated original-cache discovery through copied receipts and rejection after mutation; baseline convergence statuses and rejection of new failures; temporal and merit alignment; actual tenure SQL binding; outcome-specific weighted coefficients and cross-outcome HC1 sandwich covariance against an independent calculation, including scale invariance and the equal-weight special case.
- All code files parse; launchers pass bash syntax validation.
- Full production reruns have not run here. Persistence weighting is a declared reconstruction candidate guarded by all printed regression checks; original producer is unavailable.
