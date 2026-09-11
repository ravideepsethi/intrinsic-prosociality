"""Reconcile the fixed five-member family without importing stale estimates."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
from runner import common

ROOT=Path(__file__).resolve().parents[1]
FINGERPRINT='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30'
MEMBERS=('C1','C2','C5','C6','C9')
ARCHIVES={'C6_COMPLETED_RESULTS.zip':'0f47dce9baa00f7dded5a59c58a2c3908ebce18b09d4d45d5d530620f1c2ff0c',
          'C9_COMPLETED_RESULTS.zip':'bd0a6471e916f0a483c2309cb1fb916562ece39d72f515624c99d1fafab2f3ca'}


def read_report(path,expected):
    if common.sha256_file(path)!=expected: raise RuntimeError('Report archive SHA-256 changed')
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if not n.endswith('/')]
        if len(names)!=len(set(names)) or any(n.startswith('/') or '..' in Path(n).parts for n in names):
            raise RuntimeError('Unsafe or duplicate report members')
        if z.testzip() is not None: raise RuntimeError('Report CRC failure')
        manifests=[n for n in names if n.count('/')==1 and n.endswith('/REPORT_FILE_HASHES.tsv')]
        if len(manifests)!=1: raise RuntimeError('Ambiguous report manifest')
        manifest=manifests[0];prefix=manifest.rsplit('/',1)[0]+'/'
        rows=list(csv.DictReader(io.StringIO(z.read(manifest).decode()),delimiter='\t'))
        if set(names)!={prefix+r['relative_path'] for r in rows}|{manifest} or len(rows)!=len(names)-1:
            raise RuntimeError('Report inventory mismatch')
        files={}
        for r in rows:
            b=z.read(prefix+r['relative_path'])
            if len(b)!=int(r['bytes']) or hashlib.sha256(b).hexdigest()!=r['sha256']:
                raise RuntimeError('Report member failed authentication')
            files[r['relative_path']]=b
    return files,{'archive':path.name,'sha256':expected,'authenticated_files':len(rows)}


def holm(p_values):
    if set(p_values)!=set(MEMBERS): raise RuntimeError('Family D must retain exactly five members')
    if any(not math.isfinite(p) or not 0<=p<=1 for p in p_values.values()):
        raise RuntimeError('Invalid raw p value')
    result={};running=0.0
    for rank,key in enumerate(sorted(p_values,key=lambda k:(p_values[k],k)),1):
        running=max(running,(6-rank)*p_values[key])
        result[key]={'rank':rank,'multiplier':6-rank,'adjusted_p':min(1.0,running)}
    return result


def reconcile(evidence=None):
    evidence=ROOT/'evidence' if evidence is None else evidence
    six,six_receipt=read_report(evidence/'C6_COMPLETED_RESULTS.zip',ARCHIVES['C6_COMPLETED_RESULTS.zip'])
    nine,nine_receipt=read_report(evidence/'C9_COMPLETED_RESULTS.zip',ARCHIVES['C9_COMPLETED_RESULTS.zip'])
    s=json.loads(six['receipts/WAVE2B2B1_RUN_STATUS.json'])
    if s['status']!='POOL_MAIN_WAVE2B2B1_ALL_STAGES_OK' or s['sample_authority']['fingerprint']!=FINGERPRINT:
        raise RuntimeError('C6 sample/status authority changed')
    gate=json.loads(six['results/c6_c10/c6_support_gate.json'])
    if (gate['gate_pass'] is not True or gate['treatment_specific_c6_outcomes_tabulated'] is not False
        or gate['family_disposition']!='RETAIN_C6_IN_HOLM_FAMILY_D'
        or gate['pooled_clearly_losing_timeout_events']<4000 or gate['recipients_with_any_later_timeout']<4000):
        raise RuntimeError('C6 prespecified support gate did not pass')
    c6=json.loads(six['results/c6_c10/summary.json'])['C6']['primary']
    if c6['outcome']!='c6_clear_rate_per_1000' or c6['holm_family_member'] is not True:
        raise RuntimeError('Wrong C6 estimand')
    config=json.loads(nine['CONFIGURATION.json']);success=json.loads(nine['_SUCCESS.json'])
    digest=hashlib.sha256(common.canonical_json(config['config']).encode()).hexdigest()
    if digest!=config['config_sha256'] or digest!=success['config_sha256']:
        raise RuntimeError('C9 configuration binding failed')
    if not success['exact_new_sample_b2_reproduction'] or success['status']!='POOL_MAIN_C9_FRESH_RANDOMIZATION_OK':
        raise RuntimeError('C9 implementation precondition did not clear')
    if FINGERPRINT not in json.dumps(config['config']): raise RuntimeError('Wrong C9 sample')
    rows=list(csv.DictReader(io.StringIO(nine['c9_partition_components.csv'].decode())))
    c9=[r for r in rows if r['category']=='later_session_7d' and r['epistemic_role']=='C_primary']
    if len(c9)!=1 or int(c9[0]['randomizations'])!=4999: raise RuntimeError('Wrong C9 estimand')
    c9=c9[0]
    known={'C6':float(c6['p_value_raw']),'C9':float(c9['randomization_p_two_sided'])}
    low=holm({k:known.get(k,0.0) for k in MEMBERS})
    upper=holm({k:known.get(k,1.0) for k in MEMBERS})
    labels={'C1':'loss-minus-win within chooser','C2':'session ahead-minus-behind within chooser',
            'C5':'snapshot experience U statistic','C6':'clearly-losing timeouts per 1000 rated games, mercy minus claim',
            'C9':'later-session 7-day first-grant ignition excess'}
    table=[]
    for key in MEMBERS:
        table.append({'member':key,'estimand':labels[key],'family_size':5,
                      'authority_status':'AUTHENTICATED_NEW_SAMPLE' if key in known else 'NO_AUTHENTICATED_NEW_SAMPLE_ESTIMATE_IN_BOUND_EVIDENCE',
                      'p_raw_observed':known.get(key),'missing_slot_p_for_conservative_calculation':None if key in known else 1.0,
                      'p_holm_lower_bound':low[key]['adjusted_p'] if key in known else None,
                      'p_holm_conservative_upper_bound':upper[key]['adjusted_p'],
                      'upper_bound_rank':upper[key]['rank'],'upper_bound_multiplier':upper[key]['multiplier'],
                      'reject_under_any_completion_at_5pct':key in known and upper[key]['adjusted_p']<=.05,
                      'final_exact_Holm_p_available':False})
    receipt={'status':'FAMILY_D_RECONCILED_FINAL_EXACT_FAMILY_OPEN','family':list(MEMBERS),'family_size':5,'alpha':.05,
             'sample_fingerprint':FINGERPRINT,'authenticated_current_members':list(known),
             'missing_current_authorities':['C1','C2','C5'],'missing_p_is_not_an_estimated_p':True,
             'quarantined_C1_lineages_used':False,'old_sample_p_values_used':False,
             'C13_C7X_Patron_or_ply_sensitivities_added':False,'C6_support_gate':gate,
             'C9_B2_implementation_precondition_cleared':True,
             'guaranteed_rejections':[r['member'] for r in table if r['reject_under_any_completion_at_5pct']],
             'method':'Five-slot Holm step-down. Unknown slots set to one for upper bounds and zero for lower bounds; exact family remains open.',
             'source_reports':[six_receipt,nine_receipt],
             'selected_source_hashes':{p:hashlib.sha256(b).hexdigest() for p,b in
                 [('C6/summary.json',six['results/c6_c10/summary.json']),('C9/c9_partition_components.csv',nine['c9_partition_components.csv'])]},
             'source_estimates':{'C6':c6,'C9':c9},'table':table}
    return table,receipt
