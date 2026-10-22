"""50% release; upstream code and feature-cache definitions remain unchanged."""
from pathlib import Path
import sys,contextlib
RELEASE=Path(__file__).resolve().parents[1]
ENV=RELEASE/'vendor_env102'
sys.path.insert(0,str(ENV/'code'))
import env_common
from env_common import *
from phase_features import *
# Star imports above include upstream PACKAGE; retain it for cache definitions.
RELEASE=Path(__file__).resolve().parents[1]
ENV=RELEASE/'vendor_env102'
ENTRY=ENV/'vendor/entry100'
UPSTREAM=ENTRY/'vendor/phase122'
VERSION='1.0.1'
COHORTS=('new_phase50','increment_25_50','new_phase25','old_author_clean','pooled')

def verify_package():
    for line in (RELEASE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);io.checked(io.child(RELEASE,name),digest)
    env_common.verify_package()

def audit_quarantine(a,up,phase,coverage,root,conf,memory):
    from phase50_recovery import audit_quarantine as audited
    return audited(a,up,phase,coverage,root,conf,memory)
