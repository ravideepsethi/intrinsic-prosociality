#!/usr/bin/env python3
"""Render an authenticated source with narrowly declared authority changes."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from runner import common
from runner.bind_source import bind_source


def retarget_source(
    source: Path,
    destination: Path,
    *,
    constants: Mapping[str, Any],
    exact_replacements: Sequence[tuple[str, str, str]] = (),
    receipt: Path,
) -> dict[str, Any]:
    """Bind constants, then make asserted one-for-one semantic-label/gate edits.

    Every exact replacement must occur once.  The original source is retained in
    the transfer package, and the receipt records hashes of both sides of every
    edit.  This deliberately cannot perform regex or unbounded substitutions.
    """
    intermediate = destination.with_suffix(destination.suffix + ".constants")
    constant_receipt = receipt.with_suffix(receipt.suffix + ".constants")
    bound = bind_source(
        source,
        intermediate,
        constants=constants,
        receipt=constant_receipt,
    )
    rendered = intermediate.read_text(encoding="utf-8")
    changes: list[dict[str, Any]] = []
    for label, old, new in exact_replacements:
        count = rendered.count(old)
        if count != 1:
            raise RuntimeError(
                f"Exact retarget rule {label!r} matched {count} times; expected one"
            )
        rendered = rendered.replace(old, new, 1)
        changes.append(
            {
                "label": label,
                "category": "sample_reset_gate_or_label",
                "old_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                "new_sha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
            }
        )
    ast.parse(rendered, filename=str(destination))
    common.atomic_text(destination, rendered)
    intermediate.unlink()
    constant_receipt.unlink()
    result = {
        "status": "POOL_MAIN_WAVE2B2B1_SOURCE_RETARGET_OK",
        "created_at_utc": common.utc_now(),
        "source": common.source_record(source, "recovered_frozen_producer"),
        "generated_path": str(destination),
        "generated_bytes": destination.stat().st_size,
        "generated_sha256": common.sha256_file(destination),
        "authority_constants_changed": bound["authority_constants_changed"],
        "function_bodies_changed": bool(changes),
        "estimator_equations_changed": False,
        "only_declared_sample_gates_or_labels_changed": True,
        "exact_changes": changes,
    }
    common.atomic_json(receipt, result)
    return result


def write_package_manifest(root: Path) -> Path:
    manifest = root / "PACKAGE_CONTENTS.sha256"
    rows = common.output_manifest(root, exclude=[manifest])
    common.atomic_text(
        manifest,
        "".join(f"{row['sha256']}  ./{row['relative_path']}\n" for row in rows),
    )
    return manifest
