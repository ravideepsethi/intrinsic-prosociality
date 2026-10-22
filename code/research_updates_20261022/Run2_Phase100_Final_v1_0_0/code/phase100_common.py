"""75% release; upstream code and feature-cache definitions remain unchanged."""
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
VERSION='1.0.0'
COHORTS=('new_phase100','increment_75_100','new_phase75','old_author_clean','pooled')

def threshold(percent):
    if percent not in (10,25,50,75):raise ValueError('Expected a finite published phase boundary')
    return ((1<<256)*percent//100).to_bytes(32,'big')

def selection_sql(percent,alias='f'):
    if percent not in (10,25,50,75,100):raise ValueError('Unknown published phase')
    return ('NOT '+alias+'.previous_frame'+
        (f" AND {alias}.retrieval_rank<from_hex('{threshold(percent).hex()}')" if percent<100 else ''))

def verify_package():
    for line in (RELEASE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);io.checked(io.child(RELEASE,name),digest)
    env_common.verify_package()

def audit_quarantine(a,up,phase,coverage,root,conf,memory):
    from phase100_recovery import audit_quarantine as audited
    return audited(a,up,phase,coverage,root,conf,memory)
