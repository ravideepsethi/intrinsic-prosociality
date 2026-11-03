# Chooser comparison expansion v1.0.0

This package prepares and retrieves the larger ordinary-game comparison frame.
It does not rerun the IV, run Stockfish, estimate a placebo, or change the A1
trajectory job. The new sample is fixed at 1 in 32 using the exact old rule;
the previous 1-in-1,024 frame and its orientation must reproduce exactly.

Expect roughly 61 million frame games, including the 1.9 million already used.
The exact count and remaining API targets are printed after the local scan.
At the observed 29.05 games/second, fetching all approximately 59 million new
games would take about 24 days before backoffs. Completed local metadata can
reduce that. This is a precision-based choice following the user's removal of
the download budget, not a promised power calculation. See DESIGN.md.

## 1. Prepare on the work laptop

Place the code ZIP and its .sha256 sidecar in ~/Desktop/Lichess_Desktop. Keep
XT_Pro connected. Paste the complete block below in the usual Anaconda terminal:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Chooser_Comparison_Expansion_v1_0_0.zip.sha256
if [[ ! -d Chooser_Comparison_Expansion_v1_0_0 ]]; then
  /usr/bin/ditto -x -k Chooser_Comparison_Expansion_v1_0_0.zip .
fi
export COMP_EXP_PROJECT_ROOT="/Volumes/XT_Pro/lichess_kindness"
export COMP_EXP_DESKTOP="$PWD"
export COMP_EXP_WORKERS=10
export COMP_EXP_MEMORY_GB=4
/bin/bash "$PWD/Chooser_Comparison_Expansion_v1_0_0/PREPARE.command"
BASH
```

This command makes zero Lichess requests. It can run while A1 recovery runs,
although simultaneous disk-heavy jobs may slow each other. It automatically
uses a compatible existing Python environment. Only if none exists does it
create an environment and install dependencies from PyPI. That installation
is internet access, not Lichess retrieval.

Preparation verifies the existing inputs, freezes the design, scans 105
chronology files with 10 local workers, reproduces the original frame, and
writes 21 monthly Parquets. It inventories completed local API exports and
recognized normalized metadata caches, then merges agreeing records. Raw PGN
is not treated as a source label. The cache inventory is saved on first run;
later files are not silently added during resume. The aggregate report makes
any cache-format/parse gaps visible. Additional cache roots may be supplied
as --extra-cache-root "/exact/cache/path" on the PREPARE.command call, before
the initial inventory. No API metadata is assumed from an uninspected file.

Allow at least 35 GiB free on XT_Pro for preparation, plus room on the Desktop
for the portable input. This is a disk-space check, not a runtime prediction.
The real scan and cache inventory set the runtime; heartbeats print every
45 seconds and completed-file/group counts print throughout.

At completion it prints:

- **UPLOAD**: a small PREPARATION_REPORT ZIP and its checksum. Upload those here.
- **PRIVATE INPUT**: a portable input ZIP and checksum. Keep those private.

Completed sampling/cache stages are reusable with the same command. Existing
source and analysis files are never overwritten.

## 2. Download metadata on either laptop

If using the home laptop, copy FOUR files into its Lichess_Desktop folder:
the code ZIP, its checksum, the generated PRIVATE INPUT ZIP, and its checksum.
The input contains only the still-needed target list and the frozen design;
the complete frame and old cache evidence stay on XT_Pro.

Start this only after other Lichess API downloads finish. A1's Stockfish-only
phase can run at the same time. The wrapper checks known active A1/comparison
workers and honors the comparison downloader's existing shared lock. It cannot
detect an API job on another laptop or every independently written downloader.

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Chooser_Comparison_Expansion_v1_0_0.zip.sha256
if [[ ! -d Chooser_Comparison_Expansion_v1_0_0 ]]; then
  /usr/bin/ditto -x -k Chooser_Comparison_Expansion_v1_0_0.zip .
fi
export COMP_EXP_PROJECT_ROOT="/Volumes/XT_Pro/lichess_kindness"
export COMP_EXP_DESKTOP="$PWD"
/bin/bash "$PWD/Chooser_Comparison_Expansion_v1_0_0/RUN_DOWNLOAD.command"
BASH
```

Exactly one PRIVATE INPUT ZIP should be present, or append
--input "/exact/path/CHOOSER_COMPARISON_EXPANSION_INPUT_..._PRIVATE.zip".
Checksum filenames with a duplicate-download suffix are accepted only when
their contents match the actual archive digest. TLS remains verified. An
optional existing LICHESS_API_TOKEN or LICHESS_TOKEN environment variable is
used but never saved; no token is required by these commands.

Each request contains at most 300 game IDs. Moves, clocks, engine evaluations
and openings are disabled. Success triggers the next request immediately.
Only server/error cooldowns delay requests; HTTP 429 waits at least 60 seconds,
or longer when the server requires it. See [Lichess API tips](https://lichess.org/page/api-tips).

One SQLite checkpoint on the downloading laptop stores compressed original
responses and their SHA-256 digests. Each successful response commits before
the next request. This avoids creating hundreds of thousands of tiny files on
XT_Pro. Re-running verifies and reuses committed responses; an interrupted
in-flight response can be requested again. Nonreturns have up to three passes.
There are no parallel API workers. The 10-worker setting applies to local
preparation; this package has no engine settings.

The downloader estimates free disk needs using 450 bytes per remaining target,
150 bytes per total target for the final tables, and another 2 GiB. Actual
response sizes can differ; keep space for the final return ZIP too. It writes
typed metadata and a separate nonreturn Parquet after requests complete. All
metadata flags remain visible; neither nonreturns nor conflicts are deleted
from the underlying study denominator.

## 3. Check progress or pack the return

From a second terminal:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
export COMP_EXP_DESKTOP="$PWD"
/bin/bash "$PWD/Chooser_Comparison_Expansion_v1_0_0/STATUS.command"
BASH
```

When retrieval finishes, upload the small DOWNLOAD_REPORT ZIP and its
checksum. Prepare the private return with:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
export COMP_EXP_DESKTOP="$PWD"
/bin/bash "$PWD/Chooser_Comparison_Expansion_v1_0_0/PACK_RETURN.command"
BASH
```

Copy the resulting PRIVATE RETURN ZIP and checksum to the work laptop; do not
upload private game rows here. The return contains normalized metadata,
nonreturns, the original-response database, and file manifests. Global
username/account-ID alignment and cache-versus-new-response conflicts must be
reconciled on the work laptop before any new diagnostic is estimated. The
following analysis package can use those Parquets and the saved full frame;
this retrieval package does not silently launch it.

## Validation and scope

Offline tests run before preparation/download/packing, with fake HTTP, small
synthetic Parquets and a 180-second bound. They never contact Lichess. Real
downloads have no elapsed-time cap. Supported Python versions are 3.10+ with
numpy 2.2.6 or 2.3.5, pyarrow 21.0.0, and duckdb 1.5.4. Existing pipeline
environments are tried first. This package was tested in Linux; no claim is
made that the user's full private dataset was executed here.
