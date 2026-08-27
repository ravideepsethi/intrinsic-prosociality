#!/bin/bash
set -euo pipefail

task_package_root="$(cd "$(dirname "$0")" && pwd)"
task_project="/Volumes/XT_Pro/lichess_kindness"
task_python="$task_project/venv/bin/python"
task_base_output="$task_project/output/PATRON_STAGE10_PRODUCTION_V100"
task_output="$task_project/output/PATRON_STAGE10_POSTCERT_ADDENDUM_V100"
task_desktop="/Users/u6025368/Desktop/Lichess_Desktop"
task_manifest="$task_package_root/PatronStage10_postcertification_addendum_package_manifest.tsv"
task_threads="${PATRON_STAGE10_THREADS:-8}"
task_memory_limit="${PATRON_STAGE10_MEMORY_LIMIT:-12GB}"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

printf '%s\n' '============================================================'
printf '%s\n' 'PATRON STAGE 10 — POST-CERTIFICATION ADDENDUM v1.0.0'
printf '%s\n' '============================================================'
printf '\nExpected total runtime: approximately 10-45 minutes; most likely 15-30.\n'
printf 'Synthetic self-test: approximately 1-3 minutes.\n'
printf 'Production addendum: approximately 10-40 minutes.\n\n'
printf 'This is a separate, append-only sensitivity package.\n'
printf 'The certified v1.0.1 production output is authenticated and never modified.\n'
printf 'No API call, dependency installation, Git mutation, or source-data mutation occurs.\n\n'

if [[ ! -d "$task_project" ]]; then
    printf 'ERROR: XT_Pro project is not mounted at:\n%s\n' "$task_project" >&2
    exit 1
fi
if [[ ! -x "$task_python" ]]; then
    printf 'ERROR: canonical project Python is missing:\n%s\n' "$task_python" >&2
    exit 1
fi
if [[ ! -d "$task_base_output" ]]; then
    printf 'ERROR: certified v1.0.1 output is missing:\n%s\n' "$task_base_output" >&2
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
expected = {row["relative_path"] for row in rows}
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
observed = {
    path.relative_to(root).as_posix()
    for path in root.rglob("*")
    if path.is_file() and path != manifest
}
extras = sorted(observed - expected)
missing = sorted(expected - observed)
if extras or missing:
    raise SystemExit(
        f"ERROR: source tree differs from manifest; extras={extras}; missing={missing}"
    )
if any("__pycache__" in path.parts or path.suffix == ".pyc" for path in root.rglob("*")):
    raise SystemExit("ERROR: generated Python bytecode exists in the package source")
print("PACKAGE_CONTENTS_AND_CLEANLINESS_AUTHENTICATED_OK")
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
    raise SystemExit("ERROR: canonical environment differs; this package changes nothing.")
print("CANONICAL_ENVIRONMENT_OK")
PY

task_selftest="$(mktemp -d "$task_project/output/PATRON_STAGE10_POSTCERT_ADDENDUM_SELFTEST.XXXXXX")"
task_fixture="$task_selftest/project"
task_fixture_base="$task_selftest/base_output"
task_fixture_output="$task_selftest/addendum_output"
task_fixture_source="$task_package_root/selftest_base_v101"

printf '\nRunning end-to-end synthetic base and addendum self-test...\n'
"$task_python" "$task_fixture_source/code/04_make_synthetic_fixture.py" \
    --fixture-root "$task_fixture"
"$task_python" "$task_fixture_source/code/00_build_patron_chooser_cache.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_base" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_fixture_source/code/01_estimate_patron_chooser_models.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_base" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_fixture_source/code/02_estimate_patron_opportunity_models.py" \
    --project-root "$task_fixture" \
    --output-root "$task_fixture_base" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_fixture_source/code/03_verify_patron_stage10_outputs.py" \
    --output-root "$task_fixture_base" \
    --fixture
"$task_python" "$task_package_root/code/00_run_postcertification_addendum.py" \
    --project-root "$task_fixture" \
    --base-output-root "$task_fixture_base" \
    --output-root "$task_fixture_output" \
    --threads 4 \
    --memory-limit 2GB \
    --fixture
"$task_python" "$task_package_root/code/01_verify_postcertification_addendum.py" \
    --output-root "$task_fixture_output" \
    --fixture
printf 'PATRON_STAGE10_POSTCERT_ADDENDUM_SYNTHETIC_SELFTEST_OK\n'
printf 'Self-test retained at: %s\n' "$task_selftest"

mkdir -p "$task_output"
printf '\nStarting or resuming authenticated production addendum...\n'
"$task_python" "$task_package_root/code/00_run_postcertification_addendum.py" \
    --project-root "$task_project" \
    --base-output-root "$task_base_output" \
    --output-root "$task_output" \
    --threads "$task_threads" \
    --memory-limit "$task_memory_limit"

printf '\nRunning independent production addendum verifier...\n'
"$task_python" "$task_package_root/code/01_verify_postcertification_addendum.py" \
    --output-root "$task_output"

printf '\nRechecking executed-source cleanliness before transfer...\n'
if find "$task_package_root" -type d -name '__pycache__' -print -quit | grep -q . || \
   find "$task_package_root" -type f -name '*.pyc' -print -quit | grep -q .
then
    printf 'ERROR: generated Python bytecode appeared in package source.\n' >&2
    exit 1
fi

task_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
task_transfer="$(mktemp -d "$task_desktop/PATRON_STAGE10_POSTCERT_ADDENDUM_TRANSFER.XXXXXX")"
task_bundle="$task_desktop/PATRON_STAGE10_POSTCERT_ADDENDUM_V100_RESULTS_${task_stamp}.zip"
task_sidecar="$task_bundle.sha256"
mkdir -p \
    "$task_transfer/public_results" \
    "$task_transfer/run_receipts" \
    "$task_transfer/executed_package_source"
cp -R "$task_output/public_results/." "$task_transfer/public_results/"
cp -R "$task_output/run_receipts/." "$task_transfer/run_receipts/"
cp -R "$task_package_root/." "$task_transfer/executed_package_source/"

(cd "$task_transfer" && /usr/bin/zip -qry "$task_bundle" .)
task_bundle_sha="$(shasum -a 256 "$task_bundle" | awk '{print $1}')"
printf '%s  %s\n' "$task_bundle_sha" "$(basename "$task_bundle")" > "$task_sidecar"

printf '\n============================================================\n'
printf 'PATRON STAGE 10 POST-CERTIFICATION ADDENDUM CERTIFIED COMPLETE\n'
printf '============================================================\n'
"$task_python" - "$task_output/public_results" <<'PY'
import json
import pathlib
import pandas as pd
import sys

root = pathlib.Path(sys.argv[1])
success = json.loads((root / "_SUCCESS.json").read_text(encoding="utf-8"))
comparison = json.loads(
    (root / "corrected_vs_certified_comparison.json").read_text(encoding="utf-8")
)
fair = pd.read_csv(root / "five_bin_chooser_contrasts.csv")
fair_row = fair.loc[
    fair["model"].eq("five_bin_chooser_min4_full_HC1")
    & fair["contrast"].eq("clearly_better_minus_clearly_worse")
].iloc[0]
price = pd.read_csv(root / "price_count_rate_contrasts.csv")
price_rows = price.loc[
    price["model"].isin(["price_count_min4_full_HC1", "price_rate_min4_full_HC1"])
]
print("Status:", success["status"])
print("Certified v1.0.1 primary preserved:", success["base_primary_coefficient_pp"])
print(
    "Certified v1.0.1 full-control coefficient (pp):",
    comparison["certified_v101_full_control_coefficient_pp"],
)
print(
    "Corrected-date full-control coefficient (pp):",
    comparison["corrected_date_full_control_coefficient_pp"],
)
print("Five-bin clearly-better minus clearly-worse contrast (pp):", fair_row["difference_pp"])
for row in price_rows.itertuples(index=False):
    print(f"{row.model} standardized costly-minus-nonnegative (pp): {row.difference_pp}")
print("Interpretation: secondary cross-sectional addendum; not patron adoption or causality.")
PY
printf '\nSeparate private output root: %s\n' "$task_output"
printf 'Authenticated transfer ZIP: %s\n' "$task_bundle"
printf 'ZIP SHA-256: %s\n' "$task_bundle_sha"
printf 'Sidecar: %s\n' "$task_sidecar"
printf '\nUpload the ZIP and sidecar and paste the complete final summary into ChatGPT.\n'
