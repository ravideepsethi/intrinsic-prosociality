C7R FULL-PANEL PRE-FOCAL FIRST/REPEAT CENSUS

Status: C7R_FULLPANEL_PREFOCAL_V100_OK
Run ID: 20260905T122501Z

This bundle replaces the historical 1-in-50 focal-pair support with all
47,587,020 certified Stage-07 opportunities.

Definition:
  first = the focal event is the earliest rated event for its unordered pair
          in the authenticated C7R-compatible ordinary-speed chronology,
          ordered by (utc_ms, archive_ordinal, game_id).
  repeat = at least one earlier rated event exists for that pair.

Important:
- The expensive history classification was frozen BEFORE Stage-07 kindness
  outcomes were read.
- The row-level flags and pair histories remain private on XT_Pro.
- `first_repeat_raw_rates.csv` and `repeat_prevalence.csv` are census aggregates.
- `minimal_chooser_fe_desert.csv` and `minimal_chooser_fe_interaction.csv`
  are new transparent one-way chooser-FE census models with chooser-clustered
  CR1 inference.
- The historical +1.5669 / +1.3342 / -0.0087 C7R coefficients came from the
  frozen C7R v1.0.2 model family. Do NOT claim the new minimal FE coefficients
  are exact reproductions of that old adjusted model unless the old model
  engine is explicitly rerun on these full-sample flags.

Public files contain no row-level identifiers.
