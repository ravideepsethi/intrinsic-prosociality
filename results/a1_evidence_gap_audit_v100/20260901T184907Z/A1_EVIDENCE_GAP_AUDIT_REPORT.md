# A1 evidence-gap audit

**Status:** post-result sensitivity audit; the frozen A1/A3/B1 primary family is unchanged.

## Authentication and headline reproduction

The certified headline reproduced before any new analysis: +1.0047 pp (SE 0.1228; p=2.814e-16; N=1,029,558). The Stage-07 rescan recovered all 1,029,943 raw later-opportunity rows with zero outcome or timing mismatches.

## Same-benefactor and rematch diagnostics

- Dropping recipients whose original next fair opportunity was against the focal benefactor: +0.9805 pp (SE 0.1225; p=1.22e-15; N=1,029,420).
- Retargeting the outcome to the first later fair opportunity against someone other than the focal benefactor: +0.9829 pp (SE 0.1225; p=1.051e-15; N=1,029,505).
- Descriptive same-benefactor-only subgroup: +34.8495 pp (SE 20.5784; p=0.09036; N=138). This is a post-treatment subgroup, not a causal estimand.
- Treatment effect on reaching a nonbenefactor opportunity within 90 days: -0.2075 pp (SE 0.1878; p=0.2693; N=2,185,073).
- Treatment effect on the next opponent being the focal benefactor: +0.0256 pp (SE 0.0118; p=0.03008; N=1,029,558).

The exact 10-minute, 30-minute, 1-hour, 6-hour, and 1-day exclusions are in `results/same_benefactor_and_time_sensitivities.csv`. The time windows are explicit proxies; Stage 07 has no canonical session identifier, so they are not labeled as exact same-session tests.

## Next-opportunity composition

The following composition outcomes survive Holm adjustment within this new family:

- `audit_any_chooser_elo`: coefficient=+8.77187 Elo; Holm p=2.273e-25.
- `audit_any_opponent_elo`: coefficient=+9.06826 Elo; Holm p=6.179e-20.
- `audit_any_speed_0`: coefficient=-2.5192e-05 probability; Holm p=0.0001806.

All raw and adjusted composition results are in `results/next_opportunity_composition.csv`.

## Internal temporal split

- `first_12_exposure_months_2023_11_to_2024_10`: +0.9835 pp (SE 0.1441; p=8.76e-12; N=738,926).
- `second_12_exposure_months_2024_11_to_2025_10`: +1.0826 pp (SE 0.2347; p=3.962e-06; N=289,576).

This is a post-result split of the same certified panel, not an independent replication or preregistered holdout.

## Support

Headline weighted effective sample size: 117,652.9 from 1,029,558 rows. Propensity quantiles and arm-specific ESS are in `results/overlap_propensity_quantiles.csv` and `results/weight_ess.csv`.

## Interpretation

The defensible claim remains a robust conditional dynamic association consistent with behavioral transmission. Same-benefactor removal, timing exclusions, and composition checks can make simple direct-reciprocity or opportunity-selection accounts more or less plausible, but none converts the observational exposure into random assignment.
