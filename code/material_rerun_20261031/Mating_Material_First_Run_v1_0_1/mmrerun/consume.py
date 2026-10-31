"""Explicit new-input contract for downstream adapters, never an old READY file."""
from pathlib import Path
from .io import require, load, verify
from .material import RULE


def authenticated_paths(manifest, family, verify_hashes=True):
    require(family in ("main", "all_source"), "Unknown dataset family")
    m=load(manifest)
    require(m.get("contract")=="MATING_MATERIAL_FIRST_RUN_V1" and m.get("rule")==RULE,
            "Wrong material-restricted contract")
    require(m.get("excluded_from_decisions_not_chronology") is True,"Invalid chronology policy")
    records=m["datasets"][family]
    require(records and len({r["month"] for r in records})==len(records),"Invalid month inventory")
    if verify_hashes:
        for r in records:verify(r)
    return [Path(r["path"]) for r in sorted(records,key=lambda r:r["month"])]
