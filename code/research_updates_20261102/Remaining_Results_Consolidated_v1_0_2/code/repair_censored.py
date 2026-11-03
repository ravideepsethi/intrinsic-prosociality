"""Repair one conditional receipt estimate; retain the verified completed results."""
import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import platform
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from result_common import (
    ROOT, block_network, checkpoint, csv_save, guard, heartbeat, key, load,
    log, require, save, sha,
)
from run_all import dependency_report, pack, run_self_tests, verify_package

PRIOR_ARCHIVE = ROOT/'authority/COMPLETED_20261102T190254Z_RETURN.zip'
PRIOR_SHA = '1e7b388ffc1f97efae796139fa17bcfbf83ce6db59aa6a2d1bdf12845663641c'
MODEL = 'conditional_censored_at_next_competitive_disconnection'


def read_previous(path, expected_sha):
    """Authenticate every returned member before reusing any result."""
    require(sha(path)==expected_sha, 'Completed return archive checksum differs')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        require(len(names)==len(set(names)), 'Duplicate member in completed return')
        require(z.testzip() is None, 'Completed return ZIP is damaged')
        manifest=json.loads(z.read('RETURN_MANIFEST.json'))
        records={r['path']:r for r in manifest}
        require(len(records)==len(manifest), 'Duplicate path in return manifest')
        require(set(names)==set(records)|{'RETURN_MANIFEST.json'}, 'Unlisted return member')
        files={}
        for name,r in records.items():
            p=Path(name)
            require(not p.is_absolute() and '..' not in p.parts and 'PRIVATE' not in p.parts,
                    'Unsafe/private return member')
            require(p.suffix in ('.csv','.json','.txt','.log'), 'Unexpected return file type')
            data=z.read(name)
            require(len(data)==r['bytes'] and hashlib.sha256(data).hexdigest()==r['sha256'],
                    'Return manifest mismatch: '+name)
            files[name]=data
    require(json.loads(files['STATUS.json'])['status']=='ALL_REQUESTED_RESULT_JOBS_COMPLETE',
            'Prior jobs were not complete')
    require(json.loads(files['receipt_companions/STATUS.json'])['models_reported']==6,
            'Prior receipt report does not contain six models')
    return files


def row_hash(ids):
    import numpy as np
    return hashlib.sha256(np.asarray(ids,dtype='<i8').tobytes()).hexdigest()


def recompute(project, previous):
    import numpy as np
    import pyarrow.parquet as pq
    import receipt_companions as r
    from receipt_numerics import conditional_censor_mask, fit

    parents=r.load(r.ROOT/'authority/PARENTS.json');rid=parents['receipt_run_id']
    parent=project/'derived/replication/mating_material_receipt_v100_PRIVATE'/rid[:16]
    require(r.load(parent/'_SUCCESS.json')['status']=='RECEIPT_COMPLETE_MORE_FAMILIES_PENDING',
            'Completed corrected receipt source missing')
    require(sha(parent/'report/RESULTS.json')==parents['receipt_result_sha256'],
            'Corrected receipt summary changed')
    with heartbeat('Authenticating the completed receipt source'):
        sources=[r.bind_success_file(parent,'PRIVATE/recipient/recipient_private.parquet',rid),
                 r.bind_success_file(parent,'report/models/conditional.json',rid)]
    prior_lineage=json.loads(previous['receipt_companions/INPUT_LINEAGE.json'])
    require(prior_lineage['parent_run_id']==rid, 'Prior report used a different receipt producer')
    for source in sources:
        old=[v for v in prior_lineage['sources'] if Path(v['path']).name==Path(source['path']).name]
        require(len(old)==1 and old[0]['sha256']==source['sha256'] and old[0]['bytes']==source['bytes'],
                'Prior report and repair do not share identical receipt inputs')
    path=Path(sources[0]['path'])
    expected=r.load(r.ROOT/'authority/receipt_RESULTS.json')['summary']['sample']
    require(pq.ParquetFile(path).metadata.num_rows==expected['all_fresh_exposures'],
            'Corrected receipt row count differs')
    d,support=r.load_receipt(path)
    complete=support['eligible']&d['a1_90d_followup_eligible'].astype(bool)
    reached=d['reached_fair_chooser_within_90d'].astype(bool)
    conditional=complete&reached
    require(int(support['eligible'].sum())==expected['common_support']==r.SUPPORT_N,
            'Support cohort changed')
    require(int(complete.sum())==expected['common_support_complete90']==r.COMPLETE90_N,
            'Complete-window cohort changed')
    require(int(conditional.sum())==expected['complete90_reached']==r.CONDITIONAL_N,
            'Conditional cohort changed')
    anchor=d['exposure_anchor_utc_ms'];delta=d['first_subsequent_delta_ms']
    nxt=np.asarray(d['recipient_next_disconnection_utc_ms'],float)
    later=np.asarray(anchor,float)+np.asarray(delta,float)
    # Reconstruct the defective mask solely to identify the superseded sample.
    legacy=conditional&np.isfinite(later)&(~np.isfinite(nxt)|(nxt>anchor+90*86400000)|(later<=nxt))
    old=json.loads(previous['receipt_companions/'+MODEL+'.json'])
    require(int(legacy.sum())==old['rows'] and row_hash(d['cohort_row_id'][legacy])==old['sample_sha256'],
            'The defective sample does not reproduce the returned row identities')
    fixed=conditional_censor_mask(reached,anchor,delta,nxt,complete)
    present=np.isfinite(nxt)&(nxt>0)
    added=fixed&~legacy
    require(not (legacy&~fixed).any(), 'Repair unexpectedly removes previously retained rows')
    require(np.array_equal(added,conditional&~present&~legacy),
            'Repair changes rows beyond missing next-disconnection timestamps')
    require(int(added.sum())>0, 'Expected missing-timestamp rows were not restored')
    audit=dict(
        status='MASK_REPAIR_VALIDATED',
        reason='Integer Arrow nulls are loaded as -1, not NaN; the earlier mask treated -1 as a real censor.',
        timestamp_arrow_type=str(pq.ParquetFile(path).schema_arrow.field('recipient_next_disconnection_utc_ms').type),
        complete90=int(complete.sum()),conditional=int(conditional.sum()),
        legacy_rows=int(legacy.sum()),corrected_rows=int(fixed.sum()),restored_rows=int(added.sum()),
        removed_rows=int((legacy&~fixed).sum()),
        missing_next_disconnection=int((conditional&~present).sum()),
        negative_one_sentinels=int((conditional&(nxt==-1)).sum()),
        choice_before_next=int((conditional&present&(later<nxt)).sum()),
        choice_ties_next=int((conditional&present&(later==nxt)).sum()),
        choice_after_next_excluded=int((conditional&present&(later>nxt)).sum()),
        legacy_sample_sha256=row_hash(d['cohort_row_id'][legacy]),
        corrected_sample_sha256=row_hash(d['cohort_row_id'][fixed]),
        zero_coded_primary_modified=False,
        rule='Complete reached windows; no positive finite next-disconnection timestamp, or first later choice <= next disconnection. Ties retained.',
    )
    log(f"Censoring repair: {audit['legacy_rows']:,} previously retained; {audit['restored_rows']:,} restored; {audit['corrected_rows']:,} corrected rows.")
    fingerprint=key(dict(package=sha(ROOT/'SOURCE_SHA256SUMS.txt'),source=sources[0]['sha256'],repair='nullable_integer_censor_v1'))
    state=project/'derived/replication/remaining_results_censor_repair_v102_PRIVATE'/fingerprint[:16]
    def estimate(name,mask):
        ix=np.flatnonzero(mask)
        def build(folder):
            X,names=r.core.model_controls(d,ix,state_conditioned=False)
            groups=[d['exposure_cell_code'][ix],d['exposure_month_code'][ix]]
            with heartbeat('Estimating '+name):
                result=fit(d['first_subsequent_kind_draw'][ix],d['received_mercy'][ix],X,names,
                    support['weights'][ix],groups,d['exposure_chooser_user_id'][ix],
                    d['cohort_row_id'][ix],r.common,r.core)
            result.update(specification=name,fixed_effects=['exposure cell','exposure month'])
            save(folder/'MODEL.json',result)
            return result
        _,result=checkpoint(state,name,key(dict(job=fingerprint,model=name)),build)
        log(f"{name}: {result['estimate']:.6f} ({result['se']:.6f}), N={result['rows']:,}")
        return result
    reference=estimate('reference_conditional_validation',conditional)
    saved=r.load(sources[1]['path'])
    require(reference['sample_sha256']==saved['sample_sha256'], 'Reference row hash changed')
    require(abs(reference['estimate']-saved['estimate'])<1e-6 and abs(reference['se']-saved['se'])<1e-6,
            'Reference fit does not reproduce the completed model')
    result=estimate(MODEL,fixed)
    require(result['sample_sha256']==audit['corrected_sample_sha256'], 'Corrected model row identities differ')
    guard(sources)
    audit.update(reference_estimate_difference=reference['estimate']-saved['estimate'],
                 reference_se_difference=reference['se']-saved['se'],sources=sources,
                 repair_package_sha256=sha(ROOT/'SOURCE_SHA256SUMS.txt'))
    return result,audit


def merge_report(previous,report,result,audit):
    """Publish a corrected six-row table and byte-preserve other study results."""
    for name,data in previous.items():
        if name in ('STATUS.json','JOB_STATUS.json','SELF_TEST.log','receipt_companions/run.log'):
            target=report/'repair'/'original_run'/name
        else:
            target=report/name
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    old=json.loads(previous['receipt_companions/'+MODEL+'.json'])
    save(report/'repair/SUPERSEDED_INVALID_CENSOR_ESTIMATE.json',dict(
        valid_for_reporting=False,reason=audit['reason'],superseded_estimate=old))
    save(report/'receipt_companions'/(MODEL+'.json'),result)
    rows=list(csv.DictReader(io.StringIO(previous['receipt_companions/RECEIPT_COMPANIONS.csv'].decode())))
    require(len(rows)==6 and sum(v['specification']==MODEL for v in rows)==1, 'Prior table shape differs')
    for j,row in enumerate(rows):
        if row['specification']==MODEL:
            rows[j]={name:result.get(name,'') for name in row}
    csv_save(report/'receipt_companions/RECEIPT_COMPANIONS.csv',rows)
    counts=json.loads(previous['receipt_companions/CONDITIONAL_COUNTS.json'])
    counts.update(censored=result['rows'],missing_timestamp_rule='Present iff finite and > 0; null integers (-1) and NaN mean no recorded next disconnection.')
    save(report/'receipt_companions/CONDITIONAL_COUNTS.json',counts)
    save(report/'receipt_companions/STATUS.json',dict(status='COMPLETE',models_reported=6,
        corrected_models=[MODEL],reused_models=5,reference_models_verified=1,
        manuscript_modified=False,pdfs_modified=False,private_rows_exported=False,adjusted_p_values=False))
    (report/'receipt_companions/run.log').write_text(
        f"Corrected {MODEL}: {result['estimate']:.9f} ({result['se']:.9f}), N={result['rows']:,}.\n"
        "Five other estimates reused unchanged from the authenticated 20261102T190254Z return.\n"
        "The original run log, including the invalid censored estimate, is retained under repair/original_run/.\n")
    reused=[]
    for name,data in previous.items():
        keep=(name.startswith('counts/') or name.startswith('rating_validation/') or
              (name.startswith('receipt_companions/') and name.endswith('.json') and
               Path(name).stem in ('conditional_exposure_and_later_choice_hours','engagement_log1p_games_30d',
                                   'engagement_any_game_10m','engagement_any_game_30m','engagement_any_game_60m')))
        if keep:
            require((report/name).read_bytes()==data,'Unchanged result was modified: '+name)
            reused.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest()))
    audit=dict(audit,prior_return_sha256=PRIOR_SHA,prior_return='REMAINING_RESULTS_20261102T190254Z_RETURN.zip',
               reused_result_files=reused)
    save(report/'repair/CENSOR_REPAIR_AUDIT.json',audit)
    jobs=[dict(job='counts',status='COMPLETE',execution='reused_verified_completed_results'),
          dict(job='receipt_companions',status='COMPLETE',execution='one_model_corrected_five_reused'),
          dict(job='rating_validation',status='COMPLETE',execution='reused_verified_completed_results')]
    save(report/'JOB_STATUS.json',jobs)
    return jobs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--results-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--self-test',action='store_true')
    a=parser.parse_args();os.umask(0o077);verify_package()
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'code')
    if a.self_test:return run_self_tests(env)
    a.project_root=a.project_root.expanduser().resolve();a.results_dir=a.results_dir.expanduser().resolve()
    require(not a.results_dir.is_relative_to(a.project_root),'Return folder must be outside the source project')
    reports=a.results_dir/'Remaining_Results_Reports';reports.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report=reports/(stamp+'_CENSOR_REPAIR');report.mkdir(exist_ok=False)
    output=a.results_dir/f'REMAINING_RESULTS_CENSOR_REPAIRED_{stamp}_RETURN.zip'
    lock=(reports/'RUNNING.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('A consolidated results run is already active')
    started=time.monotonic();rc=1;jobs=[]
    try:
        log('Targeted correction: reference check plus one censored model; other completed results are reused.')
        log('Allow approximately 1–3 minutes, depending on drive I/O; no chronology scan or rating replay.')
        dependencies=dependency_report()
        save(report/'repair/ENVIRONMENT.json',dict(python=platform.python_version(),platform=platform.platform(),
             executable=sys.executable,dependencies=dependencies,blas_threads=1,
             package_manifest_sha256=sha(ROOT/'SOURCE_SHA256SUMS.txt')))
        require(not dependencies['problems'],'Dependency problems: '+', '.join(dependencies['problems']))
        require(run_self_tests(env,report)==0,'Synthetic tests failed; no private-data job was launched')
        previous=read_previous(PRIOR_ARCHIVE,PRIOR_SHA)
        require(a.project_root.is_dir(),'Mount XT_Pro: '+str(a.project_root))
        block_network()
        result,audit=recompute(a.project_root,previous)
        jobs=merge_report(previous,report,result,audit)
        rc=0
    except BaseException as exc:
        save(report/'repair/ERROR.json',dict(type=type(exc).__name__,message=str(exc)))
        (report/'ERROR.txt').write_text(traceback.format_exc())
        log(type(exc).__name__+': '+str(exc))
        if isinstance(exc,KeyboardInterrupt):rc=130
    finally:
        save(report/'STATUS.json',dict(status='ALL_REQUESTED_RESULT_JOBS_COMPLETE' if rc==0 else 'INCOMPLETE',
             jobs=jobs,repair_completed=(rc==0),elapsed_seconds=time.monotonic()-started,
             completion_scope='Rating validation, six retained matched-receipt companions, donor/environment/reputation/tenure counts',
             whole_paper_completion_certified=False,manuscript_or_pdf_modified=False,
             prior_return_sha256=PRIOR_SHA))
        pack(report,output);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return rc


if __name__=='__main__':raise SystemExit(main())
