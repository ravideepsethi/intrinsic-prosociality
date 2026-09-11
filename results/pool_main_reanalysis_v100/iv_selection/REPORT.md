# Chooser-IV selection addendum

This report supplies the previously omitted active-given-time-forfeit-candidate check. It also estimates whether the historical chooser score predicts entry into the candidate set itself.

The time-forfeit candidate set is exactly `active_timeout OR passive_outoftime`; the runner requires those categories to be mutually exclusive. Candidate incidence is estimated in the full eligible, history-supported comparison frame. Active-given-candidate is separately residualized and estimated only within candidates. Both use the same pregame controls, fixed effects, score definitions, current-IV scaling, and shared-account/date CR0 covariance as the returned main IV report.

This is a requested post-hoc selection diagnostic. It is not part of a confirmatory family and does not certify exclusion, random assignment, or a causal effect. Read `summary.json`, `estimates.csv`, and `sample_flow.csv` together.
