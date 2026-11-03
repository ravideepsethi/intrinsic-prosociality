# Expanded chooser-leniency IV: frozen analysis plan, v1.0.0

This follows review of the first-exposure IV and the repeated-exposure audit.
The earlier effects are known. This is a documented prospective freeze of the
new expanded analysis, not preregistration before the research began. All
specifications below are reported regardless of sign or significance.

## Primary population and outcome

Use the certified source=pool, observed-previous-nonadjacent 24-month main
panel. Fair-position exposures, grant-or-claim arms, real-time games, and
first observed undirected pairs are inherited from the verified audit.
First observed pair is not lifetime-stranger certification. Observed game
start adjacency is not a certified literal-rematch measure.

Retain the audit's lag-7, floor-5 support and greedy 90-day spacing flags.
These were chosen before the administrative follow-up cut and before the
new full prior-history cut. Do not recompute spacing after either cut.
Selected streams include early-history and incomplete-follow-up tails for
the subsequent risk-set calculation. Unsupported exposures do not start a
spacing interval. The accepted spacing stream uses prior selected anchors,
start/ordinal/game ordering, and no later kindness outcomes.

Require a complete [start-97 days,start-7 days) recorded-history window and
complete 90-day outcome follow-up. The primary exposure row count must be
2,682,330. Comparisons use 3,838,184 rows at 30-day spacing, 7,432,712 unspaced
rows, and 967,594 original first-recipient rows with complete prior history.
These counts are asserted before coefficients are estimated. Recount receipts,
reached decisions, unique outcome IDs, unique kind outcomes, and recipients on
each exact final row set. Incomplete follow-up is not coded as zero.

Y is the inherited first later fair main-sample choice against a different
opponent: its game must start strictly after focal lastMoveAt, and its recorded
decision must be within 90 days of that anchor. A complete window without a
qualifying decision has Y=0. The 90-day outcome remains the same under 30-day
spacing and under no spacing. Do not censor at the next exposure. Keep the
reach indicator separately. The anchor is a last-move proxy, not a recorded
claim click or certified finish time.

## Instrument, controls and estimand

Use the saved state-adjusted, pair-leave-all-out opponent grant rate, with at
least five prior decisions strictly before month start minus seven days.
The state reference excludes both participants' cross-fitting folds. Histories
remain all-source Stage07; narrowing the main sample does not erase history.
The input checks revalidate the original first-exposure identities, outcomes,
history counts and both lag-7/lag-30 scores. No new score is chosen by fit.

Primary: pooled, just-identified IV. Continuous controls are recipient displayed
rating; opponent-minus-recipient rating gap, its square and absolute value;
log(1+opponent prior decisions), log(1+prior counterparts), and the historical
expected grant rate. Add recipient fair-history availability, log(1+prior fair
choices), ever having granted, prior kind/fair rate, log(1+disconnections),
log(1+receipts), and log(1+claims), all from [start-97d,start-7d). Add
log(1+all-rated-standard games started in [start-30d,start)). This recent-volume
control is newly reconstructed for expanded exposures from the chronology.

A zero prior kind/fair rate with no prior opportunity is accompanied by the
availability indicator. It is not a measured unkind disposition. Controls use
within-sample centering/scaling. Required pregame ratings and historical
counts must be present and valid. Median imputation, with a missing indicator,
is inherited for any optional continuous control; missingness is reported.

Absorb month x exact time control x 100-point mean displayed-rating cells,
UTC exposure date, and hour of week, following the completed follow-up.
No final evaluation, ply, trajectory, clock-at-disconnect, or other
post-assignment game-state control enters these primary IV specifications.
Internal conduct categories and complete transient states remain unobserved.

Interpretation, if instrument assumptions hold: an instrument-weighted effect
of receipt at this exposure on the specified 90-day outcome, conditional on
the recorded history. It is not an unqualified population average effect.
Disjoint selected windows do not eliminate unselected intervening receipts,
carry-over, or feedback into future play. Pooled IV does not by itself resolve
selection into a fair disconnect. Recipient FE do not establish assignment.

## Prespecified model list

1. main90_pooled: primary, full 90-day sample with recipient history controls.
2. main90_repeat_pooled: same model, only recipients with >=2 selected rows.
3. main90_repeat_FE_diagnostic: add recipient FE to exactly the rows in (2).
4. sensitivity30_pooled: 30-day spacing, same controls and 90-day outcome.
5. sensitivity_all_pooled: unspaced supported exposures, same controls/outcome.
6. first97_common_controls: first-exposure reference with the same new controls.
7. main90_without_recipient_history: same rows as (1), omit recipient history
   and volume controls, to isolate the control change.
8. first97_without_recipient_history: same rows as (6), analogous bridge.

The original 1,071,174-row first-exposure result and previously reviewed
history follow-up are included as prior evidence. They are not relabelled as
models on expanded rows. Models (2)/(3) use a verified row-set hash. Membership
requires repeated observations, not observed treatment switching, outcome
switching, or a favorable amount of instrument variation. Singletons do not
provide recipient-FE information.

## Sampled all-ending denominator and selection checks

Reuse the 1,661,563 reconciled source=pool games from the existing independent
random game frame. Retain its original recipient orientation and all ending
types. This is a sampled all-ending denominator, NOT a census of every game
played by every recipient. The inherited frame has already been reconciled;
the new analysis must never reinterpret unreturned IDs as ordinary endings.
Do not restrict it to people who eventually enter the exposure sample.

Reconstruct/check recipient histories against the verified follow-up, adding
the missing claim count. Reuse its verified all-game recent volume and first
observed pair indicators. Require observed-previous nonadjacency, real-time
play, supported opponent score and a full prior-history window.

For the 90-/30-day risk flags, a selected prior exposure closes the current
window only once its recorded anchor is strictly before the current game's
start. Reopen strictly after that anchor plus the gap. Use the full selected
stream, including rows subsequently dropped for prior-history or follow-up
coverage. People without any earlier selected exposure remain eligible.
Do not use future selected exposures, the current ending, current fairness,
current receipt, or the next exposure to construct the risk flag. Record
anchor ties and earlier-started exposures whose anchors have not yet occurred;
such future anchors do not enter the primary eligibility rule. These timing
flags document the remaining last-move/recorded-start limitation. We do not
claim actual disconnect/decision times are observed.

Use start+90 days < panel end as the pregame calendar-support cut for entry
tests. This avoids selecting denominator rows using current ending time.
Then test two distinct inclusion outcomes: selected exposure before the
administrative follow-up cut, and selected exposure in the final complete-
follow-up analysis. Earlier-started overlapping games may influence the
audit's inherited selection rule; the final inclusion outcome measures that
algorithm as implemented, not an idealized physical disconnect hazard.

The primary entry association is analysis_entry_90 on opponent leniency with
the common primary controls. Also report any active timeout, recipient-side
main disconnect, and recipient-side fair-arm event. Do not condition the
denominator on current fairness or timeout status. Repeat pooled entry tests
for 30-day and unspaced eligibility. Report a no-recipient-history model on the
same 90-day risk rows, then a matched-row pooled/recipient-FE diagnostic on
people with >=2 eligible games IN THIS SAMPLED DENOMINATOR. Do not borrow a
repeat-recipient flag from the exposure outcome sample.

An ordinary-game placebo uses the same 90-day risk population with the inherited
mate/resign/stalemate ending restriction and complete anchor-based follow-up.
Its outcome comes from the independently constructed future choice. Conditioning
on an ordinary ending can itself select; this is supporting diagnostic evidence,
not a proof of exclusion. Its target differs from the IV exposure population.

## Balance and inference

Report balance on recipient aggregate and recent behavior for main90 with and
without recipient-history controls, and for the FE diagnostic. The recent
counts use [start-37d,start-7d). Directly controlled traits are explicitly marked
as not independent balance evidence. Preserve absent-history availability.
Report individual and joint tests, plus Holm adjustments within each balance
family. No nonrejection is labelled proof of random assignment.

Use the inherited shared-account OR exposure-date CR0 formula: accounts count
in either role, subtract repeated undirected-pair contributions, and use the
account-date/pair-date inclusion-exclusion correction for common exposure
dates. This covers these exposure links, not every possible downstream
network link. Historical leniency scores are treated as fixed conditional
inputs; uncertainty in their estimation is not newly modelled here.

Report first stage, partial first-stage R2, reduced form, 2SLS, and same-row
OLS. All treatment-effect fields ending _pp are percentage points. RF and
selection _pp fields use the common reference score SD 0.059411690344000595.
No comparison is based on differently standardized score coefficients.

Wald intervals use asymptotic normal CR0 inference. Separately invert the
null-restricted moment z*(Y-beta*D) with the same covariance rule for a robust
score/Anderson-Rubin confidence set. This differs from the older package's
unrestricted-RF-residual approximation; label the method explicitly. Keep
unbounded/disconnected sets. Nonpositive or indefinite covariance results stay
unsupported; never replace them by absolute values or a positive-semidefinite
repair. Fewer than 2,000 model rows or fewer than ten events/nonevents for an
entry/placebo association is explicitly unsupported.

Holm-adjust the two primary diagnostic associations: final 90-day entry and
ordinary-game kindness. The main IV is a single declared primary for the new
extension, not a replacement selected after examining sensitivity results.
Whether the extension becomes central to the paper remains a substantive
decision after reading all results and their limitations.

## Computation and provenance

No Lichess API requests and no Stockfish searches. The remaining chronology
pass adds recent playing-volume controls. Use up to ten workers for history
and chronology tasks; large model fits run one at a time to control memory.
File-level time statistics may skip row groups outside all query windows;
skipped and processed rows must sum to the verified manifest total.

The main panel, historical projections, baseline analysis and completed
follow-up analysis are authenticated against recorded hashes. The audit's
public report did not publish its private analysis checksum. That private
file is checked against its own content-bound checkpoint receipt, its frozen
configuration, the publicly reviewed candidate counts, rederived spacing flags,
and the independently pinned first-exposure data. The inherited chronology
has manifest hashes and metadata/signature checks, not full-byte data hashes.

Write DESIGN_FREEZE.json before coefficient estimation. Use atomic,
configuration-bound checkpoints in a new output directory and a process lock.
Existing reports and data are read only. Only aggregate results, plans, hashes
and validation metadata enter the upload ZIP; game/account IDs remain local.
Local validation uses synthetic fixtures; the user's private data and actual
Mac runtime cannot be tested in the development workspace.
