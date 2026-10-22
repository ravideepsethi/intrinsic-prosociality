# A3 local sources v1.0.1 — path repair and continuation

30 September 2026 UTC / 29 September in Toronto.

## Repair in v1.0.1

The v1.0.0 launch stopped in its synthetic self-tests, before the production continuation ran. This was a code bug: the inventory resolved its scan roots but compared them with an unresolved project path. When the temporary directory has an alias, such as macOS `/var/...` pointing into `/private/var/...`, the inventory labeled an internal file with its absolute path instead of `output/tournament_records.parquet`. The test then raised `StopIteration` despite finding the file.

This release canonicalizes the project and scan roots before comparing them. All four original tests remain, and a fifth tests an explicit project alias, an external source alias, stable family labels, and deduplication of overlapping roots. The original failure was reproduced on Linux through a symlink alias; the repaired suite was checked both with ordinary temporary directories and with all test projects under an aliased temporary root. macOS itself has not been run here.

The completed readiness cache identity, author restriction, support calculations, source sampling and worker settings are preserved. The existing `kac_a3_local_sources_v100` output/work namespace and lock are also retained for compatibility; the package manifest distinguishes this repaired release. No deletion, dependency installation or manual bypass of the tests is needed.

## Previously completed readiness result

The first audit **succeeded in 26.46 seconds** with 10 workers. Its ZIP matches the supplied SHA-256, all 11 manifest-covered files verify, its executed package identity matches the delivered code, and the monthly counts reconcile with the exported coverage Parquet. There were no monthly failures, API requests or engine runs.

## What it established

| Quantity | Verified result |
|---|---:|
| Original screened arena opportunities | 1,892,835 |
| Author-involving games removed | 1 |
| Retained opportunities | 1,892,834 |
| Retained opportunities with explicit tournament IDs | 1,892,834 (100%) |
| Distinct tournaments | 363,654 |
| Conflicting tournament headers | 0 |
| Competitive opportunities after ply 10 | 569,107 |
| Clearly-losing opportunities after ply 10 | 987,320 |
| Chooser–tournament cells, all states/stages | 1,840,428 |
| Cells with multiple observed decisions | 50,672 |
| Opportunities in those repeat cells | 103,078 (5.45%) |

Every tournament ID came from an explicit Event-header URL. None was inferred from the Site game ID. Starts and last-move proxies are nonmissing, but that does not turn lastMoveAt into a certified resolution/completion timestamp.

The author restriction removed one opportunity in January 2025. This audit applied exact matching in both roles. It did not refresh earlier arena estimates, and the separate project-wide author-exclusion ready manifest was absent at its expected location. Do not describe the whole paper as refreshed under that restriction.

The all-state, all-stage repeat-cell support is the relevant warning for chooser-by-tournament fixed effects: singleton cells have no identifying variation after their cell effect is removed. The 103,078 rows are only an **upper bound on the rows that could inform such a comparison**; measured cost must also vary, and the primary competitive/late-game restriction can shrink support further. There are 52,406 within-cell dimensions before other controls across all states and stages. Neither count supplies a minimum detectable effect by itself.

The 24 original Parquets consistently lack title and berserk fields, tournament scores/streaks and certified completion timestamps. Their fields containing `score` are engine-evaluation fields. These are not tournament scores. Complete tournament histories cannot be reconstructed from disconnect opportunities alone.

## What the first audit did not establish

Its broad file inventory stopped after 40,001 entries and found no candidate assets before that point. That component was too broad and used a shared limit. **Zero candidates is not evidence that no local histories or raw responses exist.** The completed tournament-ID and sample checks remain valid.

This continuation fixes the inventory and calculates state-specific repeat-cell support. It reuses the completed monthly projections; it does not repeat the 1.89-million-row source construction or invalidate its caches.

## Run

**Expected runtime: 1–5 minutes; allow 10 minutes if directory enumeration or the SSD is busy.** The estimate is for metadata and bounded header inspection; no raw archive is fully decompressed. Cached projection authentication and support calculations should be quick. The source catalogue's runtime depends on the number of local files.

It uses up to 10 workers for hashing and source inspection, with up to 10 DuckDB threads for the separate support aggregation. It requires only your existing DuckDB and PyArrow environment; no SciPy or pandas is needed. It makes no API requests and can run alongside the IV download.

After placing the ZIP in `~/Desktop/Lichess_Desktop`:

```bash
bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
A3_LOCAL_STAGE="$(mktemp -d "$PWD/kac_a3_local_sources_v101.XXXXXX")"
ditto -x -k "KAC_A3_Local_Sources_v1_0_1.zip" "$A3_LOCAL_STAGE"
bash "$A3_LOCAL_STAGE/KAC_A3_Local_Sources_v1_0_1/RUN_A3_LOCAL_SOURCES.command"
BASH
```

Return `KAC_A3_LOCAL_SOURCES_RESULT_<timestamp>.zip`, written to that Desktop folder. The command runs five synthetic checks before reading production data. Completed old caches remain unchanged.

## What the continuation does

1. Finds the completed readiness cache by its reviewed build hash, original package identity and exact author policy. It verifies all 24 monthly projection hashes. It does not accept an arbitrary folder because its filename looks plausible.
2. Computes chooser–tournament support separately for all opportunities, competitive and losing opportunities, the post-ply-10 versions, and the pooled competitive/losing late sample. These overlapping populations are labeled separately, not added together. No grant outcomes enter.
3. Writes a private target list of tournaments containing repeated late competitive opportunities. This is preparation for assessing a manageable scoring-history pilot, not authorization or execution of a mass download.
4. Enumerates `derived`, `output` and `raw` without the earlier shared file-count cap. Work/temp directories, environment files and the A3 audit outputs themselves are excluded; errors and missing roots are reported. Explicitly supplied roots are resolved and deduplicated; symlinks encountered within the walk are not followed. An optional known legacy source folder can be added with `--extra-root '/absolute/path'`.
5. Inspects up to three deterministic representatives per filename family. For Parquets it reads footers and nested schemas, not game rows. For PGN/JSON files it reads at most 256 KiB per representative, including compressed prefixes. It records header/field names and aggregate metadata, not game or account values. Active files that change during inspection are marked unread/changed; collectors are not interrupted.

Filename families preserve month partitions while collapsing numbered shards, buckets and long hash names. Representative sampling is a way to discover existing producers, not certification that every file in a family has the same schema. JSON inspection records recognized structural keys only. A generic `score` field is a candidate to inspect, not automatically tournament points. Stockfish score columns are not classified as tournament scoring.

The portable report contains:

- `SUMMARY.json`: completion status and the exact reuse scope.
- `support_by_state.parquet` and `.csv`: repeat-cell support, before measured price and outcome modeling.
- `late_competitive_by_speed.*`: support by speed.
- `asset_families.parquet`: local file-family inventory.
- `representative_schemas.parquet`: sampled field/header evidence, including failed or changed files.
- `candidate_sources.json`: relevant source leads and the precise inspection scope.

Private account/game keys and tournament target lists remain on the Mac in `derived/replication/kac_a3_local_sources_v100_PRIVATE`. The older readiness directory is preserved.

## Implication for the analysis

Tournament identification is now resolved for this existing sample. The remaining obstacle is measuring the point cost at the choice: complete prior tournament games, actual berserk flags, tournament settings and deadlines, historical scoring rules, and validation against recorded tournament scores.

Recovering complete histories for all 363,654 tournaments immediately is premature. First inspect the local sources and primary-state repeat support, then test score reconstruction on a deterministic pilot. A price model should follow only once cost measurement and usable variation are established.

If chooser-by-tournament variation is insufficient, the additive chooser-plus-tournament model mentioned in the handoff uses a different source of identification. It should be labeled as such, not silently substituted and interpreted as the same comparison. Streaks and voluntary berserk remain selected states even with correct point measurement.

No arena price response has yet been estimated. This result neither supports nor rejects opportunity cost, reference-dependent payoff or deference, and it does not allocate shares among them. The useful progress is that we can reuse the sample and all tournament IDs rather than rebuilding the arena analysis.

## Validation

`VALIDATION.json` records the local tests and environment. Checks cover cache authentication/tampering, traversal across separate roots without early starvation, deterministic representative selection, nested-field detection, bounded PGN reads, exclusion of record values from the portable report, and a complete 24-month cached continuation with independently checked state-support counts.

Production data remain on the Mac; this continuation has been tested synthetically, not run against those private data here. No new historical source certification or behavioral estimate is implied by the tests.
