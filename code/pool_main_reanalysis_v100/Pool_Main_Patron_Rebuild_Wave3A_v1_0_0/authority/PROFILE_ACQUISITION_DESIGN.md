# Design record: 24-month profile and patron acquisition

## Decision

Begin the acquisition track immediately because it is quota-bound and can run in
parallel with panel-only robustness work. Do not reuse the old one-year profile file as
if it covered the frozen two-year sample, and do not execute the historical fetcher.

The recovered historical work remains valuable for its scientific structure:
fair-opportunity-volume × modal-speed cells, a precision-oriented 1:3 control ratio,
1:1 invariance, common-support reporting, and repeated valid-control rematching. Its
HTTP implementation is superseded by the current documented contract.

## Treatment universe

The acquisition treatment is intentionally broad: any chooser with at least one
canonical kind draw anywhere in the certified Stage 07 panel. This protects downstream
options. The chooser summary separately records:

- any-state kindness;
- fair-state kindness (`engine evaluation >= -100`);
- clearly-worse-state kindness (`engine evaluation <= -300`); and
- excluded-middle kindness.

Unlike the old fair-only aggregation code, no kind chooser is dropped solely because
they have zero fair opportunities. Such users enter the `00` fair-opportunity bin.
Downstream main specifications can recover the historical `fair_opps >= 1` or common
support `fair_opps in [2,20]` samples without another API acquisition.

## Matching

The cell is the cross-product of:

- fair-opportunity count: 0, 1, 2, 3, 4, 5–9, 10–20, 21–50, 51–100, or 101+; and
- modal normalized speed: ultra, bullet, blitz, rapid, classical/long, or any preserved
  unexpected category.

Modal-speed ties are resolved by descending count and then alphabetical normalized
speed. Kind and never-kind users receive independent SHA-256 ranks within their cells.
Controls are allocated without replacement in rounds: every kind user receives a
first control before any receives a second, and every supported user receives a second
before any receives a third. This maximizes nested 1:1 and 1:2 coverage in thin cells.

Every kind user remains in the acquisition universe even when their cell cannot supply
three controls. Exact 1:3 groups and thin cells are explicitly flagged, so the later
analysis can use exact-support estimates without silently changing the acquisition
universe.

## Query ordering

Matched groups are assigned a deterministic SHA-256 query order, with the kind user
and their controls adjacent. The order is unrelated to observed patron/profile data.
Canonical 300-ID API requests are nested inside sequential numbered 120,000-user
macro-batches. Both assignment manifests contain all `N` macro-batches. Work traverses
them ascending and home descending, so either machine retains complete failover
coverage.

An authenticated completion-ledger protocol, rather than a fixed midpoint split,
controls ownership. A client processes only one macro-batch per invocation, publishes
all completed request IDs plus complete/partial macro status, skips peer-completed or
peer-started work, and requires a refreshed peer ledger before beginning its next
macro. Exact request overlap is fail-closed. If both directions converge on one final
macro, work receives the online tie-break; home may take over only with an explicit
peer-offline acknowledgement. Thus redundancy does not create routine duplicate API
queries.

Within each client the fastest documented schedule is used: 26 serial requests per
rolling 10 minutes (7,800 users), at least 23.2 seconds between request starts, and at
most 400 requests/120,000 attempted users per rolling 24 hours. Retries count again.
The code does not implement deliberate rate-limit evasion.

## Snapshot and missingness

Every selected user is queried anew, including users in the old June 2026 snapshot.
This prevents early-sample users from being measured at one profile date and later
users at another by design. Because the quota requires multiple days, every user has
an exact query timestamp and batch identifier. Query order is deterministic and
treatment-balanced, allowing acquisition-time diagnostics.

An unreturned user is coded as `returned=false` with patron status missing. It is never
automatically classified as a non-patron. Final coverage is reported by treatment
role and matching cell.

## Losslessness and privacy

Exact response bytes are authoritative. Typed fields are conveniences, not a field
selection rule. The complete canonical JSON for every returned user and a recursive
key inventory protect against losing economically relevant information that was not
anticipated when the request was made.

Raw profile text and identifiers remain private during acquisition and analysis. The
later public-release process—not this acquisition—will determine anonymization,
suppression, and disclosure rules.

## Provenance

The planner authenticates the exact Stage 07 global success receipt with SHA-256
`8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`, the Stage 07
producer SHA-256 `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`, 24 monthly
panels, 47,587,020 unique games, and 669,503 kind draws before matching.

Each stage writes structured receipts, source and output hashes, software versions,
and explicit success states. Existing certified batches are immutable and verified
before resume.
