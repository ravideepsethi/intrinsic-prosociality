# Recovery result review — 28 September 2026 (Toronto)

The numerical recovery succeeded. All ten matched-receipt model fits and all three primary-IV specifications are complete. The repetition analysis did not run because recovery of one chronology row stopped at `RECOVERY_INVALID_GAME_KEY`.

The reviewed archive is `KAC_COMPANION_RECOVERY_RESULT_740c76ad339f76e4.zip`, SHA256 `6487a14768913ccec843f97c370172804d533e58b6d41dbd6cc44ba1e710ef03`. Its checksum matches the supplied companion file. The 31 entries in the two stage completion receipts match their stored byte counts and hashes. The executed package manifest matches the delivered v1.0.2 package. Four earlier fits were preserved; nine additional fits completed.

## Receipt estimates

All estimates and intervals below are in percentage points. Standard errors in this table cluster on the account that made the exposure decision, as in the original matched design.

| Outcome | Baseline | Exposure start-hour FE | Exposure last-move-hour FE |
|---|---|---|---|
| Grant at first later competitive choice, conditional on reaching one | 0.882 [0.642, 1.122] | 0.854 [0.647, 1.061] | 0.820 [0.614, 1.026] |
| Reach a competitive choice within 90 days | −0.197 [−0.578, 0.183] | −0.224 [−0.577, 0.130] | −0.215 [−0.568, 0.138] |
| Grant at first later choice, no later choice coded zero | 0.399 [0.286, 0.512] | 0.392 [0.287, 0.498] | 0.386 [0.281, 0.492] |

The conditional models use the same 993,762 exposures and 644,491 exposure-chooser clusters. The other outcomes use the same 2,110,400 complete-follow-up exposures and 1,052,419 exposure-chooser clusters. Row-set hashes are unchanged across specifications within each sample.

For the conditional last-move-hour model, the estimate is 0.820355 and the original clustered SE is 0.105152. The sensitivity SE allowing dependence through either the exposure chooser or exposure hour is 0.125293, giving a normal 95% interval of approximately [0.575, 1.066]. The positive association therefore survives this additional covariance check as well.

The tenth matched model additionally controls for the later choice's last-move hour. Its estimate is 0.839 [0.654, 1.025], SE 0.094811. This is a **post-exposure adjustment** and belongs in a sensitivity discussion, not as the primary identification design.

The conditional point estimate falls by about 0.0613 points from baseline to the exposure last-move-hour model. This is a specification comparison; no joint test of that coefficient difference was supplied, and it is not an estimate of the fraction caused by connectivity incidents.

## Primary IV

| Specification | 2SLS estimate | SE | Wald 95% interval |
|---|---:|---:|---|
| Baseline | 0.294953 | 0.127399 | [0.045256, 0.544649] |
| Exposure start-hour FE | 0.293455 | 0.126777 | [0.044977, 0.541932] |
| Exposure last-move-hour FE | 0.294394 | 0.126835 | [0.045802, 0.542987] |

All three use the same 2,682,330 exposures, row-set hash, original controls and shared-account-or-exposure-date CR0 covariance. The last-move-hour Anderson–Rubin interval is [0.044393, 0.543538]. The first stage is 6.91194 percentage points per reference-score standard deviation and the reduced form is 0.0203484 points per standard deviation.

The instrument's exclusion restriction remains unverified. Exact-hour adjustment does not change that. The matched conditional outcome and the IV outcome use different cohorts and denominators, so their coefficient magnitudes should not be compared as two estimates of an identical quantity.

## Numerical checks

The new fits use rectangular LSMR to absorb fixed effects. The stored diagnostics verify the original weighted orthogonality condition for every original fixed-effect level. They record zero dropped rows and zero ridge penalty.

- Matched fits: tolerance 1e−10; maximum observed residual group mean at most 7.771e−11.
- IV last-move-hour fit: scale-adjusted original tolerance 1.305214e−8; maximum residual group mean 3.634518e−9.
- The slow IV fit needed up to 10,500 solver iterations per column. Its success follows the numerical criterion, not merely an exit code.
- Matched work logged roughly 20 minutes from its first visible heartbeat; the IV last-move-hour fit logged roughly 25 minutes. These timings do not estimate history reconstruction runtime.

These are checks of the stored execution outputs. The full underlying observations are on the user's external drive, so this review does not independently re-estimate the models.

## What this resolves in the manuscript

| Requested analysis | Current status |
|---|---|
| Section 3.2, responsibility/rage-quitting proxies | Previously completed in the separate repaired A2 result. The blunder association within competitive positions contradicts the proposed claim that blame is absent there. Revise that interpretation. |
| Arena position gradient | Core comparison previously completed: arena × competitive is −0.881855 pp, SE 0.029947, 95% CI [−0.940550, −0.823160]. It does not identify a causal intensity effect. |
| Within-account repetition | Blocked by one affected chronology row. No repetition coefficients have been produced. |
| Ordinary loss versus receiving a draw | Still open. The canonical chronology lacks ending type and verified game-completion time; a start-ordered preceding result alone is insufficient. |
| Connectivity adjustment | Exact exposure-hour receipt and IV checks are now complete. The proposed platform timeout-share control, exclusion of high-incident hours, and incident-adjusted temporal-concentration benchmark remain open. |

Suggested statement for the receipt discussion:

> The receipt association is similar after adding fixed effects for the UTC hour in which the exposure game began (0.85 percentage points, standard error 0.11) or its last recorded move occurred (0.82 points, standard error 0.11), on the same observations. These checks absorb common exposure-hour differences; they do not establish that receiving a draw caused later granting. Last-move time is a proxy for the timing of the disconnection decision. The platform-wide incident-share and temporal-concentration adjustments remain pending.

Do not describe every connectivity analysis as complete, and do not state that the hour checks rule out all common shocks. They do not identify the claim-click time, individual connectivity conditions, or all shocks shared across exposure and later-choice times.

## Remaining timestamp blocker

The audit found 322 invalid timestamp rows in the June 2023 bullet chronology: 321 null timestamps and one zero. Exactly one invalid row involves an analysis chooser. The exported report does not identify whether that particular row is null or zero, nor does it reveal the malformed key. The public API request was stopped by key validation before it was sent.

The new diagnostic checks the existing private cached rows, the source Parquet, and the producer-declared upstream numeric partition when available. It exports only structural key information and aggregate agreement checks. It applies no repair and does not remove the affected chooser. The historical manifest already recorded a minimum timestamp of zero, so a zero alone does not establish recent corruption.

The requested exclusion of the author's accounts remains a separate sample amendment. These recovered models retain the frozen baseline sample and should not be labeled as having applied that exclusion.
