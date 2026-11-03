CLOSING AUDIT — NOVEMBER 2, 2026

No additional affected output was found in the requested sentinel audit.
No private-data analysis was rerun for this delivery. The already completed
conditional-censor repair is retained: N 314,639 -> 625,066; coefficient
1.025175 -> 1.121584 percentage points; SE 0.213562 -> 0.159006.

NULL_SENTINEL_AUDIT.csv gives a separate status and code/result evidence for
every requested path and related receipt consumers. It distinguishes an actual
returned null count from a source-code guarantee; this is not represented as
a newly executed census of private Parquet nulls.

* November 1 Panel B zero-coded censored row: nulls are handled; unchanged
  0.315239 (0.047324), N=2,112,426. Its original implementation already checked
  that a next-disconnection timestamp was both finite and positive.
* Any grant within 90 days: nulls are handled; unchanged 0.470102 (0.071504),
  N=2,112,426. Reach: unchanged -0.204189 (0.194045) on the same denominator.
  SQL fills absent Boolean events with FALSE and absent event counts with zero.
* IV future choices/intervening events: nulls are handled. Missing-choice -1
  timestamps are protected by reached=False. SQL LEAD NULLs remain NULL.
  The 3,374,164 diagnostic counts next retained exposures before the outcome
  game; it is not a count of every intervening receipt. Neither main IV design
  censors intervening receipts. Spacing does not use a nullable future timestamp;
  it uses the prior admitted exposure anchor plus the gap. Counts remain
  9,736,412 primary exposures and 3,103,311 in the spaced design.
* Reputation previous_meeting: nulls are handled in the chronology producer.
  Prior-pair counts have no nulls by construction (integer rank differences);
  zero is the correct empty-window count. The original factual-cache code was
  checked against the adopted producer and is byte-identical.
* Patron lags: nulls are handled. Returned profiles must have a valid query
  timestamp; other profiles are excluded from SQL lag aggregation. The minimum,
  median and maximum remain 382.073976, 654.796880 and 939.880533 days.

APPENDIX C

APPENDIX_C_VALIDATION.txt contains exactly the two requested sentences.
CLAIM_ERROR_BY_RD.csv contains the corrected claim errors and denominators.
The error sign throughout this delivery is predicted minus recorded.

The high-RD claim bins are exactly reusable, not approximations. The author-free
cost report's original-layer claim count is 40,943,232, exactly matching the
November 2 corrected-frame validation. The material-rule audit reports zero
claimed-win conflicts. Thus the corrected claim frame is the original claim
frame minus 41 author claims. Its RD>110 eligible and paired counts are identical
to the original high-RD bins, so none of those high-RD claims was removed.
Their weighted signed and absolute errors reproduce the author-free high-RD
aggregate. The RD<=110 bin is the difference between corrected pooled sums and
those high-RD sums. Pooling the lower bins avoids assuming where the 41 removed
claims fell. No model or replay is needed to obtain these three exact bins.

The phrase "about -2 points" belongs to the separate all-rated player-update
diagnostic: RD>=200 signed errors are -2.111976 before the change and -2.127770
after it. It does not describe the paper's claimed-win errors. The post-panel
comparison uses November 1, 2025 through January 2026, both colors and all rated
outcomes, excluding the November 18 07:15–07:22 UTC transition bracket.
POST_CHANGE_VALIDATION.csv reproduces every RD-bin aggregate. The reported
0.334/0.338 and 4.83/4.90 comparisons are verified; these aggregate comparisons
alone do not establish equality within every finer speed/color/outcome cell.

INTEGRITY AND RECONCILIATION

checksums.txt is the single consolidated SHA-256 file: 46 source/result/code
package archives, plus this delivery's payload files. PACKAGE_INDEX.csv records
the role of each archive, including the superseded successful censor return.
The package hashes cover vendored dependencies. Audience executed code is
embedded in its returned archive. The inventory covers the authenticated
November 1 paper source families plus the completed November 2 supplements,
repair and validation sources; unused proposals and failed runs are excluded.
All 800 files in the archived paper source manifest were checked against their
recorded hashes. PAPER_SOURCE_COVERAGE.csv records each check. This verifies the
delivered report/code bytes; it does not claim a new hash pass over private data.

RECONCILIATION.csv contains the requested single censor-repair row, including
unrounded estimates, standard errors, restored observations and sample hashes.
The other results are not replaced by hypothetical re-estimates.

Optional local verification (standard library only):
    python verify_closing_results.py
To check your original archives too, supply the folder containing their exact
basenames as listed in PACKAGE_INDEX.csv:
    python verify_closing_results.py --packages-dir /path/to/package/zips

test_sentinels.py records 13 passing synthetic checks of the archived function
bodies and SQL rules (NumPy, PyArrow and DuckDB). It runs no private-data model.
No figures were created and no manuscript or PDF was edited.
