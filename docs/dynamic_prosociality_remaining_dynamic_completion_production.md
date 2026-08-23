# Remaining dynamics completion: production record

## Canonical implementation

- Producer: `code/12_complete_remaining_dynamic_analyses.py`
- Synthetic integration test:
  `code/test_remaining_dynamic_completion_synthetic.py`
- Producer version: 1.0.0
- Producer SHA-256:
  `e7b302bae6c73e2f35d3b004c7206e8b2ff07fd77d49a63871f5d72d9467a73a`
- Test SHA-256:
  `64e69a0e09ef000d58382945dd28022468dc40c6b15824c4aec6b4603d0ca147`

## Production run

- Run ID: `20260823T141145Z`
- Certified Stage-07 rows: 47,587,020
- Threads: 8
- DuckDB memory limit: 16 GB
- Actual estimator runtime: 97.1 seconds
- Total authenticated wrapper runtime: 111 seconds
- Private account-window cache rows: 1,642,449

The producer scans the certified Stage-07 panel once and writes one projected,
Zstandard-compressed account-window Parquet. It does not rebuild the
7.7-billion-row chronology.

## Input authorities

| Authority | SHA-256 |
| --- | --- |
| Core code | `2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713` |
| Stage-07 success receipt | `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7` |
| Core-results success receipt | `bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009` |
| Private recipient input | `41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d` |

The private-cache authority is recorded in the aggregate input receipt without
publishing the cache itself.

## Public aggregate outputs

The repository directory
`results/remaining_dynamic_completion_v100/20260823T141145Z` contains:

- `_SUCCESS.json`;
- `summary.json`;
- `report_file_hashes.tsv`;
- the aggregate input-authority receipt;
- the A1 censoring diagnostic;
- A1 next-exposure censoring estimates;
- A1 later-exposure paths;
- A2 mercy-minus-claim differences; and
- A2 arm-specific pre/post paths.

All files are aggregate. No user name, user identifier, game identifier,
account-level row, profile response, API credential, or raw data is included.

## Safe rerunning

The producer defaults to a write-free authenticated plan and requires
`--execute` for estimation. A completed private cache may be reused only when
its configuration and content receipt authenticate. Partial caches fail closed.
The original run did not mutate Git, make an API request, or read Patron/profile
inputs.

These analyses are explicitly post-outcome and secondary. Rerunning them cannot
change any frozen family or gate decision.
