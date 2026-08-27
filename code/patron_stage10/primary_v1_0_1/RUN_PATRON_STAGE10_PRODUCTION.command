#!/bin/bash
set -euo pipefail

task_package_root="$(cd "$(dirname "$0")" && pwd)"
task_project="/Volumes/XT_Pro/lichess_kindness"
task_python="$task_project/venv/bin/python"
task_output="$task_project/output/PATRON_STAGE10_PRODUCTION_V100"
task_desktop="/Users/u6025368/Desktop/Lichess_Desktop"
task_manifest="$task_package_root/PatronStage10_production_package_manifest.tsv"
task_threads="${PATRON_STAGE10_THREADS:-8}"
task_memory_limit="${PATRON_STAGE10_MEMORY_LIMIT:-12GB}"

printf '%s\n' '============================================================'
printf '%s\n' 'PATRON STAGE 10 — AUTHENTICATED PRODUCTION RECOVERY v1.0.1'
printf '%s\n' '============================================================'
printf '\nExpected total runtime: approximately 1.5-6 hours; most likely 2-4 hours.\n'
printf 'Synthetic self-test: approximately 1-5 minutes.\n'
printf 'Chooser feature/cache stage: approximately 15-60 minutes.\n'
printf 'Chooser models and 100 rematches: approximately 30-150 minutes.\n'
printf 'Opportunity-level appendix: approximately 30-180 minutes.\n\n'
printf 'The run is checkpointed by stage. Rerun this same command after interruption.\n'
printf 'A completed v1.0.0 chooser-design stage is authenticated and reused.\n'
printf 'Recovery v1.0.1 preserves fractional medians for nullable integer covariates.\n'
printf 'No API call, dependency installation, Git mutation, or source-data mutation occurs.\n'
printf 'The shared Python environment is verified but never changed.\n\n'

if [[ ! -d "$task_project" ]]; then
    printf 'ERROR: XT_Pro project is not mounted at:\n%s\n' "$task_project" >&2
    exit 1
fi
if [[ ! -x "$task_python" ]]; then
    printf 'ERROR: canonical project Python is missing:\n%s\n' "$task_python" >&2
    exit 1
fi
if [[ ! -f "$task_manifest" ]]; then
    printf 'ERROR: package manifest is missing:\n%s\n' "$task_manifest" >&2
    exit 1
fi
mkdir -p "$task_project/output" "$task_desktop"

printf 'Authenticating packaged source...\n'
"$task_python" - "$task_package_root" "$task_manifest" <<'PY'
import csv
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = pathlib.Path(sys.argv[2])
with manifest.open(encoding="utf-8", newline="") as stream:
    rows = list(csv.DictReader(stream, delimiter="\t"))
if not rows:
    raise SystemExit("ERROR: package manifest is empty")
for row in rows:
    path = root / row["relative_path"]
    if not path.is_file():
        raise SystemExit(f"ERROR: packaged file missing: {path}")
    if path.stat().st_size != int(row["bytes"]):
        raise SystemExit(f"ERROR: packaged byte count mismatch: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != row["sha256"]:
        raise SystemExit(f"ERROR: packaged SHA-256 mismatch: {path}")
print("PACKAGE_CONTENTS_AUTHENTICATED_OK")
PY

printf '\nVerifying the unchanged canonical numerical environment...\n'
"$task_python" - <<'PY'
import duckdb
import numpy
import pandas
import pyarrow

observed = {
    "duckdb": duckdb.__version__,
    "numpy": numpy.__version__,
    "pandas": pandas.__version__,
    "pyarrow": pyarrow.__version__,
}
expected = {
    "duckdb": "1.5.2",
    "numpy": "2.4.4",
    "pandas": "3.0.3",
    "pyarrow": "24.0.0",
}
print("Observed:", observed)
print("Expected:", expected)
if observed != expected:
    raise SystemExit("ERROR: canonical environment differs. No package dependency was changed.")
print("CANONICAL_ENVIRONMENT_OK")
PY

task_selftest="$(mktemp -d "$task_project/output/PATRON_STAGE10_PRODUCTION_V101_SELFTEST.XXXXXX")"
task_fixture="$task_selftest/project"
task_fixture_output="$task_selftest/output"

printf '\nRunning end-to-end synthetic self-test...\n'
"$task_python" "$task_package_root/code/04_make_synthetic_fixture.py" \
    --fixture-root "$task_fixture"
"$task_python" "$task_package_root/code/00_build_patron_chooser_cache.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_output" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_package_root/code/01_estimate_patron_chooser_models.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_output" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_package_root/code/02_estimate_patron_opportunity_models.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_output" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_package_root/code/03_verify_patron_stage10_outputs.py" \
    --output-root "$task_fixture_output" \
    --fixture
printf 'PATRON_STAGE10_SYNTHETIC_SELFTEST_VERIFIED_OK\n'
printf 'Self-test retained at: %s\n' "$task_selftest"

mkdir -p "$task_output"

printf '\nStarting or resuming production chooser-design stage...\n'
"$task_python" "$task_package_root/code/00_build_patron_chooser_cache.py" \
    --project-root "$task_project" \
    --output-root "$task_output" \
    --threads "$task_threads" \
    --memory-limit "$task_memory_limit"

printf '\nStarting production chooser models and deterministic rematches...\n'
"$task_python" "$task_package_root/code/01_estimate_patron_chooser_models.py" \
    --project-root "$task_project" \
    --output-root "$task_output" \
    --threads "$task_threads" \
    --memory-limit "$task_memory_limit"

printf '\nStarting production opportunity-level appendix...\n'
"$task_python" "$task_package_root/code/02_estimate_patron_opportunity_models.py" \
    --project-root "$task_project" \
    --output-root "$task_output" \
    --threads "$task_threads" \
    --memory-limit "$task_memory_limit"

printf '\nRunning independent production verifier...\n'
"$task_python" "$task_package_root/code/03_verify_patron_stage10_outputs.py" \
    --output-root "$task_output"

task_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
task_transfer="$(mktemp -d "$task_desktop/PATRON_STAGE10_PRODUCTION_TRANSFER.XXXXXX")"
task_bundle="$task_desktop/PATRON_STAGE10_PRODUCTION_V101_RESULTS_${task_stamp}.zip"
task_sidecar="$task_bundle.sha256"
mkdir -p "$task_transfer/public_results" "$task_transfer/run_receipts" "$task_transfer/executed_package_source"
cp -R "$task_output/public_results/." "$task_transfer/public_results/"
cp -R "$task_output/run_receipts/." "$task_transfer/run_receipts/"
cp -R "$task_package_root/." "$task_transfer/executed_package_source/"

(cd "$task_transfer" && /usr/bin/zip -qry "$task_bundle" .)
task_bundle_sha="$(shasum -a 256 "$task_bundle" | awk '{print $1}')"
printf '%s  %s\n' "$task_bundle_sha" "$(basename "$task_bundle")" > "$task_sidecar"

printf '\n============================================================\n'
printf 'PATRON STAGE 10 PRODUCTION v1.0.1 CERTIFIED COMPLETE\n'
printf '============================================================\n'
"$task_python" - "$task_output/public_results" <<'PY'
import json
import pathlib
import pandas as pd
import sys

root = pathlib.Path(sys.argv[1])
success = json.loads((root / "_SUCCESS.json").read_text())
raw = pd.read_csv(root / "raw_matched_patron_comparisons.csv")
primary_raw = raw.loc[raw["sample"].eq("main_fair_kind_stored_1to3_available_cases")].iloc[0]
primary = success["primary_model"]
print("Status:", success["status"])
print("Primary raw kind patron rate (%):", primary_raw["treated_rate_pct"])
print("Primary raw control patron rate (%):", primary_raw["control_rate_pct"])
print("Primary raw gap (pp):", primary_raw["gap_pp"])
print("Primary match-cell-FE gap (pp):", primary["coefficient_pp"])
print("Primary HC1 SE (pp):", primary["se_pp"])
print("Primary approximate two-sided p:", primary["p_two_sided_approx"])
print("Interpretation: current cross-sectional stable-type association; not patron adoption or causality.")
PY
printf '\nPrivate output root: %s\n' "$task_output"
printf 'Authenticated transfer ZIP: %s\n' "$task_bundle"
printf 'ZIP SHA-256: %s\n' "$task_bundle_sha"
printf 'Sidecar: %s\n' "$task_sidecar"
printf '\nUpload the ZIP and sidecar and paste the final Terminal summary into ChatGPT.\n'
