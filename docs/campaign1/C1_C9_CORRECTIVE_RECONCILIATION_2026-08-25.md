# Campaign 1 C1/C9 corrective reconciliation

Date: 2026-08-25  
Status: post-outcome technical correction and serialization recovery  
Scope: Campaign 1 C1 and C9 only

This is not a preregistration. It is a complete technical record of a result-code
semantic error discovered after C1 outcomes had been seen, plus a serialization-only
recovery of C9 after its scientific computation had completed. The governing
post-outcome statement is
`dynamics_paper2_campaign1_v1_0_5_postoutcome_correction.md`. Scientifically useful
analyses are not being held for a later wave; any new outcome-informed analysis is to
be retained and labeled exploratory.

## 1. Physical result-code decision

The exact physical chronology file inspected was:

`speed=blitz/month=2024-10/part-00000.parquet`

Its 44,144,371 rows had complete raw support `{0, 1, 2}`:

| Raw value | Rows | Physical meaning | White-signed value |
|---:|---:|---|---:|
| 0 | 20,340,159 | Black win | -1 |
| 1 | 1,916,130 | Draw | 0 |
| 2 | 21,888,082 | White win | +1 |

Row conservation passed and there were zero null `result_code` values. The historical
chronology producer independently contains the same PGN-to-raw mapping. For a Black
chooser the White-signed value must then be negated.

Authenticated evidence:

- physical-decider text SHA-256:
  `299cd137b96acf1ac5d3051be6b17dba8028a0bce2b76fdbef2dfc8b62e27b11`
- physical-decider JSON SHA-256:
  `f5cfb8836f1425a7083f55a41934a843fd143a15fbca9ff59bd6661a4385b7b2`
- historical producer SHA-256:
  `02a14d3de5ef7fadf59909b703ad481ca23625fea39c43a5d09cdc86cfbc4458`
- Campaign 1 detailed handoff SHA-256:
  `a0ad057d122606a40fec659a0239020f7a14884a4081306ffe55f2315f43b32a`

## 2. C1 invalidation and authorized correction

Both exposed C1 lineages treated the stored value as if it were already signed.
Consequently neither estimate is scientifically interpretable:

- Run A/audit lineage: approximately +0.245 percentage points; invalid.
- Run B/production lineage: -0.831712536 percentage points; invalid.

The invalidity is semantic, not a choice between the two estimates. Run B also showed
the diagnostic consequences of the bad bridge: 217,589 primary lag rows resolved,
108,543 later regressed, and only two direct loss/win streak candidates appeared among
112,725 resolved lag triples.

The corrected runner performs exactly one new C1 build under a new output root and:

1. re-authenticates the physical file and reproduces the exact 0/1/2 counts;
2. decodes `2 -> +1`, `1 -> 0`, `0 -> -1` in White perspective and negates for Black;
3. retains raw code, White-signed result, chooser-signed result, and chooser rating
   difference in the bridge;
4. requires exact raw support `{0,1,2}` and chooser support `{-1,0,+1}`;
5. requires at least 99% bridge resolution for 15-, 30-, 60-minute and streak inputs;
6. requires at least 90% complete-case preservation for every primary window;
7. requires at least 99% sign alignment between decisive chooser outcomes and the
   independently stored chooser rating-difference direction;
8. requires plausible decoded marginals: each decisive share in `(0.30, 0.65)` and
   draw share in `(0.005, 0.20)`;
9. requires at least 1,000 direct three-game streak candidates and at least 250 per
   loss/win arm before attempting the prespecified secondary; and
10. inventories prior C1 result trees by coefficient fingerprint, rejects an unknown
    lineage, and refuses any second successful corrected-v1.0.5 build.

Rating difference is validation-only; it is not used to construct the corrected result.
The frozen production user sample and the original C1 model family remain unchanged.
The invalid Run A/Run B estimates are excluded from interpretation and multiplicity.

Corrected C1 runner SHA-256:
`9154a6c49ba0ae61561926d00feeb118fd1c6d9ffde0c96b27db87b4ccf53585`

## 3. C9 serialization-only recovery

The original C9 run completed all 4,999 conditional randomizations across 20
authenticated checkpoint batches and passed exact B2 reproduction. Publication then
failed because the first CSV row lacked three keys present only on the primary row:
`epistemic_label`, `holm_adjusted_p_value`, and `interpretation`.

The recovery runner does not create a new scientific draw. It:

1. authenticates the existing session cache, private configuration, and every one of
   the 20 existing checkpoint/receipt pairs;
2. fails on any missing or mismatched batch, with no missing-batch recomputation branch;
3. combines the same 4,999 saved randomizations;
4. reruns exact B2 reproduction;
5. constructs one explicit uniform component-row schema before CSV writing; and
6. publishes aggregate-only results under a new public root with
   `new_randomizations_drawn = 0` recorded in the receipt.

The failed run's exact-B2 reproduction artifact has SHA-256
`d7e9661aa55aba7eabc151099401afa37a6641994f421c44f75319701cc49074`.
The failed-run diagnostic has SHA-256
`c1bccdb1347d2e2d2edc4c65499af2f03107ad65a4c78681193153e04ad845f8`.

Recovery C9 runner SHA-256:
`83fbbdc71e425bae6337d7fc3ee7115c4ff4daf071360fcea0229e09f84dcdd9`

## 4. Supporting source lineage

- uploaded corrective source bundle SHA-256:
  `c64bb63251ee36c0741f1372aef4fb04472de20ed75c04ddec157ccee56b28f1`
- all 84 entries in its internal manifest authenticated before use;
- collected C1 v1.0.2 production package SHA-256:
  `297e574bc24e8f25164d25550eadc55a2a5dfffdabc42ab5d64c9842f410da5d`
- collected C9 r1 production package SHA-256:
  `a2c2048d5329fc883ead00147ed2a00bb00b1380dfad7a5db50da44a0be0e5ba`
- inherited Wave 1 common module SHA-256:
  `23388353e546f34b1a8c23fad9b10bfc42fbc7850a79c41108ddd3c0821efce2`
- locked replication Git authority:
  `46abb7409621e98c74dc8aa3eb3b3885a644080d`

## 5. Verification completed before packaging

The following checks passed in the construction environment:

- Python byte-compilation for all four packaged Python programs;
- C1 pure decoder truth-table test, including rejection of an out-of-support code;
- C9 uniform-schema/CSV regression self-test;
- authentication of all packaged C1 and C9 evidence objects;
- shell syntax validation of the combined launcher;
- C1 prior-output fingerprint scan against the collected public Run B evidence; and
- an end-to-end synthetic test of result copying, inspection, private-suffix rejection
  logic, manifest creation, ZIP creation, and zero-new-randomization reporting.

DuckDB is not installed in the construction container, so the C1 SQL decoder self-test
could not execute there. The launcher refuses a production interpreter without DuckDB
and reruns the SQL self-test on the data machine before C1 begins. The full production
run cannot be executed in this container because the multi-terabyte locked chronology
and private analysis inputs remain on the authorized external volume.

Collector SHA-256:
`dd4bcda9336a47d3767e97fc556e76f44ebd6970e74f241d06feffaa5117ff84`

Post-outcome correction document SHA-256:
`14cb718408788ea15f94d555eaabc84c27f2dc42b1ca85c03b46daf43e366787`

## 6. Next decision point

The corrected C1 and recovered C9 outputs must be interpreted immediately after the
authenticated aggregate result bundle is returned. Holm adjustment remains pending
until the other effective-plan family members are available; no invalid C1 estimate is
entered into that family.
