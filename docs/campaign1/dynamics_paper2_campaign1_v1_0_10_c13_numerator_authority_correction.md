# Campaign 1 v1.0.10: C13 fair-sample numerator authority correction

Date: 2026-08-25

Status: post-aggregate-QA, pre-C13-model numerical correction

## Trigger

The authenticated non-profile recovery v1.0.3 failed closed immediately after
joining the C13 fair base to the certified Stage-07 outcome field. Its QA tuple
was `(17,328,130, 17,328,130, 487,170, 0)`: rows, unique game IDs, kindness
outcomes, and invalid binary outcomes.

The code expected 669,503 kindness outcomes. Inspection showed that 669,503 is
the certified kindness count for all 47,587,020 Stage-07 rows. C13 is defined
on the 17,328,130 fair rows, whose certified kindness count is 487,170.

## Pre-existing independent authority

The repository artifact
`summary_stage09_panel_robustness_24m_CERTIFIED.json`, created
2026-08-21T13:49:49Z, records:

- all Stage-07 rows: 47,587,020;
- all Stage-07 kindness outcomes: 669,503;
- fair rows: 17,328,130;
- fair-sample kindness outcomes: 487,170;
- Stage-07 authority SHA-256:
  `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`;
- Stage-09 summary SHA-256:
  `5107e4dabd11054724691f6c3c6937e495b8b15648302ecd578217e81d55b6e7`;
- producing script SHA-256:
  `f0b3d8d638523e22e4bc3b665d3067a261bcfb1c3d2831d9bf8fb81e6c521431`.

This authority predates the C13 recovery and independently distinguishes the
all-panel and fair-sample numerators.

## Correction

The C13 fair-sample numerator assertion is changed from 669,503 to 487,170.
The all-panel value remains retained explicitly as a separate authority. The
code still requires exact row conservation, unique game IDs, binary support,
and the certified fair-sample sum before constructing ambient-kindness
exposures.

## What does not change

- no C13 row or sample definition;
- no outcome definition;
- no 5,000-other-opportunity support threshold;
- no denominator or leave-one-chooser-out algorithm;
- no exposure window;
- no fixed effect, control, clustering, or numerical policy;
- no planned sensitivity, nonlinear, quartile, or subgroup attempt;
- no C6/C10, C7, or C12 estimate;
- no Holm-family membership.

The v1.0.3 denominator reconciliation remains frozen at 17,101,141 supported
rows and is not revisited.

## Timing and interpretation

The aggregate fair-sample numerator count was observed because the v1.0.3 QA
failed. No ambient-kindness exposure, C13 coefficient, standard error, or
p-value had been constructed or viewed. The correction is therefore not
selected on a C13 model result. It is a sample-scope assertion repair supported
by a pre-existing certified artifact, and it will be disclosed as such.
