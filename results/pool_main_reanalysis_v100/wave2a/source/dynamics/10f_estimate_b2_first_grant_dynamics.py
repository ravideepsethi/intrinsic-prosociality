#!/usr/bin/env python3
"""Estimate frozen B2 first-observed-grant dynamics with exact conditional draws.

This producer reuses the certified repeat-granter sample and cross-fitted static
propensities from the dynamic core. It is resumable at independent randomization
batches. Account-level inputs and randomization checkpoints remain private.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_GIT_BASE = "55124c10f746a6de6e5c186c8ddf7796fef5fb2a"
EXPECTED_CORE_CODE_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_PLAN_SHA256 = (
    "4f572bb8da7531bfa1b894cfde92da280a936d695bdee72d9bbde6ca4545f039"
)
EXPECTED_SOURCE_AMENDMENT_SHA256 = (
    "79d300c3b1b7b6272b26452c016820b31df8430887fa17a3fc669c69fb92a6bf"
)
EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256 = (
    "1ec12b336344f46a2dc9f4429366bbe526d36202b7949293fac55da32eec9b8b"
)
EXPECTED_FEASIBILITY_SUCCESS_SHA256 = (
    "944380e1f8f8d56ab2bcdb15a2461ac9bf6332e1e6d39d3207511dcc535a34cc"
)
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_B1_SAMPLE_SHA256 = (
    "08429d99aa839c0fc087e3d4d4de270c322086287c3814886f2bcd3bf32e7d56"
)
EXPECTED_B1_PROPENSITY_SHA256 = (
    "0aebdbb279c52308140a819c940655e4341524b3160bcc385cfa8a92030b02df"
)
EXPECTED_CHOOSERS = 64_331
EXPECTED_ROWS = 1_017_944
EXPECTED_KIND_DRAWS = 273_483
RANDOMIZATIONS = 4_999
RANDOMIZATION_BATCH = 250
B2_SEED = 2026082201
HORIZONS_HOURS = (6.0, 24.0, 168.0)
HOUR_MS = 3_600_000
PAYOFF_GROUPS = ("costly", "exact_zero", "favorable")

_WORKER_DATA: dict[str, Any] | None = None
_WORKER_PROBABILITY: Any | None = None
_WORKER_SLICES: list[tuple[int, int]] | None = None
_WORKER_SELECTIONS: list[Any] | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--core-code", type=Path)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--source-amendment", type=Path)
    parser.add_argument("--implementation-amendment", type=Path)
    parser.add_argument("--feasibility-root", type=Path)
    parser.add_argument("--core-root", type=Path)
    parser.add_argument("--core-state", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_save_npz(path: Path, **arrays: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: Sequence[str],
    *,
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(fields),
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def command_output(args: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def authenticate_git(repo: Path, script_path: Path) -> str:
    head = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    if command_output(["git", "branch", "--show-current"], cwd=repo) != "main":
        raise RuntimeError("B2 producer requires the main branch")
    if command_output(["git", "status", "--porcelain=v1"], cwd=repo):
        raise RuntimeError("B2 producer requires a clean repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_GIT_BASE, head],
        cwd=repo,
        check=True,
    )
    relative = script_path.resolve().relative_to(repo.resolve()).as_posix()
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=repo,
        check=True,
    )
    producer_commit = command_output(
        ["git", "log", "-1", "--format=%H", "--", relative], cwd=repo
    )
    if not producer_commit:
        raise RuntimeError("B2 producer has no committed Git authority")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", producer_commit, head],
        cwd=repo,
        check=True,
    )
    return producer_commit


def load_core_module(path: Path) -> Any:
    if sha256_file(path) != EXPECTED_CORE_CODE_SHA256:
        raise RuntimeError("Installed dynamic-core producer SHA mismatch")
    spec = importlib.util.spec_from_file_location("certified_dynamic_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load certified dynamic-core producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arrow_numpy(table: Any, name: str, dtype: Any) -> Any:
    import numpy as np

    column = table[name].combine_chunks()
    try:
        values = column.to_numpy(zero_copy_only=False)
    except TypeError:
        values = column.to_numpy()
    return np.asarray(values, dtype=dtype)


def load_inputs(sample: Path, propensity: Path) -> tuple[dict[str, Any], Any]:
    import numpy as np
    import pyarrow.parquet as pq

    sample_table = pq.read_table(
        sample,
        columns=[
            "b1_row_id",
            "chooser_index",
            "sequence_index",
            "utc_ms",
            "kind_draw",
            "current_draw_payoff",
        ],
        use_threads=False,
    )
    propensity_table = pq.read_table(
        propensity, columns=["b1_row_id", "static_propensity"], use_threads=False
    )
    data = {
        "b1_row_id": arrow_numpy(sample_table, "b1_row_id", np.int64),
        "chooser_index": arrow_numpy(sample_table, "chooser_index", np.int64),
        "sequence_index": arrow_numpy(sample_table, "sequence_index", np.int32),
        "utc_ms": arrow_numpy(sample_table, "utc_ms", np.int64),
        "kind_draw": arrow_numpy(sample_table, "kind_draw", np.bool_),
        "current_draw_payoff": arrow_numpy(
            sample_table, "current_draw_payoff", np.float64
        ),
    }
    propensity_ids = arrow_numpy(propensity_table, "b1_row_id", np.int64)
    probability = arrow_numpy(propensity_table, "static_propensity", np.float64)
    expected_ids = np.arange(EXPECTED_ROWS, dtype=np.int64)
    if not np.array_equal(data["b1_row_id"], expected_ids):
        raise RuntimeError("B2 sample row ordering changed")
    if not np.array_equal(propensity_ids, expected_ids):
        raise RuntimeError("B2 propensity row ordering changed")
    if data["chooser_index"].size != EXPECTED_ROWS:
        raise RuntimeError("B2 sample row total changed")
    if int(np.count_nonzero(data["kind_draw"])) != EXPECTED_KIND_DRAWS:
        raise RuntimeError("B2 sample kind-draw total changed")
    if int(np.unique(data["chooser_index"]).size) != EXPECTED_CHOOSERS:
        raise RuntimeError("B2 chooser total changed")
    if np.any(data["utc_ms"] <= 0) or np.any(~np.isfinite(probability)):
        raise RuntimeError("B2 inputs contain invalid values")
    if np.any((probability <= 0.0) | (probability >= 1.0)):
        raise RuntimeError("B2 propensities are outside (0,1)")
    return data, probability


def chooser_slices(chooser: Any) -> list[tuple[int, int]]:
    import numpy as np

    boundaries = np.flatnonzero(np.r_[True, chooser[1:] != chooser[:-1], True])
    return [
        (int(boundaries[index]), int(boundaries[index + 1]))
        for index in range(boundaries.size - 1)
    ]


def event_window_totals(
    times: Any, choices: Any, payoffs: Any, horizons_hours: Sequence[float]
) -> tuple[Any, Any, Any, Any]:
    """Return pooled numerators/denominators and payoff-group totals."""
    import numpy as np

    choices = np.asarray(choices, dtype=bool)
    if choices.ndim == 1:
        choices = choices[None, :]
    simulations, n = choices.shape
    if n == 0 or np.any(np.count_nonzero(choices, axis=1) < 1):
        raise RuntimeError("Every event-window sequence must contain a grant")
    first = np.argmax(choices, axis=1)
    cumulative = np.cumsum(choices, axis=1, dtype=np.int32)
    row = np.arange(simulations, dtype=np.int64)
    numerators = np.zeros((simulations, len(horizons_hours)), dtype=np.int64)
    denominators = np.zeros_like(numerators)
    group_numerators = np.zeros(
        (simulations, len(PAYOFF_GROUPS), len(horizons_hours)), dtype=np.int64
    )
    group_denominators = np.zeros_like(group_numerators)
    first_payoff = np.asarray(payoffs, dtype=np.float64)[first]
    group = np.where(first_payoff < 0.0, 0, np.where(first_payoff > 0.0, 2, 1))
    for horizon_index, hours in enumerate(horizons_hours):
        end = np.searchsorted(
            np.asarray(times, dtype=np.int64),
            np.asarray(times, dtype=np.int64)[first] + int(hours * HOUR_MS),
            side="right",
        ) - 1
        denominator = np.maximum(end - first, 0)
        numerator = np.where(
            denominator > 0,
            cumulative[row, end] - cumulative[row, first],
            0,
        )
        numerators[:, horizon_index] = numerator
        denominators[:, horizon_index] = denominator
        for group_index in range(len(PAYOFF_GROUPS)):
            selected = group == group_index
            group_numerators[selected, group_index, horizon_index] = numerator[selected]
            group_denominators[selected, group_index, horizon_index] = denominator[selected]
    return numerators, denominators, group_numerators, group_denominators


def simulate_batch(
    *,
    data: dict[str, Any],
    probability: Any,
    simulations: int,
    seed_components: Sequence[int],
    progress_label: str,
    slices: list[tuple[int, int]] | None = None,
    selections: list[Any] | None = None,
) -> dict[str, Any]:
    import numpy as np

    rng = np.random.default_rng(np.random.SeedSequence(list(seed_components)))
    total_num = np.zeros((simulations, len(HORIZONS_HOURS)), dtype=np.int64)
    total_den = np.zeros_like(total_num)
    total_group_num = np.zeros(
        (simulations, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)), dtype=np.int64
    )
    total_group_den = np.zeros_like(total_group_num)
    chooser_ranges = slices or chooser_slices(data["chooser_index"])
    if selections is not None and len(selections) != len(chooser_ranges):
        raise RuntimeError("B2 cached-selection count changed")
    for chooser_number, (start, stop) in enumerate(chooser_ranges):
        observed = data["kind_draw"][start:stop]
        n = stop - start
        k = int(np.count_nonzero(observed))
        if selections is None:
            log_odds = np.log(probability[start:stop]) - np.log1p(
                -probability[start:stop]
            )
            selection = conditional_selection_probabilities(log_odds, k)
        else:
            selection = selections[chooser_number]
        remaining = np.full(simulations, k, dtype=np.int32)
        choices = np.zeros((simulations, n), dtype=bool)
        for position in range(n):
            left = n - position
            forced = remaining == left
            probability_now = selection[position, remaining]
            chosen = forced | (
                (remaining > 0) & (rng.random(simulations) < probability_now)
            )
            choices[:, position] = chosen
            remaining -= chosen.astype(np.int32)
        if np.any(remaining != 0) or np.any(
            np.count_nonzero(choices, axis=1) != k
        ):
            raise RuntimeError("B2 conditional sampler failed to preserve chooser totals")
        num, den, group_num, group_den = event_window_totals(
            data["utc_ms"][start:stop],
            choices,
            data["current_draw_payoff"][start:stop],
            HORIZONS_HOURS,
        )
        total_num += num
        total_den += den
        total_group_num += group_num
        total_group_den += group_den
        if (chooser_number + 1) % 10_000 == 0:
            print(
                "B2_RANDOMIZATION_CHOOSER_PROGRESS "
                f"batch={progress_label} "
                f"choosers={chooser_number + 1:,}/{len(chooser_ranges):,}",
                flush=True,
            )
    return {
        "numerators": total_num,
        "denominators": total_den,
        "group_numerators": total_group_num,
        "group_denominators": total_group_den,
    }


def conditional_selection_probabilities(log_odds: Any, kind_total: int) -> Any:
    """Exact sequential probabilities for conditional Bernoulli sampling."""
    import numpy as np

    n = int(log_odds.size)
    k = int(kind_total)
    suffix = np.full((n + 1, k + 1), -np.inf, dtype=np.float64)
    suffix[n, 0] = 0.0
    for position in range(n - 1, -1, -1):
        suffix[position, 0] = 0.0
        for remaining in range(1, min(k, n - position) + 1):
            suffix[position, remaining] = np.logaddexp(
                suffix[position + 1, remaining],
                log_odds[position] + suffix[position + 1, remaining - 1],
            )
    if not np.isfinite(suffix[0, k]):
        raise RuntimeError("B2 conditional normalizer is nonfinite")
    probabilities = np.zeros((n, k + 1), dtype=np.float64)
    for position in range(n):
        for remaining in range(1, min(k, n - position) + 1):
            probabilities[position, remaining] = math.exp(
                min(
                    0.0,
                    log_odds[position]
                    + suffix[position + 1, remaining - 1]
                    - suffix[position, remaining],
                )
            )
    return np.clip(probabilities, 0.0, 1.0)


def initialize_worker(sample: str, propensity: str) -> None:
    import numpy as np

    for variable in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"
    global _WORKER_DATA, _WORKER_PROBABILITY, _WORKER_SLICES, _WORKER_SELECTIONS
    _WORKER_DATA, _WORKER_PROBABILITY = load_inputs(Path(sample), Path(propensity))
    _WORKER_SLICES = chooser_slices(_WORKER_DATA["chooser_index"])
    _WORKER_SELECTIONS = []
    for start, stop in _WORKER_SLICES:
        observed = _WORKER_DATA["kind_draw"][start:stop]
        log_odds = np.log(_WORKER_PROBABILITY[start:stop]) - np.log1p(
            -_WORKER_PROBABILITY[start:stop]
        )
        _WORKER_SELECTIONS.append(
            conditional_selection_probabilities(
                log_odds, int(np.count_nonzero(observed))
            )
        )


def worker_batch(
    start: int,
    stop: int,
    state_text: str,
    config_sha: str,
) -> dict[str, Any]:
    if (
        _WORKER_DATA is None
        or _WORKER_PROBABILITY is None
        or _WORKER_SLICES is None
        or _WORKER_SELECTIONS is None
    ):
        raise RuntimeError("B2 worker was not initialized")
    state = Path(state_text)
    path = state / "randomizations" / f"b2_{start:04d}_{stop - 1:04d}.npz"
    receipt = path.with_suffix(".json")
    if path.exists() or receipt.exists():
        raise RuntimeError(f"B2 worker received existing checkpoint {start}")
    started = time.time()
    result = simulate_batch(
        data=_WORKER_DATA,
        probability=_WORKER_PROBABILITY,
        simulations=stop - start,
        seed_components=(B2_SEED, start, stop),
        progress_label=f"{start + 1}-{stop}",
        slices=_WORKER_SLICES,
        selections=_WORKER_SELECTIONS,
    )
    atomic_save_npz(path, **result)
    saved = {
        "status": "DYNAMIC_B2_RANDOMIZATION_BATCH_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_path": str(path),
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
        "runtime_seconds": time.time() - started,
    }
    atomic_write_json(receipt, saved)
    return saved


def authenticate_checkpoint(
    path: Path, receipt: Path, start: int, stop: int, config_sha: str
) -> dict[str, Any] | None:
    import numpy as np

    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete B2 checkpoint {start}")
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_B2_RANDOMIZATION_BATCH_OK",
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_path": str(path),
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"B2 checkpoint mismatch {start}: {key}")
    arrays = np.load(path)
    expected_shapes = {
        "numerators": (stop - start, len(HORIZONS_HOURS)),
        "denominators": (stop - start, len(HORIZONS_HOURS)),
        "group_numerators": (
            stop - start,
            len(PAYOFF_GROUPS),
            len(HORIZONS_HOURS),
        ),
        "group_denominators": (
            stop - start,
            len(PAYOFF_GROUPS),
            len(HORIZONS_HOURS),
        ),
    }
    for name, shape in expected_shapes.items():
        if arrays[name].shape != shape:
            raise RuntimeError(f"B2 checkpoint array shape mismatch: {name}")
    return saved


def randomization_tail_p(observed: float, simulated: Any) -> tuple[float, float, float]:
    import numpy as np

    lower = (1.0 + int(np.count_nonzero(simulated <= observed))) / (
        simulated.size + 1.0
    )
    upper = (1.0 + int(np.count_nonzero(simulated >= observed))) / (
        simulated.size + 1.0
    )
    return lower, upper, min(1.0, 2.0 * min(lower, upper))


def exact_two_sided_p(observed: float, simulated: Any) -> float:
    return randomization_tail_p(observed, simulated)[2]


def quantile(values: Any, probability: float) -> float:
    import numpy as np

    return float(np.quantile(values, probability, method="linear"))


def make_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.resolve()
    repo = project / "replication_package"
    core_code = (args.core_code or repo / "code/10c_estimate_dynamic_prosociality_core.py").resolve()
    plan = (args.analysis_plan or repo / "docs/dynamic_prosociality_second_wave_analysis_plan.md").resolve()
    amendment = (args.source_amendment or repo / "docs/dynamic_prosociality_second_wave_source_contract_amendment.md").resolve()
    implementation = (
        args.implementation_amendment
        or repo / "docs/dynamic_prosociality_second_wave_implementation_amendment.md"
    ).resolve()
    feasibility = (args.feasibility_root or project / "output/dynamic_second_wave_feasibility_v100/20260822T134125Z").resolve()
    core_root = (args.core_root or project / "output/dynamic_prosociality_core_v102/20260822T022146Z").resolve()
    core_state = (args.core_state or project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE").resolve()
    state = (args.state_root or project / "derived/replication/dynamic_second_wave_b2_v100_PRIVATE").resolve()
    output = (args.output_root or project / "output/dynamic_second_wave_b2_v100").resolve()
    run_id = args.run_id or default_run_id()
    authorities = {
        "script_sha256": sha256_file(script_path),
        "git_head": authenticate_git(repo, script_path),
        "core_code_sha256": sha256_file(core_code),
        "analysis_plan_sha256": sha256_file(plan),
        "source_amendment_sha256": sha256_file(amendment),
        "implementation_amendment_sha256": sha256_file(implementation),
        "feasibility_success_sha256": sha256_file(feasibility / "_SUCCESS.json"),
        "core_success_sha256": sha256_file(core_root / "_SUCCESS.json"),
        "b1_sample_sha256": sha256_file(core_state / "b1_repeat_granter_private.parquet"),
        "b1_propensity_sha256": sha256_file(core_state / "b1_crossfit_propensity_private.parquet"),
    }
    expected = {
        "core_code_sha256": EXPECTED_CORE_CODE_SHA256,
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "source_amendment_sha256": EXPECTED_SOURCE_AMENDMENT_SHA256,
        "implementation_amendment_sha256": EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256,
        "feasibility_success_sha256": EXPECTED_FEASIBILITY_SUCCESS_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "b1_sample_sha256": EXPECTED_B1_SAMPLE_SHA256,
        "b1_propensity_sha256": EXPECTED_B1_PROPENSITY_SHA256,
    }
    for key, value in expected.items():
        if authorities[key] != value:
            raise RuntimeError(f"B2 authority mismatch: {key}")
    config = {
        "script_version": SCRIPT_VERSION,
        **authorities,
        "randomizations": RANDOMIZATIONS,
        "batch_size": RANDOMIZATION_BATCH,
        "seed": B2_SEED,
        "horizons_hours": list(HORIZONS_HOURS),
        "payoff_groups": list(PAYOFF_GROUPS),
    }
    return {
        "project": project,
        "repo": repo,
        "core_code": core_code,
        "plan": plan,
        "amendment": amendment,
        "implementation_amendment": implementation,
        "feasibility": feasibility,
        "core_root": core_root,
        "core_state": core_state,
        "sample": core_state / "b1_repeat_granter_private.parquet",
        "propensity": core_state / "b1_crossfit_propensity_private.parquet",
        "state": state,
        "output": output,
        "run_id": run_id,
        "workers": args.workers,
        "authorities": authorities,
        "config": config,
        "config_sha256": sha256_json(config),
    }


def initialize_state(payload: dict[str, Any]) -> None:
    state = payload["state"]
    state.mkdir(parents=True, exist_ok=True)
    config_path = state / "CONFIG.json"
    expected = {
        "status": "DYNAMIC_B2_PRIVATE_STATE_OK",
        "created_utc": None,
        "config": payload["config"],
        "config_sha256": payload["config_sha256"],
        "privacy": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    if config_path.is_file():
        saved = load_json(config_path)
        if saved.get("config") != expected["config"] or saved.get(
            "config_sha256"
        ) != expected["config_sha256"]:
            raise RuntimeError("B2 private state configuration mismatch")
        print("B2_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
        return
    if any(state.iterdir()):
        raise RuntimeError("Nonempty B2 state root lacks CONFIG.json")
    expected["created_utc"] = utc_now()
    atomic_write_json(config_path, expected)
    print("B2_PRIVATE_STATE_CREATED", flush=True)


def observed_totals(data: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    total_num = np.zeros(len(HORIZONS_HOURS), dtype=np.int64)
    total_den = np.zeros_like(total_num)
    group_num = np.zeros((len(PAYOFF_GROUPS), len(HORIZONS_HOURS)), dtype=np.int64)
    group_den = np.zeros_like(group_num)
    for start, stop in chooser_slices(data["chooser_index"]):
        num, den, gnum, gden = event_window_totals(
            data["utc_ms"][start:stop],
            data["kind_draw"][start:stop],
            data["current_draw_payoff"][start:stop],
            HORIZONS_HOURS,
        )
        total_num += num[0]
        total_den += den[0]
        group_num += gnum[0]
        group_den += gden[0]
    return {
        "numerators": total_num,
        "denominators": total_den,
        "group_numerators": group_num,
        "group_denominators": group_den,
    }


def run_randomizations(payload: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    sample = payload["sample"]
    propensity = payload["propensity"]
    state = payload["state"]
    config_sha = payload["config_sha256"]
    specs: list[tuple[int, int, Path, Path]] = []
    pending: list[tuple[int, int]] = []
    for start in range(0, RANDOMIZATIONS, RANDOMIZATION_BATCH):
        stop = min(start + RANDOMIZATION_BATCH, RANDOMIZATIONS)
        path = state / "randomizations" / f"b2_{start:04d}_{stop - 1:04d}.npz"
        receipt = path.with_suffix(".json")
        specs.append((start, stop, path, receipt))
        if authenticate_checkpoint(path, receipt, start, stop, config_sha) is None:
            pending.append((start, stop))
    print(
        f"B2_RANDOMIZATION_CHECKPOINTS existing={len(specs) - len(pending)} "
        f"pending={len(pending)} workers={payload['workers']}",
        flush=True,
    )
    if pending:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(payload["workers"], len(pending)),
            mp_context=context,
            initializer=initialize_worker,
            initargs=(str(sample), str(propensity)),
        ) as executor:
            futures = {
                executor.submit(worker_batch, start, stop, str(state), config_sha): (
                    start,
                    stop,
                )
                for start, stop in pending
            }
            for future in as_completed(futures):
                saved = future.result()
                print(
                    "B2_RANDOMIZATION_BATCH_COMPLETE "
                    f"start={saved['start']} stop={saved['stop_exclusive']} "
                    f"seconds={saved['runtime_seconds']:.1f}",
                    flush=True,
                )
    arrays: dict[str, list[Any]] = {
        "numerators": [],
        "denominators": [],
        "group_numerators": [],
        "group_denominators": [],
    }
    for start, stop, path, receipt in specs:
        authenticate_checkpoint(path, receipt, start, stop, config_sha)
        loaded = np.load(path)
        for name in arrays:
            arrays[name].append(np.asarray(loaded[name]))
    combined = {name: np.concatenate(parts, axis=0) for name, parts in arrays.items()}
    if combined["numerators"].shape[0] != RANDOMIZATIONS:
        raise RuntimeError("B2 combined randomization total changed")
    return combined


def summarize(observed: dict[str, Any], simulated: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    sim_rates = simulated["numerators"] / simulated["denominators"]
    obs_rates = observed["numerators"] / observed["denominators"]
    horizon_rows: list[dict[str, Any]] = []
    for index, hours in enumerate(HORIZONS_HOURS):
        values = sim_rates[:, index]
        null_mean = float(np.mean(values))
        delta = float(obs_rates[index] - null_mean)
        lower, upper, p_value = randomization_tail_p(
            float(obs_rates[index]), values
        )
        horizon_rows.append(
            {
                "analysis": "B2",
                "horizon_hours": hours,
                "primary": hours == 24.0,
                "observed_numerator": int(observed["numerators"][index]),
                "observed_denominator": int(observed["denominators"][index]),
                "observed_rate": float(obs_rates[index]),
                "null_mean_rate": null_mean,
                "excess_rate": delta,
                "excess_percentage_points": delta * 100.0,
                "lower_tail_plus_one": lower,
                "upper_tail_plus_one": upper,
                "randomization_p_two_sided": p_value,
                "null_p025": quantile(values, 0.025),
                "null_p975": quantile(values, 0.975),
                "excess_reference_interval_95_low": float(
                    obs_rates[index] - quantile(values, 0.975)
                ),
                "excess_reference_interval_95_high": float(
                    obs_rates[index] - quantile(values, 0.025)
                ),
                "randomizations": RANDOMIZATIONS,
                "scope": "repeat granters; first observed grant in locked panel",
            }
        )
    sim_group_rates = np.divide(
        simulated["group_numerators"],
        simulated["group_denominators"],
        out=np.full(simulated["group_numerators"].shape, np.nan, dtype=float),
        where=simulated["group_denominators"] > 0,
    )
    obs_group_rates = np.divide(
        observed["group_numerators"],
        observed["group_denominators"],
        out=np.full(observed["group_numerators"].shape, np.nan, dtype=float),
        where=observed["group_denominators"] > 0,
    )
    group_rows: list[dict[str, Any]] = []
    for group_index, group in enumerate(PAYOFF_GROUPS):
        for horizon_index, hours in enumerate(HORIZONS_HOURS):
            values = sim_group_rates[:, group_index, horizon_index]
            finite = values[np.isfinite(values)]
            observed_rate = float(obs_group_rates[group_index, horizon_index])
            null_mean = float(np.mean(finite))
            group_rows.append(
                {
                    "analysis": "B3_secondary",
                    "first_grant_payoff_group": group,
                    "horizon_hours": hours,
                    "observed_numerator": int(
                        observed["group_numerators"][group_index, horizon_index]
                    ),
                    "observed_denominator": int(
                        observed["group_denominators"][group_index, horizon_index]
                    ),
                    "observed_rate": observed_rate,
                    "null_mean_rate": null_mean,
                    "excess_rate": observed_rate - null_mean,
                    "excess_percentage_points": (observed_rate - null_mean) * 100.0,
                    "randomization_p_two_sided": exact_two_sided_p(
                        observed_rate, finite
                    ),
                    "finite_randomizations": int(finite.size),
                }
            )
    horizon_24 = HORIZONS_HOURS.index(24.0)
    observed_difference = float(
        obs_group_rates[0, horizon_24] - obs_group_rates[2, horizon_24]
    )
    simulated_difference = (
        sim_group_rates[:, 0, horizon_24] - sim_group_rates[:, 2, horizon_24]
    )
    finite_difference = simulated_difference[np.isfinite(simulated_difference)]
    b3 = {
        "analysis": "B3_secondary_costly_vs_favorable",
        "horizon_hours": 24.0,
        "observed_rate_difference": observed_difference,
        "null_mean_rate_difference": float(np.mean(finite_difference)),
        "excess_difference": observed_difference - float(np.mean(finite_difference)),
        "excess_difference_percentage_points": (
            observed_difference - float(np.mean(finite_difference))
        )
        * 100.0,
        "randomization_p_two_sided": exact_two_sided_p(
            observed_difference, finite_difference
        ),
        "null_p025": quantile(finite_difference, 0.025),
        "null_p975": quantile(finite_difference, 0.975),
        "excess_reference_interval_95_low": (
            observed_difference - quantile(finite_difference, 0.975)
        ),
        "excess_reference_interval_95_high": (
            observed_difference - quantile(finite_difference, 0.025)
        ),
        "excess_reference_interval_95_low_pp": (
            observed_difference - quantile(finite_difference, 0.975)
        )
        * 100.0,
        "excess_reference_interval_95_high_pp": (
            observed_difference - quantile(finite_difference, 0.025)
        )
        * 100.0,
        "confirmatory": False,
    }
    primary = next(row for row in horizon_rows if row["primary"])
    return {
        "horizons": horizon_rows,
        "payoff_groups": group_rows,
        "b3_costly_vs_favorable": b3,
        "primary_raw_p_value": primary["randomization_p_two_sided"],
        "primary_excess_percentage_points": primary["excess_percentage_points"],
    }


def manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"_SUCCESS.json", "report_file_hashes.tsv"}:
            rows.append(
                {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "path": path.relative_to(root).as_posix(),
                }
            )
    return rows


def write_results(payload: dict[str, Any], summary: dict[str, Any]) -> Path:
    output_base = payload["output"]
    final = output_base / payload["run_id"]
    if final.exists():
        raise RuntimeError(f"B2 output run already exists: {final}")
    staging = output_base / f".{payload['run_id']}.tmp.{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    write_csv(
        staging / "b2_first_grant_horizons.csv",
        summary["horizons"],
        list(summary["horizons"][0]),
    )
    write_csv(
        staging / "b3_first_grant_payoff_groups.csv",
        summary["payoff_groups"],
        list(summary["payoff_groups"][0]),
    )
    atomic_write_json(staging / "b3_costly_vs_favorable.json", summary["b3_costly_vs_favorable"])
    public_summary = {
        "status": "DYNAMIC_SECOND_WAVE_B2_V100_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "authorities": payload["authorities"],
        "config_sha256": payload["config_sha256"],
        "support": {
            "repeat_granters": EXPECTED_CHOOSERS,
            "opportunities": EXPECTED_ROWS,
            "kind_draws": EXPECTED_KIND_DRAWS,
        },
        "randomizations": RANDOMIZATIONS,
        **summary,
        "privacy": "Aggregate output only; private checkpoints remain on XT_Pro.",
    }
    atomic_write_json(staging / "summary.json", public_summary)
    report = manifest_rows(staging)
    write_csv(
        staging / "report_file_hashes.tsv",
        report,
        ("sha256", "bytes", "path"),
        delimiter="\t",
    )
    success = {
        "status": "DYNAMIC_SECOND_WAVE_B2_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["authorities"]["script_sha256"],
        "git_head": payload["authorities"]["git_head"],
        "analysis_plan_sha256": payload["authorities"]["analysis_plan_sha256"],
        "source_amendment_sha256": payload["authorities"]["source_amendment_sha256"],
        "implementation_amendment_sha256": payload["authorities"][
            "implementation_amendment_sha256"
        ],
        "config_sha256": payload["config_sha256"],
        "primary_raw_p_value": summary["primary_raw_p_value"],
        "primary_excess_percentage_points": summary[
            "primary_excess_percentage_points"
        ],
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(report),
        "account_level_output": False,
        "patron_profile_input_read": False,
    }
    atomic_write_json(staging / "_SUCCESS.json", success)
    os.replace(staging, final)
    return final


def execute(payload: dict[str, Any]) -> Path:
    started = time.time()
    initialize_state(payload)
    data, _ = load_inputs(payload["sample"], payload["propensity"])
    print("B2_OBSERVED_EVENT_STATISTIC_BEGIN", flush=True)
    observed = observed_totals(data)
    print("B2_OBSERVED_EVENT_STATISTIC_OK", flush=True)
    simulated = run_randomizations(payload)
    summary = summarize(observed, simulated)
    final = write_results(payload, summary)
    print(f"DYNAMIC_SECOND_WAVE_B2_V100_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final


def self_test() -> None:
    import itertools
    import numpy as np

    odds = np.log(np.array([0.2, 0.4, 0.6, 0.8])) - np.log1p(
        -np.array([0.2, 0.4, 0.6, 0.8])
    )
    selection = conditional_selection_probabilities(odds, 2)
    combinations = list(itertools.combinations(range(4), 2))
    weights = np.array([math.exp(sum(odds[list(combo)])) for combo in combinations])
    weights /= weights.sum()
    exact_first = sum(weight for combo, weight in zip(combinations, weights) if 0 in combo)
    assert abs(selection[0, 2] - exact_first) < 1e-12

    times = np.array([0, HOUR_MS, 2 * HOUR_MS, 30 * HOUR_MS], dtype=np.int64)
    choices = np.array([[0, 1, 1, 0], [1, 0, 1, 0]], dtype=bool)
    payoff = np.array([-1.0, 2.0, -2.0, 1.0])
    num, den, group_num, group_den = event_window_totals(
        times, choices, payoff, (6.0, 24.0)
    )
    assert num.tolist() == [[1, 1], [1, 1]]
    assert den.tolist() == [[1, 1], [2, 2]]
    assert group_den[0, 2, 0] == 1
    assert group_den[1, 0, 0] == 2
    assert exact_two_sided_p(2.0, np.array([0.0, 1.0, 2.0])) == 1.0
    print("DYNAMIC_SECOND_WAVE_B2_V100_SELF_TEST_OK")


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_B2_V100_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("git_head:", payload["authorities"]["git_head"])
    print("analysis_plan_sha256:", payload["authorities"]["analysis_plan_sha256"])
    print("source_amendment_sha256:", payload["authorities"]["source_amendment_sha256"])
    print(
        "implementation_amendment_sha256:",
        payload["authorities"]["implementation_amendment_sha256"],
    )
    print("repeat_granters:", f"{EXPECTED_CHOOSERS:,}")
    print("opportunities:", f"{EXPECTED_ROWS:,}")
    print("randomizations:", f"{RANDOMIZATIONS:,}")
    print("workers:", payload["workers"])
    print("state_root:", payload["state"])
    print("output_root:", payload["output"])


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8")
    payload = make_payload(args, Path(__file__).resolve())
    print_plan(payload)
    if not args.execute:
        print("No outcome was estimated. Re-run with --execute.")
        return
    execute(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMIC_SECOND_WAVE_B2_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
