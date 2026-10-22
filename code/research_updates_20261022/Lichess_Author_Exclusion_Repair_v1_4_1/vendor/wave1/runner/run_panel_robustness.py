#!/usr/bin/env python3
"""Run the public Stage-09 panel-robustness producer on the pool-main panel."""

from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path

from runner import common
from runner.run_core import STATUS as CORE_STATUS


STATUS = "POOL_MAIN_STAGE09_PANEL_ROBUSTNESS_24M_REESTIMATED_OK"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--stage08-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--hash-workers", type=int, default=8)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    stage08_success = args.stage08_root.resolve() / "_SUCCESS.json"
    core = common.verify_lineaged_json(stage08_success, CORE_STATUS, auth["fingerprint"])
    success_path = args.output_root.resolve() / "_SUCCESS.json"
    if args.output_root.exists():
        return common.verify_lineaged_json(success_path, STATUS, auth["fingerprint"])

    source_path = common.PACKAGE_ROOT / "source/core/09_build_panel_robustness.py"
    source = common.source_record(source_path, "public_repository")
    module = common.load_source_module(source_path, "pool_main_stage09_source")
    month_rows = OrderedDict(
        (row["month"], int(row["rows"])) for row in auth["month_records"]
    )
    module.SCRIPT_VERSION = "1.1.0+pool-main-wave1"
    module.PANEL_ROOT = auth["panel_root"]
    module.STAGE08_ROOT = args.stage08_root.resolve()
    module.MONTH_ROWS = month_rows
    module.ALL_MONTHS = tuple(month_rows)
    module.EXPECTED_STAGE07_ROWS = auth["authority"]["rows"]
    module.EXPECTED_STAGE07_KIND_DRAWS = auth["authority"]["kind_draws"]
    module.EXPECTED_STAGE07_COLUMNS = auth["authority"]["columns"]
    module.EXPECTED_STAGE07_STATUS = auth["authority"]["status"]
    module.EXPECTED_STAGE08_STATUS = CORE_STATUS
    module.git_state = common.recorded_git_state

    def authenticate_inputs(months, verify_hashes):
        records = common.legacy_month_records(auth, months)
        return {
            "hashes": {
                "stage07_success": auth["success_sha256"],
                "stage07_producer": auth["report"]["code_sha256"]["build_main_sample.py"],
                "stage08_success": common.sha256_file(stage08_success),
                "stage08_producer": common.sha256_file(
                    common.PACKAGE_ROOT / "runner/run_core.py"
                ),
            },
            "stage07_summary": auth["success"],
            "stage08_summary": core,
            "month_records": records,
            "selected_rows": sum(row["rows"] for row in records),
            "selected_bytes": sum(row["size_bytes"] for row in records),
        }

    module.authenticate_inputs = authenticate_inputs
    producer_args = argparse.Namespace(
        months="all",
        output_root=str(args.output_root.resolve()),
        threads=args.threads,
        memory_limit=args.memory_limit,
        expected_git_head="",
        self_test=False,
        execute=True,
    )
    module.execute(producer_args, module.ALL_MONTHS, Path(__file__).resolve())
    saved = common.replace_success_status(
        success_path,
        expected_old="STAGE09_PANEL_ROBUSTNESS_24M_CERTIFIED_OK",
        new_status=STATUS,
        auth=auth,
        source=source,
        adapter_path=Path(__file__).resolve(),
    )
    print(STATUS, flush=True)
    return saved


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
