# Counterfactual cost computation and historical source limitations

## Estimand

The immediate cost is the chooser's post-update rating under claiming minus
that under granting a draw, conditional on the same recovered pre-update
state. The opponent's benefit is its draw rating minus its loss rating.
There is no simulation of future games or future rating consequences.

For the usual Lichess game update, RD has already been inflated for elapsed
time. `skipDeviationIncrease=True` prevents adding another period at the focal
game. With g = (1 + 3 phi_j^2/pi^2)^(-1/2), E the expected score, and
v = [g^2 E(1-E)]^(-1), the post-update variance is
phi_prime^2 = [phi^(-2) + v^(-1)]^(-1). The common unregulated scale is
K = 173.7178 g phi_prime^2. The core win/draw premium equals K/2 exactly.
Volatility is reconstructed and used in the history; it does not alter the
immediate scale in this branch.

The code first reproduces the existing stored draw, win and premium values
from both players' saved RDs and rating anchors. It also checks each side's
stored realized prediction, role orientation, material, result and missingness
flags. The tolerance is 1e-7 rating points. No parameter is chosen to minimize
error against the realized update of an individual game.

## Regulation and bounds

The documented gain multiplier is 1.005 for blitz, 1.015 for bullet/rapid/
classical, and 1.013 for ultrabullet. The pre-refactor updater did not invoke
the regulator for ultrabullet. Correspondence has no multiplier. The main
sample is expected to have no ultrabullet rows; categories are still explicit.

The regulation map is h(d) = f*d for d>0 and h(d)=d otherwise. If no bounds or
bot adjustment bind, the revised cost is h(K(1-E))-h(K(0.5-E)). This can differ
from K/2 without any outcome-dependent update scale.

The historical human/bot adjustment halves a human's update against a bot.
Both known flags are used when supplied. With no map, or absent accounts, the
candidate assumes unknown accounts are human and records that uncertainty.
It is not described as an exact platform cost for unknown bot-status rows.

The old operation order is change cap (+/-700), sanity check/reset, rating
floor (400), human/bot adjustment, positive-gain regulation. The newer order
is regulation, human/bot adjustment, change cap, sanity check/reset, floor.
The reset branch sets the rating to 1500 when the bounded pre-floor rating is
outside (0,4000). Cached RD/volatility ranges and the update equations satisfy
the other sanity checks in the ordinary branch. Reset cases are counted and
excluded from the regular cost comparison. The operation-order transition
uses a source refactor timestamp, explicitly not a certified deployment date.

## Unknown historical settings

Commit c06b59cde5b2b763368267e203225c6954e5ba2f (2025-04-17 06:42:35Z)
replaced the runtime `ratingFactor` SettingStore with fixed constants.
The prior source default was an empty map, which does not disclose the live
database's values. The hardcoded values cannot establish earlier live settings.
The default candidate carries them backward as an explicit hypothesis. A
user-supplied, evidence-backed calendar can replace it. Neither monthly fit nor
good validation by itself identifies the exact historical configuration.

Source commit dates also need not equal deployment dates. The report separates
the runtime-setting era, the later hardcoded-source era, and monthly results.
Historical sources and the hardcoding diff are included in `sources/`.

## November 2024 source refactor

The November 20, 2024 source snapshot (fc1040f756e350740edabe51abbb439d23dd9f74)
called `computeGame` without the skip flag. Earlier November 19 commits were
work in progress; their production deployment is not established.
Commit 33b011622c6665ec0495c016c8d4b48035dfae24 (November 22 at 09:08:03Z)
restored `skipDeviationIncrease=true`. These commits do not establish whether
or exactly when the intermediate branch ran in production.

The primary candidate keeps the cached no-extra-period core. A separately
labelled sensitivity uses the additional-period branch for completion times
from 2024-11-20 10:24:14Z through 2024-11-22 09:08:03Z. For each potential
outcome, it solves the volatility equation separately, uses the un-clamped
working volatility in the added-period RD step, then applies the platform
operations. It uses the same cached pre-state in both arms. It does not rebuild
possible downstream historical-state effects of that temporary branch.
The report also provides a comparison excluding the entire November 2024 month.

## Meaningful choice, display and validation

The project's `chooser_has_mating_material` is a locked historical screen:
pawn/rook/queen, two bishops, bishop plus knight, or two knights. It is not
identical to Lichess's side-specific insufficient-material predicate. In
particular, the platform can allow a lone bishop or knight to win depending
on the opponent's pieces, and bishop-only positions depend on square colors.
Version 1.0.0 incorrectly required this historical flag for every recorded win
and used it to assign zero action costs. Version 1.0.1 corrects both errors.

The correction implements `InsufficientMatingMaterial.apply(board, color)`
from the bundled scalachess 2023 and 2025 source snapshots. Both have the same
three branches: king alone; king plus exactly one knight against king/queens
only; bishops only with no bishops on opposite square colors anywhere on the
board and no opposing knights or pawns. Those branches mean insufficient
material. Cached piece counts cover the usual cases; FEN is parsed only when
bishop-square colors are necessary. The historical screen is independently
reproduced from the counts. Neither result nor observed rating change enters
the material predicate. The pinned Lila claim handler uses this predicate.

If the platform predicate rules out a win, the feasible cost is zero provided
the observed outcome does not contradict that rule. A recorded chooser win
in such a position is retained and flagged `material_result_conflict`; its
action cost, claim-action payoff and opponent benefit are NULL, not zero.
Hypothetical draw/win rating changes and their difference remain available,
and its observed win is still validated. Positive-cost summaries require
`analysis_eligible_cost`: platform mating capacity and no sanity reset or
material-result conflict. Conflicts do not halt the numerical audit.

The original `kind_draw` stays unchanged. `kind_draw_platform_rule` is a
separate candidate; the report counts added/removed draws and provides a
month/speed/result/material cross-tab. Nothing silently relabels the paper's
behavioral outcome or changes the retained main-panel rows.

The public PGN records integer ratings, while the server carries fractional
ratings. This reconstruction anchors to the recorded ratings. Costs are kept
continuous. The floor/ceil display bracket is conditional on the predicted
continuous change and an unknown common fractional offset; it is not a bound
on the true server update after state-reconstruction error. No rounded-change
exact-match claim is made. Missing observed updates remain missing; observed
zeros remain valid observations.

Validation includes both observed primary arms, with paired changes in MAE on
identical rows. It cannot directly validate the unchosen outcome or their
difference. The diagnostic slope of observed on predicted positive changes
selects on predictions (1 to 50), never observed signs, and is never used to
fit any candidate cost. No iid standard errors or causal price claims are made.

The primary inclusion rules match the earlier `Pool_Rating_Validation_v1_0_0`:
stored kind draws and ALL PGN/API-confirmed chooser wins, without a material
restriction on the wins. The byte-identical earlier validation code is bundled
and its actual `consume` function is executed in a regression test to verify
identical primary sample counts and original-formula errors on the same rows.
Historical published counts can differ here because this run excludes both
author accounts. All raw draws, draws failing the historical screen, the new
platform-material draw subset and unusual chooser losses are supplemental
series, which overlap and must not be added as independent observations.

## Sample, computation and downstream use

The author-free main sample is 41,534,289 opportunities. Both named author
accounts are excluded in either player role before aggregation. Factual
rating histories are preserved. This code uses no behavioral donor aggregate.

Monthly tasks stream Arrow batches and write compressed Parquet sidecars.
Independent months run in separate spawned processes. Exact global quantiles
and game-ID uniqueness are checked with a memory-limited DuckDB query after
the workers finish. Full input hashes, package hashes, output hashes and the
per-month ordered game-ID digests bind the computation. Corrupt checkpoints
stop rather than silently being reused.

The final status certifies completion of this audit, not historical server
state recovery or unchanged manuscript regression results. Any adopted cost
definition must be joined by the manifest's month/game_id key, and affected
models and paper tables must then be re-estimated under a new result identity.
