#!/usr/bin/env python3
"""Independent aggregate-output verifier; reads no private account-level data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

PUBLIC_FILES = (
    "sample_summary.csv",
    "table1_descriptives.csv",
    "five_bin_rates.csv",
    "rating_gap_rates.csv",
    "structural_chooser_fe.csv",
    "persistence.csv",
    "a1_unfamiliar_opponent_sensitivity.csv",
    "patron_singleton_rematch.csv",
    "c9_singleton_randomization.csv",
    "c7r_prefocal_authority.json",
    "c7x_relationship_mechanism.json",
    "c6_scope.json",
    "module_status.csv",
    "summary.json",
    "README_results.md",
)
FORBIDDEN = {
    "game_id",
    "chooser_user_id",
    "opponent_user_id",
    "username_norm",
    "chooser_username_norm",
    "recipient_user_id",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(root: Path) -> dict:
    for name in PUBLIC_FILES:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing/empty public result: {path}")
        if path.suffix == ".csv":
            with path.open(newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                if FORBIDDEN.intersection(header):
                    raise RuntimeError(f"Identifier leaked in {name}")
                if next(reader, None) is None:
                    raise RuntimeError(f"No data rows in {name}")
    summary = json.loads((root / "summary.json").read_text())
    success = json.loads((root / "_SUCCESS.json").read_text())
    if summary.get("status") != "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_OK":
        raise RuntimeError("Summary status changed")
    if success.get("status") != "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_INDEPENDENT_VERIFICATION_OK":
        raise RuntimeError("Success status changed")
    manifest = {r["path"]: r for r in success.get("files", [])}
    if set(manifest) != set(PUBLIC_FILES):
        raise RuntimeError("Success file set changed")
    for name, row in manifest.items():
        path = root / name
        if int(row["bytes"]) != path.stat().st_size or row["sha256"] != sha256(path):
            raise RuntimeError(f"Hash/byte mismatch: {name}")
    modules = list(csv.DictReader((root / "module_status.csv").open(newline="")))
    required = {
        "structural_and_persistence",
        "A1_receipt_to_different_unfamiliar_opponent",
        "Patron_reconstructed_kindness_and_rematch",
        "C9_singleton_conditional_randomization",
        "C7R_prefocal_history_authority",
        "C7X_relationship_specific_classification",
        "C6_first_exposure_scope",
    }
    if {r["module"] for r in modules} != required:
        raise RuntimeError("Module set changed")
    return {"status": "PAPERWIDE_REPEAT_DYAD_AUDIT_V100_INDEPENDENT_VERIFICATION_OK", "run_id": summary["run_id"], "files": len(PUBLIC_FILES)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.result_root), sort_keys=True))


if __name__ == "__main__":
    main()
