"""Load unchanged pure functions from the frozen August acquisition source.

The original network runner uses requests and a multi-machine acquisition plan.
Only its schema and named normalization helpers are loaded here. The new small
fetch uses Python's HTTPS client, so it requires no environment installation.
"""
import ast
from pathlib import Path
from types import ModuleType

SOURCE = Path(__file__).resolve().parents[1] / "source/profile_fetcher_v100.py"
FUNCTIONS = {
    "utc_now", "iso_from_epoch", "sha256_bytes", "sha256_text", "sha256_file",
    "atomic_write_bytes", "atomic_write_text", "atomic_write_json", "atomic_write_parquet",
    "canonical_json", "norm_user", "nullable_int", "nullable_bool", "nullable_text",
    "profile_value", "normalized_row", "json_type", "pointer_escape", "inventory_json",
    "write_key_inventory", "retry_after_seconds", "safe_headers", "validate_payload",
}
CONSTANTS = {"NORMALIZED_SCHEMA", "SENSITIVE_RESPONSE_HEADERS"}
tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
nodes = []
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.Import) and any(x.name == "requests" for x in node.names):
            continue
        nodes.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
        nodes.append(node)
    elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets):
        nodes.append(node)
if {n.name for n in nodes if isinstance(n, ast.FunctionDef)} != FUNCTIONS:
    raise RuntimeError("Frozen normalizer function inventory differs")
frozen = ModuleType("frozen_profile_normalizer")
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), frozen.__dict__)
