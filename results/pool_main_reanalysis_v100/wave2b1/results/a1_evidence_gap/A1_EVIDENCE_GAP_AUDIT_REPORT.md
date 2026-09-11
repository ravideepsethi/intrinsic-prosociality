# A1 evidence-gap audit

**Status:** post-result sensitivity audit; the frozen A1/A3/B1 primary family is unchanged.

## Authentication and headline reproduction

The certified headline reproduced before any new analysis: +0.8817 pp (SE 0.1224; p=5.894e-13; N=993,762). The Stage-07 rescan recovered all 994,219 raw later-opportunity rows with zero outcome or timing mismatches.

## Same-benefactor and rematch diagnostics

- Dropping recipients whose original next fair opportunity was against the focal benefactor: +0.8819 pp (SE 0.1224; p=5.834e-13; N=993,678).
- Retargeting the outcome to the first later fair opportunity against someone other than the focal benefactor: +0.8818 pp (SE 0.1224; p=5.847e-13; N=993,734).
- Descriptive same-benefactor-only subgroup: not estimable under the frozen support rule (fewer_than_100_supported_rows; N=84; mercy=3; claimed=81). This is a post-treatment subgroup, not a causal estimand.
- Treatment effect on reaching a nonbenefactor opportunity within 90 days: -0.1970 pp (SE 0.1942; p=0.3103; N=2,110,400).
- Treatment effect on the next opponent being the focal benefactor: +0.0006 pp (SE 0.0052; p=0.9019; N=993,762).

The exact 10-minute, 30-minute, 1-hour, 6-hour, and 1-day exclusions are in `results/same_benefactor_and_time_sensitivities.csv`. The time windows are explicit proxies; Stage 07 has no canonical session identifier, so they are not labeled as exact same-session tests.

## Next-opportunity composition

The following composition outcomes survive Holm adjustment within this new family:

- `audit_any_chooser_elo`: coefficient=+7.43268 Elo; Holm p=2.051e-19.
- `audit_any_opponent_elo`: coefficient=+7.56794 Elo; Holm p=1.67e-16.

All raw and adjusted composition results are in `results/next_opportunity_composition.csv`.

## Internal temporal split

- `first_12_exposure_months_2023_11_to_2024_10`: +0.8578 pp (SE 0.1433; p=2.162e-09; N=714,831).
- `second_12_exposure_months_2024_11_to_2025_10`: +0.9353 pp (SE 0.2349; p=6.867e-05; N=277,378).

This is a post-result split of the same certified panel, not an independent replication or preregistered holdout.

## Support

Headline weighted effective sample size: 112,757.0 from 993,762 rows. Propensity quantiles and arm-specific ESS are in `results/overlap_propensity_quantiles.csv` and `results/weight_ess.csv`.

## Interpretation

The defensible claim remains a robust conditional dynamic association consistent with behavioral transmission. Same-benefactor removal, timing exclusions, and composition checks can make simple direct-reciprocity or opportunity-selection accounts more or less plausible, but none converts the observational exposure into random assignment.
