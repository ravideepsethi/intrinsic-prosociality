#!/usr/bin/env python3
"""Refit and render the latest controlled reference-price diagnostic on pool-main."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from runner import common


MODEL_STATUS = "POOL_MAIN_CONTROLLED_REFERENCE_PRICE_MODEL_V110_COMPLETE"
FIGURE_STATUS = "POOL_MAIN_CONTROLLED_REFERENCE_PRICE_FIX_V111_COMPLETE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--figure-output", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory", default="10GB")
    parser.add_argument("--batch-rows", type=int, default=32768)
    parser.add_argument("--hash-workers", type=int, default=8)
    return parser.parse_args()


def _engine_complete(model_output: Path, private_root: Path, auth: dict) -> bool:
    receipt_path = model_output / "receipts/completion_receipt.json"
    lineage_path = model_output / "POOL_MAIN_LINEAGE.json"
    cache = private_root / "controlled_reference_price_local_h1_private.parquet"
    if not (receipt_path.is_file() and lineage_path.is_file() and cache.is_file()):
        return False
    receipt = common.load_json(receipt_path)
    lineage = common.load_json(lineage_path)
    if receipt.get("status") != "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE":
        return False
    if lineage.get("status") != MODEL_STATUS:
        return False
    return (lineage.get("sample_authority") or {}).get("fingerprint") == auth["fingerprint"]


def _add_engine_lineage(
    engine,
    model_output: Path,
    private_root: Path,
    auth: dict,
    source_path: Path,
) -> None:
    receipt_path = model_output / "receipts/completion_receipt.json"
    receipt = common.load_json(receipt_path)
    if receipt.get("status") != "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE":
        raise RuntimeError("Controlled reference-price v1.1.0 source run is incomplete")
    if Path(receipt["panel"]).resolve() != auth["panel_root"].resolve():
        raise RuntimeError("Controlled reference-price model used a different panel")
    lineage = {
        "status": MODEL_STATUS,
        "created_at_utc": common.utc_now(),
        "sample_authority": common.compact_sample_lineage(auth),
        "source_program": common.source_record(source_path, "controlled_reference_price_v1.1.0"),
        "adapter": common.source_record(Path(__file__).resolve(), "pool_main_adapter"),
        "private_cache": str(private_root.resolve()),
        "old_full_panel_numeric_bridge_authentication_requested": False,
        "new_sample_authentication": "24 monthly panel bytes authenticated against the certified pool-main report",
    }
    common.atomic_json(model_output / "POOL_MAIN_LINEAGE.json", lineage)
    engine.write_manifest(model_output)
    engine.package_output(model_output)


def _validate_new_source(renderer, engine, source: Path, auth: dict):
    checksums = renderer.verify_manifest(source)
    needed = [
        "receipts/completion_receipt.json",
        "receipts/executed_controlled_reference_price_figure.py",
        "tables/controlled_reference_price_bins.csv",
        "tables/controlled_local_h1_coefficients.csv",
        "tables/source_month_inventory.csv",
        "tables/source_identity_checks.csv",
        "POOL_MAIN_LINEAGE.json",
    ]
    if not set(needed).issubset(checksums):
        raise RuntimeError("Required new-sample source outputs are not manifest-covered")
    receipt = common.load_json(source / "receipts/completion_receipt.json")
    if receipt.get("version") != "1.1.0" or receipt.get("status") != "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE":
        raise RuntimeError("Unexpected controlled reference-price source receipt")
    if receipt.get("synthetic_smoke_test"):
        raise RuntimeError("Production renderer refuses a synthetic source")
    if receipt.get("code_sha256") != renderer.ENGINE_SHA256:
        raise RuntimeError("Frozen v1.1.0 engine checksum changed")
    settings = receipt.get("settings") or {}
    for key, expected in {"payoff_limit": 5.0, "bin_width": 0.25, "local_bandwidth": 1.0}.items():
        if settings.get(key) != expected:
            raise RuntimeError(f"Unexpected controlled model setting: {key}")
    if Path(receipt["panel"]).resolve() != auth["panel_root"].resolve():
        raise RuntimeError("Controlled model receipt points to another panel")
    lineage = common.load_json(source / "POOL_MAIN_LINEAGE.json")
    if lineage.get("status") != MODEL_STATUS:
        raise RuntimeError("Controlled model lacks the pool-main lineage status")
    if (lineage.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Controlled model lineage belongs to another sample")
    inventory = pd.read_csv(source / "tables/source_month_inventory.csv")
    if len(inventory) != 24:
        raise RuntimeError("Controlled model source-month inventory is incomplete")
    if int(inventory["n"].sum()) != int(auth["authority"]["rows"]):
        raise RuntimeError("Controlled model source rows differ from pool-main")
    if int(inventory["kind"].sum()) != int(auth["authority"]["kind_draws"]):
        raise RuntimeError("Controlled model source outcomes differ from pool-main")
    identity = pd.read_csv(source / "tables/source_identity_checks.csv").iloc[0]
    if int(identity["n"]) != int(auth["authority"]["rows"]):
        raise RuntimeError("Controlled model identity total differs from pool-main")
    if int(identity["distinct_games"]) != int(auth["authority"]["rows"]):
        raise RuntimeError("Controlled model game identity is not one-row-per-game")
    return receipt, checksums


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.threads <= 10 or not 1 <= args.hash_workers <= 10:
        raise SystemExit("Require 1-10 analysis threads and hash workers")
    if args.batch_rows < 4096:
        raise SystemExit("Require --batch-rows >= 4096")
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    model_output = args.model_output.resolve()
    private_root = args.private_root.resolve()
    figure_output = args.figure_output.resolve()
    scratch_root = args.scratch_root.resolve()
    engine_path = common.PACKAGE_ROOT / "source/controlled/reference_price_model_v110.py"
    renderer_path = common.PACKAGE_ROOT / "source/controlled/controlled_reference_price_figure.py"

    engine = common.load_source_module(engine_path, "reference_price_model_v110")
    if not _engine_complete(model_output, private_root, auth):
        old_argv = sys.argv[:]
        resume = model_output.exists() or private_root.exists()
        argv = [
            str(engine_path),
            "--panel",
            str(auth["panel_root"]),
            "--out",
            str(model_output),
            "--private",
            str(private_root),
            "--threads",
            str(args.threads),
            "--memory",
            args.memory,
            "--batch-rows",
            str(args.batch_rows),
        ]
        if resume:
            argv.append("--resume")
        try:
            sys.argv = argv
            engine.main()
        finally:
            sys.argv = old_argv
        _add_engine_lineage(engine, model_output, private_root, auth, engine_path)

    figure_receipt = figure_output / "receipts/completion_receipt.json"
    if figure_receipt.is_file():
        saved = common.load_json(figure_receipt)
        if saved.get("status") == FIGURE_STATUS:
            if (saved.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
                raise RuntimeError("Existing controlled figure belongs to another sample")
            return saved
        if saved.get("status") != "CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE":
            raise RuntimeError("Existing controlled figure has an unexpected status")
    elif figure_output.exists():
        raise RuntimeError(
            f"Incomplete controlled-figure output exists; preserve it and choose a fresh root: {figure_output}"
        )
    else:
        renderer = common.load_source_module(
            renderer_path, "controlled_reference_price_figure"
        )
        renderer.validate_source = lambda source, allow_synthetic: _validate_new_source(
            renderer, engine, source, auth
        )
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                str(renderer_path),
                "--source-run",
                str(model_output),
                "--source-private",
                str(private_root),
                "--out",
                str(figure_output),
                "--scratch",
                str(scratch_root),
                "--threads",
                str(args.threads),
                "--memory",
                args.memory,
                "--batch-rows",
                str(args.batch_rows),
            ]
            renderer.main()
        finally:
            sys.argv = old_argv

    saved = common.load_json(figure_receipt)
    if saved.get("status") != "CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE":
        raise RuntimeError("Controlled reference-price v1.1.1 renderer did not complete")
    saved["upstream_producer_status"] = saved["status"]
    saved["status"] = FIGURE_STATUS
    saved["sample_authority"] = common.compact_sample_lineage(auth)
    saved["source_program"] = common.source_record(
        renderer_path, "controlled_reference_price_v1.1.1"
    )
    saved["adapter"] = common.source_record(Path(__file__).resolve(), "pool_main_adapter")
    common.atomic_json(figure_receipt, saved)
    engine.write_manifest(figure_output)
    engine.package_output(figure_output)
    print(FIGURE_STATUS, flush=True)
    return saved


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
