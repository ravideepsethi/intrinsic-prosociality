#!/usr/bin/env python3
"""Resumable controller for pool-main Wave 2A."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from runner import common


STAGES = (
    "preflight",
    "dynamics_inventory",
    "crossing_audit",
    "crossing_verify",
    "fen_design",
    "fen_analysis",
    "fen_verify",
    "collect",
)
FEN_STATUS = "POOL_MAIN_EQUALITY_FEN_AUDIT_V200_OK"
DESIGN_STATUS = "POOL_MAIN_EQUALITY_FEN_POSITION_DESIGN_V200_OK"
ANALYSIS_STATUS = "POOL_MAIN_EQUALITY_FEN_ANALYSIS_STAGE_COMPLETE"
CROSSING_STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_OK"
CROSSING_VERIFY_STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_VERIFIED_OK"
ANALYSIS_REQUIRED = (
    "analysis_complete.json",
    "interpretation.json",
    "receipts/input_authorities.json",
    "receipts/input_no_mutation.json",
    "receipts/position_design_receipt.json",
    "tables/equality_fe_models.csv",
    "tables/equality_raw_contrasts.csv",
    "tables/engine_zero_models.csv",
    "tables/five_bin_by_ply_band.csv",
    "tables/position_commonness_models.csv",
)


def parse_args() -> argparse.Namespace:
    authority = common.load_json(common.AUTHORITY_PATH)
    project_default = Path(os.environ.get("PROJECT_ROOT", authority["default_project_root"]))
    sample_default = Path(
        os.environ.get(
            "SAMPLE_ROOT",
            str(project_default / authority["default_sample_root_relative"]),
        )
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_default)
    parser.add_argument("--sample-root", type=Path, default=sample_default)
    parser.add_argument("--wave1-public", type=Path)
    parser.add_argument("--public-base", type=Path)
    parser.add_argument("--private-base", type=Path)
    parser.add_argument(
        "--transfer-root",
        type=Path,
        default=Path(
            os.environ.get("TRANSFER_ROOT", "/Users/u6025368/Desktop/Lichess_Desktop")
        ),
    )
    parser.add_argument("--threads", type=int, default=int(os.environ.get("ANALYSIS_THREADS", "8")))
    parser.add_argument("--memory-limit", default=os.environ.get("ANALYSIS_MEMORY", "12GB"))
    parser.add_argument("--min-free-gb", type=float, default=80.0)
    parser.add_argument(
        "--stages",
        default=",".join(STAGES),
        help="Comma-separated ordered subset of: " + ",".join(STAGES),
    )
    parser.add_argument(
        "--force-inventory",
        action="store_true",
        help="Recompute new-sample dynamics support counts even if a ready receipt exists.",
    )
    return parser.parse_args()


def command(module_or_script: str | Path, values: list[object], *, module: bool) -> list[str]:
    prefix = [sys.executable, "-B", "-u"]
    if module:
        prefix.extend(["-m", str(module_or_script)])
    else:
        prefix.append(str(module_or_script))
    return [*prefix, *[str(value) for value in values]]


def run_logged(stage: str, argv: list[str], logs: Path, environment: dict[str, str]) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{stage}.log"
    print(f"\n===== {stage.upper()} =====", flush=True)
    print("COMMAND:", shlex.join(argv), flush=True)
    with log.open("a", encoding="utf-8", newline="") as stream:
        stream.write(f"\n[{common.utc_now()}] COMMAND {shlex.join(argv)}\n")
        stream.flush()
        process = subprocess.Popen(
            argv,
            cwd=common.PACKAGE_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            stream.write(line)
            stream.flush()
        code = process.wait()
        stream.write(f"[{common.utc_now()}] EXIT {code}\n")
    if code:
        raise RuntimeError(f"Stage {stage} exited {code}; see {log}")


def json_has(path: Path, status: str, fingerprint: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = common.load_json(path)
    except Exception:
        return False
    lineage = value.get("sample_authority") or {}
    observed = lineage.get("fingerprint") or value.get("sample_fingerprint")
    return value.get("status") == status and observed == fingerprint


def resumable_stage(
    stage: str,
    *,
    public: Path,
    private: Path,
    fingerprint: str,
    force_inventory: bool,
) -> bool:
    if stage == "dynamics_inventory" and not force_inventory:
        return json_has(
            public / "DYNAMICS_REBUILD_PREFLIGHT.json",
            "POOL_MAIN_WAVE2B_PREFLIGHT_READY",
            fingerprint,
        )
    if stage == "crossing_audit":
        return json_has(
            public / "crossing_default_audit/_SUCCESS.json",
            CROSSING_STATUS,
            fingerprint,
        )
    if stage == "crossing_verify":
        return json_has(
            public / "crossing_default_audit/_VERIFIED.json",
            CROSSING_VERIFY_STATUS,
            fingerprint,
        )
    if stage == "fen_design":
        public_receipt = public / "equality_fen/receipts/position_design_receipt.json"
        private_receipt = private / "equality_fen/position_design_receipt.json"
        cache = private / "equality_fen/short_position_commonness_private.parquet"
        if not all(path.is_file() for path in (public_receipt, private_receipt, cache)):
            return False
        try:
            receipt = common.load_json(private_receipt)
            return (
                receipt.get("status") == DESIGN_STATUS
                and receipt.get("sample_fingerprint") == fingerprint
                and int(receipt.get("bytes", -1)) == cache.stat().st_size
                and receipt.get("sha256") == common.sha256_file(cache)
            )
        except Exception:
            return False
    if stage == "fen_analysis":
        root = public / "equality_fen"
        return all((root / relative).is_file() for relative in ANALYSIS_REQUIRED) and json_has(
            root / "analysis_complete.json", ANALYSIS_STATUS, fingerprint
        )
    return False


def main() -> int:
    args = parse_args()
    requested = [item.strip() for item in args.stages.split(",") if item.strip()]
    unknown = sorted(set(requested) - set(STAGES))
    if unknown or not requested:
        raise SystemExit(f"Invalid --stages selection: {unknown or requested}")
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"Project root is unavailable; connect XT_Pro: {project}")
    sample = args.sample_root.expanduser().resolve()
    wave1 = (
        args.wave1_public or project / "output/pool_main_reanalysis_v100/wave1"
    ).expanduser().resolve()
    public = (
        args.public_base or project / "output/pool_main_reanalysis_v100/wave2a"
    ).expanduser().resolve()
    private = (
        args.private_base
        or project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2a"
    ).expanduser().resolve()
    for root in (public, private):
        root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(private).free / 1024**3
    if free_gb < args.min_free_gb:
        raise SystemExit(
            f"Insufficient free space at {private}: {free_gb:.1f} GiB available; "
            f"require at least {args.min_free_gb:.1f} GiB"
        )
    auth = common.authenticate_sample(sample, verify_hashes=False)
    fingerprint = auth["fingerprint"]
    fen_package = common.PACKAGE_ROOT / "source/fen"
    fen_code = fen_package / "code"
    fen_public = public / "equality_fen"
    fen_private = private / "equality_fen"
    crossing_public = public / "crossing_default_audit"
    crossing_private = private / "crossing_default_audit"
    transfer = args.transfer_root.expanduser().resolve()
    transfer.mkdir(parents=True, exist_ok=True)

    run_command = [sys.executable, "-B", "-u", "-m", "runner.orchestrate", *sys.argv[1:]]
    common.atomic_text(public / "RUN_COMMAND.txt", shlex.join(run_command) + "\n")
    state_path = public / "WAVE2A_RUN_STATUS.json"
    started = time.monotonic()
    state = {
        "status": "POOL_MAIN_REANALYSIS_WAVE2A_RUNNING",
        "started_at_utc": common.utc_now(),
        "sample_authority": common.compact_sample_lineage(auth),
        "command": {
            "argv": sys.argv,
            "python": sys.executable,
            "project_root": str(project),
            "sample_root": str(sample),
            "wave1_public": str(wave1),
            "public_base": str(public),
            "private_base": str(private),
            "transfer_root": str(transfer),
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "minimum_free_gb": args.min_free_gb,
            "requested_stages": requested,
        },
        "completed_stages": [],
        "resumed_stages": [],
    }
    common.atomic_json(state_path, state)

    values = [
        "--package-root", fen_package,
        "--project-root", project,
        "--private-root", fen_private,
        "--public-root", fen_public,
    ]
    commands = {
        "preflight": command(
            "runner.preflight",
            [
                "--project-root", project,
                "--sample-root", sample,
                "--wave1-public", wave1,
                "--private-base", private,
                "--receipt", public / "PREFLIGHT.json",
                "--min-free-gb", args.min_free_gb,
            ],
            module=True,
        ),
        "dynamics_inventory": command(
            "runner.dynamics_preflight",
            [
                "--project-root", project,
                "--sample-root", sample,
                "--wave1-public", wave1,
                "--receipt", public / "DYNAMICS_REBUILD_PREFLIGHT.json",
                "--private-temp", private / "dynamics_inventory_duckdb_spill",
                "--threads", args.threads,
                "--memory-limit", args.memory_limit,
            ],
            module=True,
        ),
        "crossing_audit": command(
            "runner.crossing_audit",
            [
                "--sample-root", sample,
                "--wave1-public", wave1,
                "--public-root", crossing_public,
                "--private-root", crossing_private,
                "--threads", args.threads,
                "--memory-limit", args.memory_limit,
            ],
            module=True,
        ),
        "crossing_verify": command(
            "runner.verify_crossing_audit",
            ["--public-root", crossing_public],
            module=True,
        ),
        "fen_design": command(fen_code / "00_build_position_design.py", values, module=False),
        "fen_analysis": command(fen_code / "01_run_equality_fen_audit.py", values, module=False),
        "fen_verify": command(
            fen_code / "02_verify_equality_fen_audit.py",
            ["--package-root", fen_package, "--public-root", fen_public],
            module=False,
        ),
        "collect": command(
            "runner.collect",
            [
                "--sample-root", sample,
                "--wave1-public", wave1,
                "--public-base", public,
                "--private-base", private,
                "--transfer-root", transfer,
            ],
            module=True,
        ),
    }
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            [str(common.PACKAGE_ROOT), str(fen_code), environment.get("PYTHONPATH", "")],
        )
    )
    environment["MPLBACKEND"] = "Agg"
    environment.setdefault("OMP_NUM_THREADS", "1")
    environment.setdefault("OPENBLAS_NUM_THREADS", "1")
    environment.setdefault("MKL_NUM_THREADS", "1")
    logs = public / "_logs"
    try:
        for stage in requested:
            if resumable_stage(
                stage,
                public=public,
                private=private,
                fingerprint=fingerprint,
                force_inventory=args.force_inventory,
            ):
                print(f"\n===== {stage.upper()} (AUTHENTICATED RESUME) =====", flush=True)
                state["resumed_stages"].append(stage)
            else:
                if stage == "collect":
                    state["status"] = "POOL_MAIN_REANALYSIS_WAVE2A_COMPUTE_OK"
                    state["compute_completed_at_utc"] = common.utc_now()
                    common.atomic_json(state_path, state)
                run_logged(stage, commands[stage], logs, environment)
            state["completed_stages"].append(stage)
            state["last_completed_at_utc"] = common.utc_now()
            common.atomic_json(state_path, state)
        state["status"] = "POOL_MAIN_REANALYSIS_WAVE2A_OK"
        state["completed_at_utc"] = common.utc_now()
        state["runtime_seconds"] = round(time.monotonic() - started, 3)
        common.atomic_json(state_path, state)
        print("\nPOOL_MAIN_REANALYSIS_WAVE2A_OK", flush=True)
        print(f"public_results: {public}", flush=True)
        print(f"private_restart_state: {private}", flush=True)
        return 0
    except Exception as exc:
        state["status"] = "POOL_MAIN_REANALYSIS_WAVE2A_STOPPED"
        state["stopped_at_utc"] = common.utc_now()
        state["runtime_seconds"] = round(time.monotonic() - started, 3)
        state["error"] = f"{type(exc).__name__}: {exc}"
        state["traceback"] = traceback.format_exc()
        common.atomic_json(state_path, state)
        print(f"POOL_MAIN_REANALYSIS_WAVE2A_STOPPED: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
