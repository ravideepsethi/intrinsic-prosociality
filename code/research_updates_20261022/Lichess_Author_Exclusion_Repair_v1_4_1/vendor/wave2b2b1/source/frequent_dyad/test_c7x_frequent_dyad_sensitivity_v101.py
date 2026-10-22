#!/usr/bin/env python3
"""Synthetic end-to-end test for C7X frequent-dyad sensitivity v1.0.1."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
MAIN = HERE / "c7x_frequent_dyad_sensitivity_v101.py"
VERIFY = HERE / "verify_c7x_frequent_dyad_sensitivity_v101.py"
MODELS = (
    "chooser_context_hdfe_chooser_cluster",
    "directed_pair_context_fe_chooser_cluster",
    "directed_pair_context_fe_unordered_pair_cluster",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_fixture(root: Path) -> tuple[Path, Path, Path, dict[str, int]]:
    rng = random.Random(20260904)
    classification_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    flag_rows: list[dict[str, Any]] = []
    pair_counts = (4, 8, 12)
    benefactor_rows = 0
    claimer_rows = 0
    benefactor_kind = 0
    claimer_kind = 0
    row_index = 0
    for chooser in range(1, 201):
        for opponent_slot, pair_games in enumerate(pair_counts):
            opponent = 100_000 + chooser * 10 + opponent_slot
            pair_hash = 1_000_000 + chooser * 10 + opponent_slot
            arm_sequence = [0, 0, 1, 1]
            rng.shuffle(arm_sequence)
            for repetition in range(4):
                arm = arm_sequence[repetition]
                probability = (
                    0.07
                    + 0.23 * arm
                    + 0.035 * (chooser % 5 == 0)
                    + 0.015 * (repetition == 0)
                )
                outcome = int(rng.random() < probability)
                game_id = f"g{row_index:06d}"
                context = {
                    "game_id": game_id,
                    "chooser_id": chooser,
                    "opponent_id": opponent,
                    "latest_prior_arm": arm,
                    "row_hash": 10_000_000 + row_index,
                    "pair_hash": pair_hash,
                    "eval_bin": rng.randrange(10),
                    "speed_code": rng.randrange(6),
                    "month_code": rng.randrange(24),
                    "hour_of_week": rng.randrange(168),
                    "ply_band": rng.randrange(8),
                    "draw_payoff": rng.gauss(0.0, 1.0),
                    "win_premium": rng.gauss(0.0, 1.0),
                    "chooser_clock": rng.uniform(1.0, 240.0),
                    "opponent_clock": (
                        None if row_index % 97 == 0 else rng.uniform(0.0, 120.0)
                    ),
                    "chooser_elo": rng.uniform(900.0, 2600.0),
                    "opponent_elo": rng.uniform(900.0, 2600.0),
                    "chooser_rd": rng.uniform(30.0, 180.0),
                    "opponent_rd": rng.uniform(30.0, 180.0),
                    "tournament": float(rng.random() < 0.12),
                }
                classification_rows.append(context)
                stage_rows.append(
                    {
                        "game_id": game_id,
                        "chooser_user_id": chooser,
                        "disconnected_user_id": opponent,
                        "outcome_kind_draw": outcome,
                    }
                )
                flag_rows.append(
                    {
                        "game_id": game_id,
                        "latest_prior_arm": arm,
                        "pair_games_24m": pair_games,
                        "dyad_ge_2": pair_games >= 2,
                        "dyad_ge_3": pair_games >= 3,
                        "dyad_ge_5": pair_games >= 5,
                        "dyad_ge_10": pair_games >= 10,
                    }
                )
                if arm:
                    benefactor_rows += 1
                    benefactor_kind += outcome
                else:
                    claimer_rows += 1
                    claimer_kind += outcome
                row_index += 1

    classification = root / "c7x_classification_private.parquet"
    write_parquet(classification, classification_rows)
    stage_root = root / "stage07"
    write_parquet(stage_root / "month=2023-11/analysis_panel.parquet", stage_rows)
    (stage_root / "_SUCCESS.json").write_text(
        json.dumps({"status": "SYNTHETIC_STAGE07_OK"}) + "\n", encoding="utf-8"
    )
    frequency_state = root / "frequency_state"
    flags = frequency_state / "c7x_frequency_flags_private.parquet"
    write_parquet(flags, flag_rows)
    receipt = {
        "status": "C7X_FREQUENT_DYAD_FLAGS_PRIVATE_OK",
        "classification_sha256": sha256_file(classification),
        "rows": row_index,
        "output_bytes": flags.stat().st_size,
        "output_sha256": sha256_file(flags),
    }
    (frequency_state / "c7x_frequency_flags_receipt.json").write_text(
        json.dumps(receipt) + "\n", encoding="utf-8"
    )
    expected = {
        "rows": row_index,
        "benefactor_rows": benefactor_rows,
        "claimer_rows": claimer_rows,
        "benefactor_kind": benefactor_kind,
        "claimer_kind": claimer_kind,
    }
    return stage_root, classification, frequency_state, expected


def test_output(output: Path, expected: dict[str, int]) -> None:
    raw = {row["sample"]: row for row in csv_rows(output / "raw_rate_sensitivity.csv")}
    full = raw["all"]
    observed_full = (
        int(full["observations"]),
        int(full["benefactor_observations"]),
        int(full["benefactor_kind_draws"]),
        int(full["claimer_observations"]),
        int(full["claimer_kind_draws"]),
    )
    wanted_full = (
        expected["rows"],
        expected["benefactor_rows"],
        expected["benefactor_kind"],
        expected["claimer_rows"],
        expected["claimer_kind"],
    )
    if observed_full != wanted_full:
        raise RuntimeError(f"Synthetic raw baseline mismatch: {observed_full}")
    expected_sample_sizes = {
        "all": 2400,
        "pair_lt_3": 0,
        "pair_lt_5": 800,
        "pair_lt_10": 1600,
        "pair_eq_2": 0,
        "pair_3_4": 800,
        "pair_5_9": 800,
        "pair_ge_10": 800,
    }
    observed_sample_sizes = {
        key: int(row["observations"]) for key, row in raw.items()
    }
    if observed_sample_sizes != expected_sample_sizes:
        raise RuntimeError(f"Synthetic sample sizes changed: {observed_sample_sizes}")

    fixed = {
        (row["sample"], row["model"]): row
        for row in csv_rows(output / "fixed_effect_sensitivity.csv")
    }
    for model in MODELS:
        row = fixed[("all", model)]
        if row["status"] != "ESTIMATED":
            raise RuntimeError(f"Synthetic full model was not estimated: {row}")
        if not math.isfinite(float(row["benefactor_effect_pp"])):
            raise RuntimeError(f"Synthetic coefficient is non-finite: {row}")
    beta_chooser_cluster = float(
        fixed[("all", MODELS[1])]["benefactor_effect_pp"]
    )
    beta_pair_cluster = float(
        fixed[("all", MODELS[2])]["benefactor_effect_pp"]
    )
    if abs(beta_chooser_cluster - beta_pair_cluster) > 1e-10:
        raise RuntimeError("Clustering changed the synthetic directed-pair coefficient")
    for model in MODELS:
        if fixed[("pair_eq_2", model)]["status"] != "NO_WITHIN_GROUP_ARM_VARIATION":
            raise RuntimeError("Empty synthetic exact-two sample should be unidentified")
    baseline = json.loads(
        (output / "baseline_reproduction.json").read_text(encoding="utf-8")
    )
    if baseline.get("exact_authoritative_model_reproduction_pass") is not None:
        raise RuntimeError("Synthetic run must not claim production baseline reproduction")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="c7x_frequency_sensitivity_v101_test_") as tmp:
        root = Path(tmp)
        stage_root, classification, frequency_state, expected = make_fixture(root)
        output_root = root / "output"
        pointer = root / "execution.json"
        command = [
            sys.executable,
            str(MAIN),
            "--execute",
            "--project-root", str(root),
            "--stage07-root", str(stage_root),
            "--stage07-success-sha256", "",
            "--c7x-classification", str(classification),
            "--c7x-sha256", "",
            "--frequency-state-root", str(frequency_state),
            "--output-root", str(output_root),
            "--execution-pointer", str(pointer),
            "--temp-directory", str(root / "temp"),
            "--run-id", "synthetic",
            "--threads", "2",
            "--memory-limit", "512MB",
            "--expected-rows", str(expected["rows"]),
            "--expected-benefactor-rows", str(expected["benefactor_rows"]),
            "--expected-claimer-rows", str(expected["claimer_rows"]),
            "--expected-benefactor-kind", str(expected["benefactor_kind"]),
            "--expected-claimer-kind", str(expected["claimer_kind"]),
            "--allow-incomplete-months",
            "--synthetic-test-mode",
        ]
        log = run(command)
        output = output_root / "synthetic"
        test_output(output, expected)
        verify_log = run(
            [
                sys.executable,
                str(VERIFY),
                "--output-dir", str(output),
                "--expected-rows", str(expected["rows"]),
                "--expected-benefactor-rows", str(expected["benefactor_rows"]),
                "--expected-claimer-rows", str(expected["claimer_rows"]),
                "--expected-benefactor-kind", str(expected["benefactor_kind"]),
                "--expected-claimer-kind", str(expected["claimer_kind"]),
                "--synthetic-test-mode",
            ]
        )
        if STATUS_MARKER not in log:
            raise RuntimeError("Synthetic success marker missing")
        if "INDEPENDENT_VERIFICATION_OK" not in verify_log:
            raise RuntimeError("Synthetic independent verification marker missing")
    print("C7X_FREQUENT_DYAD_SENSITIVITY_V101_SYNTHETIC_END_TO_END_OK")
    return 0


STATUS_MARKER = "C7X_FREQUENT_DYAD_SENSITIVITY_V101_OK"


if __name__ == "__main__":
    raise SystemExit(main())
