# Campaign 1 — B2 First-Grant Anchoring Audit Resolution

**Date:** 2026-08-24
**Status:** `B2_SEQUENCE_SPECIFIC_FIRST_GRANT_ANCHORING_VERIFIED`
**Scope:** Campaign 1 C9 implementation precondition only.

## Question

The frozen Campaign 1 plan requires every conditional-randomization draw to identify
its **own simulated first grant** and to construct every post-first-grant window relative
to that draw-specific anchor. Reusing the observed first-grant timestamp in every null
draw would be invalid.

## Audited authorities

- Campaign base-plan SHA-256: `ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe`
- Campaign v1.0.1 amendment SHA-256: `01c0ed96bfca62b1659a98d978bedaaf9a4540fcdc5a30a075e2f032e35e05ee`
- Historical B2 producer commit: `1418976974e1b7857407f1b2a717a5c11f9c88a1`
- Historical producer path: `code/10f_estimate_b2_first_grant_dynamics.py`
- Historical producer Git blob: `58000cfb8b1581947d803e73300407037726539b`
- Targeted read-only audit report SHA-256: `02a6aed69593970e202ec7959f42bdd1a3d98ca4ed6af19393c242d89965267f`

## Finding

The historical B2 producer satisfies the frozen rule.

The simulated grant matrix has one row per randomization. Inside
`event_window_totals`, the producer computes:

```python
first = np.argmax(choices, axis=1)
```

so each simulated sequence obtains its own first simulated grant. The horizon calculation
then uses the corresponding `times[first]`, and the post-first numerator subtracts the
cumulative total at that same draw-specific `first`.

Upstream, `simulate_batch` constructs the simulated `choices` matrix under the exact
conditional sampler, preserving each chooser's observed grant total, and passes those
simulated choices directly to `event_window_totals`. The null therefore does **not**
reuse a first-grant index taken from the observed sequence.

The historical second-wave plan states the same contract: every simulated sequence
defines its own first observed grant.

## Adjudication

- B2 does **not** require a rerun because of first-grant anchoring.
- The Campaign 1 B2/C9 anchoring precondition is **cleared**.
- C9 may inherit the authenticated B2 conditional-randomization machinery.
- C9 must additionally recompute its Section 3 same-session/later-session and
  same-pool/different-pool partitions under **each draw's pseudo-first grant**.
- This is a software/provenance determination only. Campaign 1 estimation remains
  unauthorized until the flagship submission and the other frozen execution conditions
  are satisfied.

## Non-claim

This audit resolves only the specific first-grant anchoring question. It is not a new
substantive result and does not independently recertify every aspect of B2.
