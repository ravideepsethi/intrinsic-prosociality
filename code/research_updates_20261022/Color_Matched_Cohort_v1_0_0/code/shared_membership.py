#!/usr/bin/env python3
"""Use the unchanged IV producer and its existing checkpoint namespace.

This isolated process avoids module-name collisions with the color code. It
stops after membership; no IV scores, rating history or engine work is run.
"""
from __future__ import annotations
import argparse,fcntl,os,shutil,sys,time
from pathlib import Path
VENDOR=Path(__file__).resolve().parents[1]/'vendor/Receipt_IV_Cohort_Extension_v1_0_0'
sys.path.insert(0,str(VENDOR/'code'))
import common as c
import inputs,source_stage,adjacency_stage,membership_stage
import run as producer

def fast_membership(work,auth,code):
    valid=[]
    for rp in sorted((work/'membership').glob('*/_DONE.json')):
        d=c.load(rp)
        if len(d.get('inputs',[]))<2:continue
        sp=Path(d['inputs'][0]['path']);ap=Path(d['inputs'][1]['path'])
        if not sp.is_file() or not ap.is_file():continue
        sr=c.load(sp)
        expected=c.digest(dict(code=code,inputs=d['inputs'],source_result=sr['result']))
        if d.get('key')!=expected:continue
        # Only the current immutable input chain is reusable.
        try:c.unchanged(d['inputs'])
        except RuntimeError:continue
        c.checked(sp,d['inputs'][0],auth);c.checked(ap,d['inputs'][1],auth)
        for month in ('2025-11','2025-12','2026-01'):
            rel='membership/month='+month+'/membership_PRIVATE.parquet'
            er=next((r for r in d['files'] if r['path']==rel),None)
            if er is None:raise RuntimeError('Completed membership receipt lacks a required month')
            c.checked(rp.parent/rel,er,auth)
        valid.append((rp.parent,d,sp.parent,ap.parent,sr['result']))
    if len(valid)>1:raise RuntimeError('Multiple current membership contracts; preserve them for resolution')
    return valid[0] if valid else None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--desktop',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=int,default=8)
    a=ap.parse_args();project=a.project.resolve();work=project/'derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE'
    work.mkdir(parents=True,exist_ok=True);auth=work/'authentication'
    inputs.verify_package();code=producer.code_signature();c.pa.set_cpu_count(1);c.pa.set_io_thread_count(1)
    lock=(work/'run.lock').open('a+')
    while True:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
        except BlockingIOError:
            c.log('Shared IV membership producer is running; waiting 30 seconds, then reusing its outputs');time.sleep(30)
    try:
        hit=fast_membership(work,auth,code)
        if hit:
            mr,md,sr,ar,source_result=hit;c.log('Reusing completed source/adjacency/membership without rerunning those stages')
        else:
            processes=min(2,a.workers);per_mb=(a.memory_gb*1024-2048)//processes;serial=a.memory_gb*1024-1536
            with c.heartbeat('Authenticating existing source/adjacency inputs'):
                hist=inputs.history(project,auth);old=inputs.old_membership(project,auth)
                feats,fs=inputs.feature_sources(project,auth);chron=inputs.chronology(project,auth)
            tr,td=source_stage.prepare_targets(hist['opportunities'],feats,work,auth,code,a.workers,serial,[*hist['snapshots'],*fs])
            sr,sd=source_stage.recover(project,a.desktop,[],tr,work,auth,code,a.workers,a.workers,serial)
            if shutil.disk_usage(work).free<32*1024**3:raise RuntimeError('Need 32 GiB free for unfinished shared chronology projection')
            target_inputs=[producer.snapshot(tr/n) for n in ('targets_PRIVATE.parquet','target_user_months_PRIVATE.parquet','target_users_PRIVATE.parquet')]
            jobs=[dict(record=r,targets=str(tr),target_inputs=target_inputs,work=str(work),auth=str(auth),code=code,
                       threads=max(1,a.workers//processes),memory_mb=per_mb) for r in chron]
            projected=producer.pool_jobs(jobs,adjacency_stage.file_job,processes,'Shared chronology files')
            projected.sort(key=lambda x:(x['result']['month'],x['result']['speed'],x['root']))
            by_bucket={k:[] for k in range(adjacency_stage.BUCKETS)}
            for r in projected:
                for e in r['files']:
                    p=Path(e['path']);ub=[x for x in p.parts if x.startswith('ub=')]
                    if p.suffix=='.parquet' and len(ub)==1:by_bucket[int(ub[0][3:])].append(str(Path(r['root'])/p))
            proj_inputs=[dict(**r['receipt'],fingerprint=c.stamp(r['receipt']['path'])) for r in projected]
            sj=[dict(bucket=b,paths=by_bucket[b],targets=str(tr),inputs=[*proj_inputs,*target_inputs],work=str(work),auth=str(auth),
                     code=code,memory_mb=per_mb) for b in range(adjacency_stage.BUCKETS)]
            sides=producer.pool_jobs(sj,adjacency_stage.side_job,processes,'Shared adjacency buckets')
            ar,ad=adjacency_stage.census(sides,tr,old,work,auth,code,a.workers,serial)
            mr,md=membership_stage.build(sr,sd['result'],ar,hist['opportunities'],old,work,auth,code,a.workers,serial,
                [producer.snapshot(sr/'_DONE.json'),producer.snapshot(ar/'_DONE.json'),*hist['snapshots'],*old['snapshots']])
            source_result=sd['result']
            c.unchanged([*hist['snapshots'],*old['snapshots'],*fs])
        # Attach only three completed history projections; no 512-shard IV work.
        hr=project/inputs.HISTORY;ready=c.load(hr/'READY_FOR_COHORT_EXTENSION.json')
        opportunities={};receipts=[]
        for r in ready['new_month_products']:
            if r['month'] not in ('2025-11','2025-12','2026-01'):continue
            root=c.relocated(r['root'],project);c.checked(root/'_DONE.json',r['receipt'],auth)
            done=c.load(root/'_DONE.json');er=next(e for e in done['files'] if e['path']=='opportunities_PRIVATE.parquet')
            fp=root/er['path'];c.checked(fp,er,auth);opportunities[r['month']]=str(fp)
            receipts.append(dict(path=str(fp),**{k:v for k,v in er.items() if k!='path'}))
        if len(opportunities)!=3:raise RuntimeError('Required November–January history projections missing')
        c.write_json(a.output,dict(status='SHARED_MEMBERSHIP_REUSED_OR_COMPLETED',producer_code_signature=code,
            membership_root=str(mr),source_root=str(sr),adjacency_root=str(ar),membership_receipt=c.receipt(mr/'_DONE.json'),
            opportunities=opportunities,opportunity_receipts=receipts,
            source_scan_issues=source_result['scan_issues'],flow=md['result']['flow'],
            code_scope='Unchanged source, chronology, adjacency and membership producer; no IV score jobs',
            roster_regular_definition='NOT_THIS_PRODUCER; built by color runner separately'))
    finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':main()
