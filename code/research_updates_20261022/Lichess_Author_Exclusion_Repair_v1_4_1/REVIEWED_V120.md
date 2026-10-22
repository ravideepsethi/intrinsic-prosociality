# Review of returned v1.2.0 report

Source: `AUTHOR_EXCLUSION_REPORT_c5784554d40c84d9_100.zip`.
SHA256: `85c3de90620f80c5bd2b6e6575bd6b6255e2a5c22eb62e9bc57525b1bedcdba4`.
All 298 manifested report files verified. Elapsed time: 3,778.112 seconds, about 63 minutes.

Ten paired families completed: core, panel robustness, rating gap, nonparametric, controlled reference, merit, R11, primary Patron, matched receipt and activity. The included session baseline was adopted; the excluded session stage failed during the descriptive length aggregation after the 20 regression specifications reached their saved moment checkpoints.

| Audit | Returned finding |
| --- | --- |
| Current primary IV and R9 donor lineage | Verified: 3,103,280 primary rows; 47,551,226 author-clean donor rows. The fixed standardization SD is 0.04979005187533171. This is not a fresh included-IV comparison or clearance of every IV sensitivity. |
| Reputation | Existing author-excluded result verified: 8,300,865 feature rows and 9,505,047 return rows. |
| Stakes | Existing author-excluded result verified: 15,207,414 rows. |
| Framework | Blocked by SQL parsing of the alias `name` in author-ID resolution; v1.3.0 uses explicit unreserved aliases. |
| Regular equal/losing mechanism | 25 author-involving eligible observations among 15,263,009 rows; requires actual refitting. |

The comparison reported 15,909 point estimates, four sign changes, two approximate 95% zero-boundary flags and a maximum change of 0.704335 included standard errors. All these flagged changes occur in nonparametric results. Four sign changes concern nuisance coefficients without reported standard errors. The two boundary flags are the same coefficient duplicated between coefficient and curve tables: early-ply, m300_m100, gap_m2, −0.487532 to −0.482763 percentage points, a change of 0.019189 included standard errors.

The largest change is the stableRD_K95, p100_p300, gap_p8 contrast: 1.560591 to 0.406708 percentage points. It cannot be attributed cleanly to author exclusion. Independently recomputed approximate K95 cutoffs were 41.078723036679854 versus 40.62293472141922. This changed stable-RD subsamples by thousands of rows even though only 42 author-involving main-panel games were removed. K20/K50 control bins were also independently recomputed. v1.3.0 uses one exact author-free set of cuts for both variants and retains the old results for provenance.

This diagnosis does not imply that every difference will vanish. Sparse/rank-deficient nonparametric specifications also require attention. No statistical or substantive equivalence claim is made.
