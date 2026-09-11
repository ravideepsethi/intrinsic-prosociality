# New-main-sample Patron design rebuild

The 24-month chooser histories and deterministic matches have been rebuilt on the certified pool nonadjacent sample. The original acquisition planner's chooser-summary and matching functions and SHA-256 seed were used unchanged.

Primary fair-kind target membership gate: **BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE**. 77 target accounts were never queried in August; 130 were queried but did not return a profile. These are separate kinds of missingness.

This package estimates no Patron coefficients and does not update manuscript Patron numbers. It decodes acquisition identities, return flags and stored match fields only. A membership pass does not certify an estimation sample: return attrition, structural match support, covariate construction and statistical estimation still need their recorded gates.

If target membership is incomplete, do not silently rematch inside the available August profiles or treat unqueried accounts as non-Patrons. The old snapshot sampled all old kind choosers but only selected old never-kind controls; some old kind accounts are now controls. The coverage/transition tables show this selection mechanism. A redesign using this historical acquired cohort must label its population and justify sampling/weighting. A fresh snapshot would measure Patron status at a different date and must not be mixed into the August outcome unnoticed.

original_group_retention_diagnostic.tsv describes retention of the original acquired groups with a now-fair-kind focal chooser; it does not select an alternative main analysis. Only the fresh target uses the new match cells. No profile API requests were made. Account-level artifacts and identifiers remain in private project state.

The sample reset was requested after seeing old-sample results. This is a deterministic reset/coverage diagnostic, not a new preregistration.
