# Dynamics of Intrinsic Prosociality — Campaign 1

## v1.0.5 Post-Outcome Technical Correction and Immediate-Execution Directive

**Date:** 2026-08-25  
**Status:** author-directed post-outcome correction; not a preregistration  
**Known governing base:** v1.0.0 plus amendments v1.0.1, v1.0.2, and v1.0.3  
**Version note:** an audit-session document called v1.0.4 is reported in the handoff,
but its bytes are absent from the authenticated corrective source collection. This
document therefore does not claim to reproduce or silently incorporate that unavailable
text. It supersedes only the technical and operational matters stated here.

This record is necessarily post-outcome. Two C1 implementations had already exposed
incompatible estimates before the underlying encoding error was physically adjudicated.
The correction is documented openly rather than represented as blind or pre-outcome.

---

## 1. Physical result-code adjudication

The exact locked chronology file

```text
/Volumes/XT_Pro/lichess_kindness/derived/glicko2_replay/
rating_events_replay_sorted_v2_time/events_replay_sorted_time/
speed=blitz/month=2024-10/part-00000.parquet
```

was queried read-only. Its complete `result_code` support and counts are:

| Raw code | Rows | Meaning fixed by the producing source |
| ---: | ---: | --- |
| 0 | 20,340,159 | Black win |
| 1 | 1,916,130 | Draw |
| 2 | 21,888,082 | White win |

All 44,144,371 rows have a non-null result code, and row conservation passed. The
authenticated historical producer independently shows the same mapping:
`1-0 -> 2`, `1/2-1/2 -> 1`, and `0-1 -> 0`.

The exact decoder from White's perspective is therefore:

```text
2 -> +1
1 ->  0
0 -> -1
```

Only after this decoding may the sign be negated when the chooser was Black.

## 2. Invalidation of the two earlier C1 lineages

Run A (audit-session lineage, approximately +0.245 percentage points) and Run B
(production lineage, -0.8317 percentage points) are both classified
`INVALID_RESULT_CODE_SEMANTICS` and are excluded from substantive interpretation and
multiple-testing calculations.

Both lineages were reported to apply the raw chronology code directly for White, negate
it for Black, and retain only `{-1,0,+1}`. On a physical `{0,1,2}` field, that procedure:

- drops true White wins because they become `+/-2`;
- relabels draws as chooser wins or losses according to color; and
- relabels true Black wins as draws.

Run B exhibits the predicted forensic fingerprint: 217,589 resolved primary bridge rows
collapse to 108,543 regression rows, and 112,725 resolved lag triples yield only two
direct three-win/three-loss streak observations. Run A's different reported fingerprint
remains a provenance puzzle, but it cannot rescue an implementation with the same
invalid decoder. Old output trees remain immutable forensic evidence.

## 3. Authorized corrected C1 rebuild

One new C1 build is explicitly authorized under a new output root. This is a technical
repair of the frozen C1 estimand, not an outcome-responsive change to its sample,
controls, inference, session definition, or epistemic label.

The corrected producer must:

1. authenticate the exact historical chronology producer and the physical decider;
2. reject every raw result code outside `{0,1,2}`;
3. decode raw code to White-signed result before converting to chooser perspective;
4. use rating-difference signs only as a validator, never to construct the exposure;
5. report raw-code counts, chooser win/draw/loss marginals overall and by speed, bridge
   row conservation, and all post-bridge sample counts;
6. fail closed if primary bridge coverage is below 99%, if any bridge row has an invalid
   side or code, or if decisive rating-difference signs materially contradict the
   decoded chooser perspective;
7. report the prespecified direct three-loss versus three-win secondary whenever its
   frozen complete-case support rule is met; and
8. write only aggregate public outputs and never mutate an earlier C1 result tree.

The prior duplicate-primary guard is superseded for this one correction because it
checked only an obsolete Wave-1 flag and could not see the independently completed
audit lineage. The correction record itself is the authorization; future duplicate C1
builds remain unauthorized unless separately documented.

## 4. C9 serialization-only recovery

The completed C9 scientific computation is not contaminated by the C1 outcome-code
error because it used chronology identities and timestamps, not `result_code`. Its
4,999 randomizations and exact B2 reproduction completed before a heterogeneous CSV-row
schema caused publication to fail.

A serialization-only recovery is authorized. It must authenticate every existing
checkpoint, require zero missing checkpoint batches, draw no new randomizations,
re-run the exact B2 reproduction check, give all component rows a uniform explicit CSV
schema, and publish to a new output root. Any missing checkpoint is a hard stop rather
than permission to recompute within this recovery.

## 5. Immediate execution and analysis scope

The author directs that every scientifically useful analysis be run as soon as its own
required inputs exist. There is no artificial sequencing hold, no C1-based hold on
independent modules, and no reservation of available analyses for a later paper or later
chat. Only a genuine missing or uncertified input, a permission boundary, or a technical
failure may block work.

This directive does not suppress analytical breadth. Prespecified analyses retain their
existing `[C]`, `[S]`, or `[X]` labels. Additional specifications, diagnostics,
heterogeneity checks, robustness analyses, and outcome-informed searches may also be
run now, but anything not fixed before outcome inspection must be labeled transparently
as post-outcome exploratory. The complete analysis record must retain favorable, null,
and unfavorable results alike.

## 6. Rules unchanged

Except for the explicit corrections and execution rules above, the frozen scientific
design remains unchanged, including:

- C1's 30-minute start-to-start primary session definition and 15/60-minute
  sensitivities under v1.0.3;
- chooser fixed effects, chooser-clustered inference, and the current-state controls;
- Holm family D membership: C1, C2, C5, C6, and C9;
- the C6 and C7 support-gate rules;
- the C9 draw-specific pseudo-first-grant rule;
- privacy and aggregate-output restrictions;
- the prohibition on new Lichess API acquisition inside Campaign 1; and
- the requirement to authenticate every input authority fail-closed.

Holm adjustment is performed only after valid raw p-values and the prespecified gate
status are available for all family members needed by the effective plan. Invalid C1
lineages never enter that calculation.
