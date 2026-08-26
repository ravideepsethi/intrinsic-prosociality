#!/usr/bin/env python3
"""Attempt and disclose the C12 chooser-rating-band model omitted by v1.0.2.

The v1.0.2 estimator silently skipped any subgroup below its 1,000-row or
100-cluster eligibility rule.  This supplement attempts the remaining 2400+
band under the same strict/extended numerical policy.  If the common estimator
rejects it for low support or nonidentification, that failure is retained as a
model-attempt record instead of being omitted.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import campaign1_c12_v102 as c12
import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.3"
SUPPLEMENT_MODEL = "C12_primary_by_chooser_rating_band_3"


def supplement(*, model_cache: Path, public_stage: Path) -> dict[str, Any]:
    started = time.time()
    if not model_cache.is_file():
        raise RuntimeError(f"C12 model cache is missing: {model_cache}")
    results_path = public_stage / "c12_results.json"
    summary_path = public_stage / "summary.json"
    if not results_path.is_file() or not summary_path.is_file():
        raise RuntimeError("Authenticated v1.0.2 C12 public results are incomplete")

    prior_results_sha256 = common.sha256_file(results_path)
    prior_summary_sha256 = common.sha256_file(summary_path)
    result = common.load_json(results_path)
    summary = common.load_json(summary_path)
    existing_attempts = list(result.get("model_attempts", []))
    existing_models = list(result.get("models", []))
    if any(row.get("model") == SUPPLEMENT_MODEL for row in existing_attempts):
        raise RuntimeError("C12 2400+ supplement was already present in the v1.0.2 evidence")
    if int(result.get("model_attempts_total", -1)) != len(existing_attempts):
        raise RuntimeError("C12 v1.0.2 model-attempt count is inconsistent")

    data = c12._load_model(model_cache)
    np = common.import_numpy()
    decile = data["experience_decile"]
    sample = ((decile <= 2) | (decile >= 9)) & (data["chooser_rating_band"] == 3)
    low = (decile <= 2).astype(float)
    rows, attempt = c12._attempt_model(
        data=data,
        sample=sample,
        exposures={"low_deciles_1_2_minus_high_deciles_9_10": low},
        label=SUPPLEMENT_MODEL,
        epistemic_label="X",
        analysis_role="exploratory_heterogeneity",
    )
    for row in rows:
        row["heterogeneity_dimension"] = "chooser_rating_band"
        row["heterogeneity_value"] = 3
        row["rating_band_definition"] = "2400+"
        row["v103_supplement"] = True
    attempt["heterogeneity_dimension"] = "chooser_rating_band"
    attempt["heterogeneity_value"] = 3
    attempt["rating_band_definition"] = "2400+"
    attempt["v103_supplement"] = True

    result["models"] = existing_models + rows
    result["model_attempts"] = existing_attempts + [attempt]
    result["model_attempts_total"] = len(result["model_attempts"])
    result["models_estimated"] = sum(
        bool(row.get("numerical_estimate_emitted"))
        for row in result["model_attempts"]
    )
    result["extended_absorption_successes"] = sum(
        row.get("final_status") == "ESTIMATED_EXTENDED_ABSORPTION"
        for row in result["model_attempts"]
    )
    result["retained_model_failures"] = sum(
        row.get("numerical_estimate_emitted") is not True
        for row in result["model_attempts"]
    )
    result["status"] = (
        "C12_RECIPIENT_EXPERIENCE_ESTIMATION_COMPLETE"
        if result["retained_model_failures"] == 0
        else "C12_RECIPIENT_EXPERIENCE_COMPLETED_WITH_RETAINED_MODEL_FAILURES"
    )
    result["all_chooser_rating_bands_attempted"] = True
    result["v103_supplement"] = {
        "model": SUPPLEMENT_MODEL,
        "reason": "v1.0.2 silently skipped subgroups below its eligibility threshold",
        "selection_on_result": False,
        "requested_rows": attempt["requested_rows"],
        "requested_chooser_clusters": attempt["requested_chooser_clusters"],
        "final_status": attempt["final_status"],
        "numerical_estimate_emitted": attempt["numerical_estimate_emitted"],
        "prior_results_sha256": prior_results_sha256,
        "prior_summary_sha256": prior_summary_sha256,
    }

    summary.update(
        {
            "status": "CAMPAIGN1_C12_V103_COMPLETE_ALL_BANDS_ATTEMPTED",
            "result_status": result["status"],
            "model_attempts_total": result["model_attempts_total"],
            "models_estimated": result["models_estimated"],
            "extended_absorption_successes": result["extended_absorption_successes"],
            "retained_model_failures": result["retained_model_failures"],
            "all_chooser_rating_bands_attempted": True,
            "v102_primary_numerical_estimate_changed": False,
            "v103_supplement_model": SUPPLEMENT_MODEL,
            "v103_supplement_final_status": attempt["final_status"],
            "v103_supplement_requested_rows": attempt["requested_rows"],
            "v103_supplement_requested_chooser_clusters": attempt[
                "requested_chooser_clusters"
            ],
            "v103_supplement_runtime_seconds": time.time() - started,
            "v103_disposition": (
                "AUTHENTICATED_V102_RESULTS_PLUS_EXPLICIT_2400PLUS_ATTEMPT"
            ),
        }
    )
    common.atomic_json(results_path, result)
    common.atomic_json(summary_path, summary)
    common.write_csv(public_stage / "c12_models.csv", result["models"])
    common.write_csv(public_stage / "c12_model_attempts.csv", result["model_attempts"])
    common.atomic_json(public_stage / "c12_v103_supplement.json", result["v103_supplement"])
    return summary


def self_test() -> None:
    if SUPPLEMENT_MODEL != "C12_primary_by_chooser_rating_band_3":
        raise RuntimeError("C12 supplement model-name self-test failed")
    if c12.STRICT_ABSORPTION_TOLERANCE != 1e-9:
        raise RuntimeError("C12 strict numerical policy changed")
    if c12.EXTENDED_ABSORPTION_TOLERANCE != 1e-7:
        raise RuntimeError("C12 extended numerical policy changed")
    print("CAMPAIGN1_C12_SUPPLEMENT_V103_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
