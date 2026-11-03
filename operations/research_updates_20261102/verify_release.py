#!/usr/bin/env python3
"""Verify public bytes, syntax, and aggregate reconciliations; no research data."""
import ast
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
TAG='research_updates_20261102'
MAN=ROOT/'manifests'/TAG
AUDIT=ROOT/'results'/TAG/'closing_audit'

def require(ok,message):
    if not ok: raise ValueError(message)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):
    with p.open(newline='') as f:return list(csv.DictReader(f))
def close(x,y):return math.isclose(float(x),float(y),rel_tol=1e-11,abs_tol=1e-11)

def verify():
    expected={}
    for line in (MAN/'PUBLIC_SHA256SUMS.txt').read_text().splitlines():
        digest,name=line.split('  ',1)
        path=ROOT/name
        require(name not in expected,'Duplicate inventory path')
        require(path.resolve().is_relative_to(ROOT) and not path.is_symlink(),'Unsafe path')
        require(path.is_file() and sha(path)==digest,'Hash mismatch: '+name)
        expected[name]=digest
    actual={'README.md'}
    for category in ['code','docs','manifests','operations','results']:
        for p in (ROOT/category/TAG).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.name!='PUBLIC_SHA256SUMS.txt':
                actual.add(p.relative_to(ROOT).as_posix())
    require(actual==set(expected),'Publication inventory differs')
    packages=json.loads((MAN/'SOURCE_PACKAGE_INDEX.json').read_text())
    for package in packages:
        manifest=json.loads((ROOT/package['manifest']).read_text())
        require(manifest['archive_sha256']==package['archive_sha256'],'Archive binding differs')
        for entry in manifest['files']:
            p=ROOT/entry['path']
            require(sha(p)==entry['published_sha256'],'Source binding differs: '+entry['path'])
            require(p.stat().st_size==entry['published_bytes'],'Source size differs')
    for entry in json.loads((MAN/'RESULT_FILES.json').read_text()):
        require(sha(ROOT/entry['path'])==entry['published_sha256'],'Result binding differs')

    seen_python=set();seen_shell=set()
    for name,digest in expected.items():
        original=name.removesuffix('.in')
        if original.endswith('.py') and digest not in seen_python:
            ast.parse((ROOT/name).read_text(),filename=name);seen_python.add(digest)
        if original.endswith(('.sh','.command')) and digest not in seen_shell:
            subprocess.run(['bash','-n',str(ROOT/name)],check=True,capture_output=True)
            seen_shell.add(digest)
    audit=rows(AUDIT/'NULL_SENTINEL_AUDIT.csv')
    require(len(audit)==14 and sum(x['status']=='affected' for x in audit)==1,'Sentinel audit changed')
    require(all(x['reestimated_this_audit']=='False' for x in audit),'Unexpected model rerun')
    repair=rows(MAN/'RECONCILIATION.csv')[0]
    require((int(repair['old_N']),int(repair['new_N']))==(314639,625066),'Wrong repair sample')
    require(int(repair['new_N'])-int(repair['old_N'])==int(repair['restored_N']),'Repair count mismatch')
    require(close(repair['new_estimate_pp'],1.121583658124428),'Wrong repaired estimate')
    returned=json.loads((ROOT/'results'/TAG/'remaining_results/receipt_companions/conditional_censored_at_next_competitive_disconnection.json').read_text())
    require(returned['rows']==625066,'Repaired return denominator differs')
    bins=rows(AUDIT/'CLAIM_ERROR_BY_RD.csv')
    require(sum(int(x['eligible_claims']) for x in bins)==40943232,'Claim frame mismatch')
    require(sum(int(x['paired_claims']) for x in bins)==40707278,'Paired claim frame mismatch')
    pooled=next(x for x in rows(AUDIT/'evidence/corrected_rating/RATING_VALIDATION.csv') if x['group']=='claim__action_payoff')
    for key in ['mean_absolute_error','mean_signed_error_predicted_minus_recorded']:
        require(close(math.fsum(int(x['paired_claims'])*float(x[key]) for x in bins)/40707278,pooled[key]),'Claim bin reconciliation failed')
    raw=rows(AUDIT/'evidence/post_panel/reconstruction_cells.csv')
    labels=['45 <= RD < 45.01 (floor)','45.01 <= RD < 60','60 <= RD < 100','100 <= RD < 200','RD >= 200']
    for r in rows(AUDIT/'POST_CHANGE_VALIDATION.csv'):
        k=labels.index(r['rd_bin'])
        cells=[x for x in raw if x['phase']==r['phase'] and int(x['rd_bin'])==k]
        n=sum(int(float(x['n'])) for x in cells)
        require(n==int(r['player_updates']),'Post-panel denominator mismatch')
        for source,target in [('sum_abs_error','mean_absolute_error'),('sum_error','mean_signed_error_predicted_minus_recorded')]:
            require(close(math.fsum(float(x[source]) for x in cells)/n,r[target]),'Post-panel reconciliation failed')
    return dict(status='PUBLIC_RELEASE_VERIFIED',public_files=len(expected),source_packages=len(packages),
                unique_python_sources=len(seen_python),unique_shell_sources=len(seen_shell),
                sentinel_audit_rows=len(audit),private_models_run=0)

if __name__=='__main__':print(json.dumps(verify(),indent=2))
