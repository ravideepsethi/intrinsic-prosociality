# Frozen A1 trajectory build v1.0.0

This is a data construction and weighted balance stage. It does not estimate a
new receipt effect, change A1 weights, update the IV, or select variables by
significance. Session histories and the same-row regression/sensitivity stage
remain separate work.

## Fixed frame and authority

Use the 2,110,400 complete-followup, supported A1 exposures from preparation
configuration `a2af1aed29e480099f74b4893aa0aabafcbb5a98c3c21f299547c9380869be9a`.
They contain the 993,762 primary conditional-choice rows. Targets do not depend
on whether the recipient later grants a draw. All 24 monthly target checkpoints
are authenticated, including the two months with no complete-followup targets.
The main sample is pool and not mutually adjacent in observed start order.
That is not a literal historical finish-time rematch certificate.

The reviewed preparation report SHA-256 is
`73a3cfdaccee4b182d45afb57134c8eebfbf7240ea99bc7247e82aee76fc0b47`.
The reviewed cache report SHA-256 is
`bfe21eed11b41351f0da127f678315ae336be5520fdd43e1862c17ddd642f51a`.
The cache report sampled 175 files and 4,800 game records without moves or clock
histories. Its producer explicitly contained moves=false and clocks=false.
This is evidence about retained sampled exports, not an exhaustive claim about
every file on the computer. Recovery uses new full-move exports for the fixed
frame; its own completed response cache is always reused.

## Recovery and missingness

Use POST /api/games/export/_ids with 300 or fewer IDs, NDJSON, moves=true,
clocks=true, and evals/opening/literate/pgnInJson=false. Each completed response
is saved as gzip before replay. Three passes request only IDs absent from prior
responses. One request is active at a time. Successful requests have no fixed
sleep. A 429 requires at least 60 seconds; honor a longer Retry-After. Transient
errors have bounded backoff. TLS certificates are verified. Use system roots
plus an already installed certifi bundle; no insecure override is available.

Only one API job should be active across the user's other Lichess processes.
This package has a lock against a second copy of itself; it cannot control an
unrelated downloader. Lichess's rules: https://lichess.org/page/api-tips .
Endpoint routing source: https://github.com/lichess-org/api/blob/master/doc/specs/lichess-api.yaml .

Every returned record must match the game ID, standard initial position,
variant, pool/rated status, active timeout, saved creation and last-move times,
and grant/claim result by the frozen player colors. Replay all legal SAN moves
and require the exact ply count and normalized final FEN. Earlier boards must
match the previously frozen before/after indices for the recipient's last two
moves. Dictionary account IDs are retained from the authenticated frame;
current API account names are not used to construct a new identity join.

Keep a row for every target, including nonreturns and replay failures. Missing
or malformed clock histories do not discard valid move trajectories. If more
than 5% of one batch fails replay, stop with a diagnostic report before
continuing the large fetch. This is a source-validation stop, not a rule for
selecting a statistical sample. It must be resolved from record validity, never
from an effect estimate.

## Engine and features

The full frame requests 8,068,072 before/after positions. Use the same Stockfish
18 binary as the pilot, SHA-256
`ae4c93fa9676ca7750d0714342fd8a5b1d018000fc6e0f6cedf112067b5ef374`.
Use 100,000 requested nodes, one engine thread, Hash=64 MB, up to ten workers.
Each search starts a new game with a standalone normalized FEN, consistent with
the preparation benchmark. An in-worker cache of 4,096 identical FEN/color
scores reuses exact results; output records retain their own game/row identities
and record whether a search was executed. No approximate board matching occurs.

Save recipient-perspective centipawns, mate distances, node counts, depths,
bound flags, and time per requested position. Terminal boards, bound-only
scores, and short searches are explicit. A mate score is never substituted by
an arbitrary finite number. Centipawn differences involving a mate/bounded
score stay missing. Short-budget raw scores are saved, and the balance table
uses only games where every requested position reached the budget for its CP
traits. Report this missingness; a future regression must use identical rows
before and after adding controls.

For each of the last two recipient moves, cp_change = cp_after - cp_before;
cp_loss = cp_before - cp_after. Keep signed differences rather than truncating
negative values. Also record last-capture distance, no-capture status, and
whether the recipient's last move was a capture. Preserve full raw API clocks
and selected post-move readings. They are labelled API units in this release;
no elapsed thinking time is inferred without auditing increment, first-move,
and lag conventions. No historical finish time is inferred from lastMoveAt.

## Interpretation

Compute weighted raw balance for the complete-followup frame and A1 primary
rows using their original ATT weights. Report observed and missing rows/weights
alongside group means and SMDs. Weights are not reestimated after missingness.
These contrasts precede regression adjustment and do not establish random
receipt. The features are pre-receipt but post-opponent-assignment; they may be
used as A1 controls and labelled IV sensitivities, not added silently to the
primary IV. No variable list is chosen from treatment-effect estimates here.
