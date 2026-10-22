#!/usr/bin/env python3
"""Explicit, recorded worker-scheduling override; authenticated analysis unchanged."""
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
import datetime,hashlib,importlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE=ROOT/'KAC_Repetition_Sensitivity_v1_0_1'
EXPECTED_BASE_MANIFEST='2a8e7cbc781699b5eaafffe22b7c866beb114434ac19462b4e53ccd50ed7ff52'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify():
    manifest=json.loads((ROOT/'LAUNCHER_MANIFEST.json').read_text())
    for row in manifest['files']:
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe package member')
        p=ROOT/relative
        if not p.is_file() or sha(p)!=row['sha256']:raise RuntimeError('No-wait package checksum failed: '+row['path'])
    if sha(BASE/'PACKAGE_MANIFEST.json')!=EXPECTED_BASE_MANIFEST:
        raise RuntimeError('Unexpected analysis package manifest')

def immediate_slots(budget,want,minimum=1):
    """Honor this job's limit without inspecting or waiting for other processes."""
    if not 1<=budget<=10 or minimum<1 or want<minimum or budget<minimum:
        raise ValueError('Invalid per-run worker request')
    return min(budget,want),[]

def install():
    sys.path.insert(0,str(BASE))
    modules={n:importlib.import_module(n) for n in ('util','run','history','handoff','repetition')}
    for mod in modules.values():
        if Path(mod.__file__).resolve().parent!=BASE:
            raise RuntimeError('Unexpected analysis module location')
        mod.slots=immediate_slots
    core=modules['run']
    original_export=core.export
    def export_with_policy(run,desktop,tag):
        report=Path(run)/'report/resource_policy'
        policy=dict(mode='USER_REQUESTED_NO_WORKER_CAPACITY_WAIT',
            recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            process_reservations_checked=False,worker_capacity_wait=False,
            limit_scope='this job only; existing other jobs are not counted',
            per_run_worker_limits_unchanged=True,memory_limits_unchanged=True,
            duplicate_run_locks_unchanged=True,integrity_checks_unchanged=True,
            scientific_package_manifest_sha256=EXPECTED_BASE_MANIFEST,
            scientific_cache_keys_unchanged=True,
            launcher_manifest_sha256=sha(ROOT/'LAUNCHER_MANIFEST.json'))
        core.js(report/'POLICY.json',policy)
        # Retain the complete executed wrapper and its manifest in each archive.
        for name in ('no_wait.py','RUN_NOW.command','README.md','LAUNCHER_MANIFEST.json'):
            core.textfile(report/name,(ROOT/name).read_text())
        original_export(run,desktop,tag)
    core.export=export_with_policy
    return modules

def test_policy(modules):
    from unittest.mock import patch
    with patch.object(modules['util'],'reservations',side_effect=AssertionError('Must not inspect other jobs')):
        with patch.object(modules['util'].time,'sleep',side_effect=AssertionError('Must not wait')):
            for mod in modules.values():
                assert mod.slots(10,4)==(4,[])
                assert mod.slots(2,4)==(2,[])
                assert mod.slots(10,1)==(1,[])
    assert modules['run'].package_check()==EXPECTED_BASE_MANIFEST
    print('NO_WAIT_TEST_OK: no reservations or sleep; per-run limits retained; base manifest unchanged.',flush=True)

def main():
    verify();modules=install()
    if '--self-test' in sys.argv:test_policy(modules)
    elif '--help' not in sys.argv:
        print('NO_WAIT_MODE: starting without worker-capacity reservation; per-run limits, memory caps, and duplicate-run locks retained.',flush=True)
    modules['run'].main()

if __name__=='__main__':main()
