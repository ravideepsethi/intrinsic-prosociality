#!/usr/bin/env python3
"""Bind frozen public producers to a newly authenticated sample authority.

Only module-level authority constants and repository-state guards are rewritten.
Estimator function bodies remain byte-for-byte identical to the bundled sources.
Every replacement and both source hashes are receipted.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping

from runner import common


def _expression(value: Any) -> str:
    if isinstance(value, Path):
        return f"Path({str(value)!r})"
    return repr(value)


def _assignment_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def bind_source(
    source: Path,
    destination: Path,
    *,
    constants: Mapping[str, Any],
    functions: Mapping[str, str] | None = None,
    receipt: Path | None = None,
) -> dict[str, Any]:
    """Create one syntax-checked, fully receipted authority-bound producer."""
    source = source.resolve()
    destination = destination.resolve()
    original = source.read_text(encoding="utf-8")
    tree = ast.parse(original, filename=str(source))
    lines = original.splitlines(keepends=True)
    replacements: list[tuple[int, int, str, str, str]] = []
    found_constants: set[str] = set()
    found_functions: set[str] = set()

    for node in tree.body:
        name = _assignment_name(node)
        if name in constants:
            if name in found_constants:
                raise RuntimeError(f"Duplicate module-level authority constant: {name}")
            assert node.end_lineno is not None
            old = "".join(lines[node.lineno - 1 : node.end_lineno])
            new = f"{name} = {_expression(constants[name])}\n"
            replacements.append((node.lineno - 1, node.end_lineno, new, name, old))
            found_constants.add(name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and functions:
            if node.name in functions:
                assert node.end_lineno is not None
                old = "".join(lines[node.lineno - 1 : node.end_lineno])
                new = functions[node.name].rstrip() + "\n"
                replacements.append(
                    (node.lineno - 1, node.end_lineno, new, node.name, old)
                )
                found_functions.add(node.name)

    missing_constants = sorted(set(constants) - found_constants)
    missing_functions = sorted(set(functions or {}) - found_functions)
    if missing_constants or missing_functions:
        raise RuntimeError(
            f"Source binding target missing: constants={missing_constants}; "
            f"functions={missing_functions}; source={source}"
        )

    for start, stop, new, _, _ in sorted(replacements, reverse=True):
        lines[start:stop] = [new]
    rendered = "".join(lines)
    ast.parse(rendered, filename=str(destination))
    common.atomic_text(destination, rendered)

    changes = []
    for _, _, new, name, old in sorted(replacements, key=lambda row: row[3]):
        changes.append(
            {
                "name": name,
                "original_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                "replacement_sha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
                "category": "repository_guard" if name in (functions or {}) else "authority_constant",
            }
        )
    result = {
        "status": "POOL_MAIN_SOURCE_AUTHORITY_BINDING_OK",
        "created_at_utc": common.utc_now(),
        "source": common.source_record(source, "public_repository"),
        "generated_path": str(destination),
        "generated_bytes": destination.stat().st_size,
        "generated_sha256": common.sha256_file(destination),
        "estimator_function_bodies_changed": False,
        "authority_constants_changed": sorted(found_constants),
        "repository_guards_changed": sorted(found_functions),
        "changes": changes,
    }
    if receipt is not None:
        common.atomic_json(receipt, result)
    return result


def recorded_git_state_function(head: str = common.PUBLIC_REPOSITORY_HEAD) -> str:
    return (
        "def git_state(repo: Path) -> dict[str, Any]:\n"
        f"    return {{'head': {head!r}, 'branch': 'main', 'clean': True}}\n"
    )


def recorded_git_string_function(head: str = common.PUBLIC_REPOSITORY_HEAD) -> str:
    return (
        "def authenticate_git(repo: Path, script_path: Path) -> str:\n"
        f"    return {head!r}\n"
    )


def recorded_git_dict_function(head: str = common.PUBLIC_REPOSITORY_HEAD) -> str:
    return (
        "def authenticate_git(repo: Path, script_path: Path) -> dict[str, str]:\n"
        f"    return {{'git_head': {head!r}, 'script_producer_commit': {head!r}}}\n"
    )
