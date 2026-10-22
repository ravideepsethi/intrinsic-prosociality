#!/usr/bin/env python3
"""Chooser leniency: predetermined scores, balance, first stage, and candidate IV.

Input scope is the authenticated T0 first-exposure cohort, NOT all ordinary
Lichess games. No network activity, API scan, Stockfish or all-game replay.
Every effect estimate is labelled a candidate IV with causal assumptions open.
"""
from __future__ import annotations
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import traceback
import uuid
import zipfile

import numpy as np
import iv_numerics as num
import t0_reference as t0

VERSION='1.0.0'
DAY=86_400_000
T0_ID='20260905T220710Z_2976'
T0_REPORT_SHA='b5866d0b0e4f893d3d67c1cc409bd831a7081d415d9b5866f1e3be70bda47ce0'
T0_CODE_SHA='7cef3e83738c496a744ef9a71d7067aa49f7d293a37d4d69d2b3989b324f9ec2'
MONTHS=t0.MONTHS
STARTS=np.array([int(dt.datetime.fromisoformat(m+'-01').replace(tzinfo=dt.timezone.utc).timestamp()*1000) for m in MONTHS],np.int64)
LAGS=(7,30)
FOLDS=4
CELLS=500
SPEEDS={'ultrabullet':0,'bullet':1,'blitz':2,'rapid':3,'classical':4}
COLS=['chooser_user_id','disconnected_user_id','api_last_move_at_ms','utc_ms','archive_ordinal',
      'game_id','kind_draw','timeout_chooser_win','fair_competitive','tc_base_s','tc_inc_s','api_speed',
      'engine_eval_cp_disconnected','ply_count','chooser_elo','disconnected_elo']
REC_FEATURES=['cohort_row_id','exposure_game_id','recipient_user_id','exposure_chooser_user_id',
              'exposure_game_utc_ms','exposure_anchor_utc_ms','exposure_month_code','exposure_tc_base_s',
              'exposure_tc_inc_s','exposure_chooser_elo','exposure_recipient_elo','exposure_chooser_rd',
              'exposure_recipient_rd','exposure_eval_cp','exposure_ply_count',
              'exposure_chooser_clock_s','exposure_recipient_clock_s','pre_games_30d',
              'reached_fair_chooser_within_90d','first_subsequent_kind_draw','first_subsequent_delta_ms']


def log(s): t0.log(s)
def digest(p): return t0.digest(p)
def load(p): return t0.load(p)
def write_json(p,v): t0.atomic_json(p,clean(v))

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,np.ndarray): return clean(v.tolist())
    if isinstance(v,np.generic): return clean(v.item())
    if isinstance(v,float) and not math.isfinite(v): return None
    return v

def deps():
    import pyarrow as pa
    import pyarrow.parquet as pq
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    return pa,pq

def array(t,n,dtype=None,nullable=False): return t0.array(t,n,dtype,allow_null=nullable)
def write_table(p,t): t0.pa_write(p,t)
def read_table(p,columns=None): return deps()[1].ParquetFile(p).read(columns=columns,use_threads=False)

def write_csv(p,rows):
    rows=[clean(r) for r in rows]
    for r in rows:
        for k,v in r.items():
            if isinstance(v,(list,dict)): r[k]=json.dumps(v,separators=(',',':'))
    if not rows: rows=[{'status':'NO_ROWS'}]
    t0.csv_write(p,rows)


def result_files(root):
    return [{'path':str(p.relative_to(root)), 'bytes':p.stat().st_size,'sha256':digest(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and p.name!='_COMPLETE.json']


def completed(root,config_hash):
    receipt=root/'_COMPLETE.json'
    if not receipt.exists(): return None
    r=load(receipt)
    if r.get('config_sha256')!=config_hash: raise RuntimeError('Checkpoint configuration mismatch: '+str(root))
    for f in r['files']:
        p=root/f['path']
        if not p.is_file() or digest(p)!=f['sha256']: raise RuntimeError('Checkpoint file mismatch: '+str(p))
    return r


def finish_dir(tmp,final,config_hash,extra=None):
    r={'config_sha256':config_hash,'files':result_files(tmp),**(extra or {})}
    write_json(tmp/'_COMPLETE.json',r)
    if final.exists(): raise RuntimeError('Refusing to overwrite checkpoint '+str(final))
    os.replace(tmp,final)
    return r


def safe_tmp(final):
    final.parent.mkdir(parents=True,exist_ok=True)
    p=final.with_name(final.name+'.partial.'+uuid.uuid4().hex)
    p.mkdir()
    return p


def verify_t0_report(package):
    p=package/'evidence/T0_REPORT.zip'
    t0.hashcheck(p,T0_REPORT_SHA)
    t0.hashcheck(package/'evidence/T0_CODE.zip',T0_CODE_SHA)
    with zipfile.ZipFile(p) as z:
        prefix='CHOOSER_LENIENCY_T0_REPORT/'
        rows=list(csv.DictReader(z.read(prefix+'REPORT_MANIFEST.csv').decode().splitlines()))
        for r in rows:
            b=z.read(prefix+r['file'])
            if len(b)!=int(r['bytes']) or hashlib.sha256(b).hexdigest()!=r['sha256']:
                raise RuntimeError('Uploaded T0 report manifest failed')
        summary=json.loads(z.read(prefix+'summary.json'))
        scan=list(csv.DictReader(z.read(prefix+'T0_scan_summary.csv').decode().splitlines()))
    if summary['run_id']!=T0_ID or summary['status']!='CHOOSER_LENIENCY_T0_COMPLETE_WITH_GAPS':
        raise RuntimeError('Unexpected T0 report')
    return summary,scan


def source_checkpoint_audit(old, report_scan, private, workers):
    """Read small T0 EXTRACTIONS only; never rescan the 46-GiB raw API archive."""
    report={r['file_id']:r for r in report_scan}
    recs=load(old/'source_scan_results_private.json')
    if recs['errors'] or len(recs['results'])!=12015: raise RuntimeError('T0 source scan not complete')
    if set(report)!={r['file_id'] for r in recs['results']}: raise RuntimeError('T0 scan ID set differs from upload')
    target_hash=digest(old/'targets_private.parquet')
    jobs=[]
    for r in recs['results']:
        rr=report[r['file_id']]
        for k in ('kind','rows_read','matched_rows','malformed_lines','input_sha256'):
            if str(r.get(k) if r.get(k) is not None else '')!=str(rr.get(k,'')):
                raise RuntimeError('T0 source receipt differs from uploaded manifest: '+k)
        if r['target_sha256']!=target_hash: raise RuntimeError('T0 target hash mismatch')
        jobs.append({'file_id':r['file_id'],'output':str(old/'source_parts'/f"{r['file_id']}.parquet"),
                     'sha256':r['output_sha256']})
    def one(j): t0.hashcheck(j['output'],j['sha256'])
    with cf.ThreadPoolExecutor(max_workers=min(workers,4)) as ex:
        for k,_ in enumerate(ex.map(one,jobs),1):
            if k%2000==0 or k==len(jobs): log(f'T0_EXTRACT_HASH_CHECK {k}/{len(jobs)}')
    # Re-reduce only matched target records into THIS run's private directory.
    # The old consolidated table had no output hash bound into the public report.
    table,qa=t0.reduce_sources(old/'targets_private.parquet',jobs,recs['results'],private)
    if qa['known_source_exposures']!=2177788 or qa['missing_source_exposures']!=9355:
        raise RuntimeError('T0 reduction count mismatch')
    if any(qa[k] for k in ['conflicting_source_exposures','created_at_conflicts','non_timeout_status_evidence']):
        raise RuntimeError('T0 source evidence is inconsistent')
    write_json(private/'t0_reduction_authentication.json',{'source_parts_checked':len(jobs),
        'source_raw_files_reread':0,'source_parts_matched_to_uploaded_scan_receipts':True,
        'consolidated_sha256':digest(private/'cohort_with_source_private.parquet'),'qa':qa})
    log('T0_SOURCE_RECOVERY_REUSED_NO_RAW_API_SCAN')
    return table


def prepare_cohort(args,rec,private,package):
    pa,pq=deps()
    final=private/'cohort'
    chk=completed(final,args.config_hash)
    if chk: return final/'cohort_private.parquet',chk
    tmp=safe_tmp(final)
    _,scan=verify_t0_report(package)
    old=args.project_root/'derived/replication/chooser_leniency_t0_v100_PRIVATE'/T0_ID
    if not old.is_dir(): raise RuntimeError('Completed private T0 directory is unavailable')
    old_done=load(old/'_AUDIT_COMPLETE.json')
    if old_done.get('report_zip_sha256')!=T0_REPORT_SHA or old_done.get('status')!='CHOOSER_LENIENCY_T0_COMPLETE_WITH_GAPS':
        raise RuntimeError('T0 completion receipt is not bound to the uploaded report')
    t=source_checkpoint_audit(old,scan,tmp,args.workers)
    # Reconstruct original membership from the pinned A1 file rather than trusting a copied flag.
    base=read_table(rec, list(t0.RECIPIENT_COLUMNS))
    d={n:array(base,n,nullable=True) for n in t0.RECIPIENT_COLUMNS
       if n not in ('exposure_game_id','first_subsequent_kind_draw')}
    full,published=t0.cohort_masks(d,enforce=True)
    rid=np.flatnonzero(full)
    if not np.array_equal(array(t,'cohort_row_id',np.int64),rid): raise RuntimeError('T0 row alignment differs from A1')
    if t['game_id'].to_pylist()!=base['exposure_game_id'].take(pa.array(rid)).to_pylist():
        raise RuntimeError('T0 case-sensitive game IDs differ from A1')
    for a,b in [('chooser_id','exposure_chooser_user_id'),('recipient_id','recipient_user_id'),
                ('archive_start_ms','exposure_game_utc_ms'),('anchor_ms','exposure_anchor_utc_ms'),
                ('received','received_mercy')]:
        if not np.array_equal(array(t,a),array(base,b)[rid]): raise RuntimeError('T0/A1 identity mismatch: '+a)
    if not np.array_equal(array(t,'frozen_a1_support',bool),published[rid]): raise RuntimeError('T0 support flag mismatch')
    source=np.array(t['api_source_recovered'].to_pylist())
    keep=(source=='pool') & ~array(t,'api_created_at_conflict',bool) & ~array(t,'api_status_not_timeout_evidence',bool)
    # Primary pilot uses the broader population, avoiding receipt-dependent ATT support cuts.
    ix=np.flatnonzero(keep)
    t=t.take(pa.array(ix))
    if len(t)!=2071679 or int(array(t,'received',bool).sum())!=61045:
        raise RuntimeError('Broader pool population count mismatch')
    f=array(t,'frozen_a1_support',bool)
    if int(f.sum())!=2070295 or int((f & array(t,'received',bool)).sum())!=61012:
        raise RuntimeError('Frozen pool population count mismatch')
    ids=array(t,'recipient_id',np.int64)
    if len(np.unique(ids))!=len(ids): raise RuntimeError('More than one exposure per recipient')
    start=array(t,'archive_start_ms',np.int64)
    month=array(t,'month_code',np.int64)
    inferred=np.searchsorted(STARTS,start,side='right')-1
    if not np.array_equal(inferred,month): raise RuntimeError('Exposure calendar month is inconsistent with archive start')
    features=read_table(rec,REC_FEATURES).take(t['cohort_row_id'])
    t=t.append_column('pilot_row',pa.array(np.arange(len(t),dtype=np.int64)))
    for n in REC_FEATURES:
        if n not in t.column_names: t=t.append_column(n,features[n])
    write_table(tmp/'cohort_private.parquet',t)
    qcols=['pilot_row','cohort_row_id','chooser_id','recipient_id','archive_start_ms','anchor_ms','month_code','received']
    for role,col in [('chooser','chooser_id'),('recipient','recipient_id')]:
        h=(num.user_hash(array(t,col,np.int64)) % np.uint64(args.shards)).astype(int)
        for s in range(args.shards):
            small=t.select(qcols).filter(pa.array(h==s))
            write_table(tmp/f'{role}_targets'/f'shard-{s:02d}.parquet',small)
    qa={'population':'all_first_pair_arm_complete90_pool_without_ATT_support_cut',
        'pool_exposures':len(t),'receipts':int(array(t,'received',bool).sum()),
        'frozen_pool_exposures':int(f.sum()),'ATT_weights_used':False,
        'additional_rows_outside_original_ATT_support':int((~f).sum()),
        'source_known_exposure_months':sorted({MONTHS[int(m)] for m in month}),
        'all_24_months_source_enrichment_created':False}
    r=finish_dir(tmp,final,args.config_hash,qa)
    return final/'cohort_private.parquet',r


def projected_schema():
    pa,_=deps()
    return pa.schema([('j',pa.int64()),('i',pa.int64()),('t',pa.int64()),('start',pa.int64()),
                      ('ord',pa.int64()),('gid',pa.string()),('y',pa.bool_()),('arm',pa.bool_()),
                      ('fair',pa.bool_()),('rt',pa.bool_()),('cell',pa.int16())])


def project_month(job):
    pa,pq=deps()
    final=Path(job['output']); old=completed(final,job['config_hash'])
    if old: return old
    tmp=safe_tmp(final)
    q=read_table(job['cohort'],['pilot_row','recipient_id','archive_start_ms'])
    qids=array(q,'recipient_id',np.int64); order=np.argsort(qids)
    qids=qids[order]; qrow=array(q,'pilot_row',np.int64)[order]
    # Balance histories end seven days BEFORE GAME START, not at the later disconnect.
    qend=array(q,'archive_start_ms',np.int64)[order]-7*DAY
    pre=np.zeros((len(q),4),np.int64) # own fair N, own grants, prior disconnects, prior receipts
    shape=(len(LAGS),len(MONTHS)+1,FOLDS,FOLDS,CELLS)
    rn=np.zeros(shape,np.int64); rs=np.zeros(shape,np.int64)
    writers=[pq.ParquetWriter(tmp/f'shard-{s:02d}.parquet',projected_schema(),compression='zstd') for s in range(job['shards'])]
    nr=0; nh=0
    try:
        for batch in pq.ParquetFile(job['path']).iter_batches(columns=COLS,batch_size=131072,use_threads=False):
            b=pa.Table.from_batches([batch])
            j=array(b,'chooser_user_id',np.int64); i=array(b,'disconnected_user_id',np.int64)
            tt=array(b,'api_last_move_at_ms',np.int64); st=array(b,'utc_ms',np.int64)
            if np.any(j==i) or np.any(j<0) or np.any(i<0) or np.any(tt<st):
                raise RuntimeError('Invalid Stage07 identity or timestamp ordering')
            yy=array(b,'kind_draw',bool); arm=yy|array(b,'timeout_chooser_win',bool)
            fair=array(b,'fair_competitive',bool)
            speed=np.array([SPEEDS.get(x,-1) for x in b['api_speed'].to_pylist()],np.int8)
            rt=(speed>=0)&(array(b,'tc_base_s',float)>0)
            cp=array(b,'engine_eval_cp_disconnected',float,nullable=True)
            ply=array(b,'ply_count',float,nullable=True)
            gap=array(b,'disconnected_elo',float,nullable=True)-array(b,'chooser_elo',float,nullable=True)
            valid=np.isfinite(cp)&np.isfinite(ply)&np.isfinite(gap)&rt
            # Invalid state values may remain in choice-outcome reconstruction but not training.
            cell=num.state_cells(np.nan_to_num(cp),np.nan_to_num(ply),np.maximum(speed,0),np.nan_to_num(gap))
            hist=arm&valid
            hf=(num.user_hash(j)%np.uint64(FOLDS)).astype(int)
            of=(num.user_hash(i)%np.uint64(FOLDS)).astype(int)
            for l,lag in enumerate(LAGS):
                eligible=np.searchsorted(STARTS,tt[hist]+lag*DAY,side='right')
                flat=(((eligible*FOLDS+hf[hist])*FOLDS+of[hist])*CELLS+cell[hist]).astype(np.int64)
                rn[l]+=np.bincount(flat,minlength=int(np.prod(shape[1:]))).reshape(shape[1:])
                rs[l]+=np.bincount(flat,weights=yy[hist].astype(np.int64),minlength=int(np.prod(shape[1:]))).reshape(shape[1:]).astype(np.int64)
            # Predetermined recipient behavior, compiled from original Stage 07.
            for people,role in [(j,0),(i,1)]:
                pos=num.lookup(qids,people); found=pos>=0; safe=np.maximum(pos,0)
                prior=found & (tt<qend[safe]) & (tt>=qend[safe]-90*DAY)
                if role==0:
                    use=prior&fair
                    np.add.at(pre[:,0],qrow[pos[use]],1)
                    np.add.at(pre[:,1],qrow[pos[use]],yy[use].astype(np.int64))
                else:
                    np.add.at(pre[:,2],qrow[pos[prior]],1)
                    np.add.at(pre[:,3],qrow[pos[prior]],yy[prior].astype(np.int64))
            out=pa.table({'j':pa.array(j),'i':pa.array(i),'t':pa.array(tt),'start':pa.array(st),
                 'ord':b['archive_ordinal'],'gid':b['game_id'],'y':pa.array(yy),'arm':pa.array(hist),
                 'fair':pa.array(fair),'rt':pa.array(rt),'cell':pa.array(cell)},schema=projected_schema())
            shard=(num.user_hash(j)%np.uint64(job['shards'])).astype(int)
            for s,w in enumerate(writers):
                take=np.flatnonzero(shard==s)
                if len(take): w.write_table(out.take(pa.array(take)),row_group_size=131072)
            nr+=len(b); nh+=int(hist.sum())
    finally:
        for w in writers: w.close()
    np.savez_compressed(tmp/'reference_deltas.npz',n=rn,s=rs)
    use=np.flatnonzero(pre.sum(axis=1)>0)
    write_table(tmp/'recipient_prehistory.parquet',pa.table({'pilot_row':pa.array(use),
          'own_fair_n':pa.array(pre[use,0]),'own_kind_n':pa.array(pre[use,1]),
          'prior_disconnects':pa.array(pre[use,2]),'prior_receipts':pa.array(pre[use,3])}))
    return finish_dir(tmp,final,job['config_hash'],{'rows':nr,'training_rows':nh,'input_sha256':job['input_sha256']})


def build_projections(args,paths,cohort,private,authorities):
    jobs=[]
    for p,r in zip(paths,authorities['stage07_files']):
        jobs.append({'path':str(p),'output':str(private/'projection'/p.parent.name),
           'cohort':str(cohort),'shards':args.shards,'config_hash':args.config_hash,'input_sha256':r['expected_sha256']})
    workers=min(args.workers,4,max(1,int((args.memory_gb-1)//1.5)))
    log(f'PANEL_PROJECTION_BEGIN months=24 workers={workers}; no API or chronology read')
    done=[]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        for k,r in enumerate(ex.map(project_month,jobs),1):
            done.append(r); log(f'PANEL_PROJECTION_MONTH {k}/24 training_rows={r["training_rows"]:,}')
    if sum(r['rows'] for r in done)!=47587020: raise RuntimeError('Projection lost certified Stage 07 rows')
    shape=(len(LAGS),len(MONTHS)+1,FOLDS,FOLDS,CELLS)
    rn=np.zeros(shape,np.int64); rs=np.zeros(shape,np.int64)
    for job in jobs:
        with np.load(Path(job['output'])/'reference_deltas.npz',allow_pickle=False) as z:
            rn+=z['n']; rs+=z['s']
    model=num.expanding_reference(rn[:,:len(MONTHS)],rs[:,:len(MONTHS)])
    np.save(private/'reference_means.npy',model,allow_pickle=False)
    write_json(private/'reference_receipt.json',{'sha256':digest(private/'reference_means.npy'),
        'state_cells':CELLS,'folds':FOLDS,'cutoff':'first day of focal month minus washout; strict predecessor',
        'excluded_from_reference':'all games involving either held-out focal participant fold',
        'reference_smoothing_strength':50,'post_cutoff_anchors_used':False,
        'training_source_filter':'real-time eligible Stage07 active resolutions; historical source NOT separately recovered'})
    return jobs


def first_choices(h, q):
    """Rebuild legacy and other-opponent outcomes, with deterministic tie breaks."""
    qids=q['recipient_id']; order=np.argsort(qids); sorted_ids=qids[order]
    pos=num.lookup(sorted_ids,h['j']); found=pos>=0
    target=np.where(found,order[np.maximum(pos,0)],0)
    base=found & h['fair'] & (h['t']>q['anchor_ms'][target]) & (h['t']<=q['anchor_ms'][target]+90*DAY)
    different=h['i']!=q['chooser_id'][target]
    started_after=h['start']>q['anchor_ms'][target]
    result={'pilot_row':q['pilot_row']}
    for label,keep in [('legacy',base),('other_anchor',base&different),
                       ('other_started_after',base&different&started_after)]:
        idx=np.flatnonzero(keep)
        reached=np.zeros(len(qids),bool); y=np.zeros(len(qids),bool)
        delta=np.full(len(qids),-1,np.int64); startdelta=np.full(len(qids),-1,np.int64)
        opponent=np.full(len(qids),-1,np.int64)
        if len(idx):
            o=np.lexsort((h['gid'][idx],h['ord'][idx],h['t'][idx],target[idx]))
            idx=idx[o]
            row=target[idx]
            take=np.r_[True,row[1:]!=row[:-1]]
            idx=idx[take]; row=target[idx]
            reached[row]=True; y[row]=h['y'][idx]
            delta[row]=h['t'][idx]-q['anchor_ms'][row]
            startdelta[row]=h['start'][idx]-q['anchor_ms'][row]
            opponent[row]=h['i'][idx]
        result[label+'_reached']=reached
        result[label+'_y']=y
        result[label+'_delta_ms']=delta
        result[label+'_start_delta_ms']=startdelta
        result[label+'_opponent_id']=opponent
    return result


def shard_worker(job):
    pa,pq=deps()
    final=Path(job['output']); old=completed(final,job['config_hash'])
    if old: return old
    tmp=safe_tmp(final)
    parts=[read_table(p) for p in job['parts']]
    t=pa.concat_tables(parts); del parts
    h={n:array(t,n) for n in ['j','i','t','start','ord','y','arm','fair','rt','cell']}
    h['gid']=np.array(t['gid'].to_pylist(),dtype='U8')
    del t
    qi=read_table(job['recipient_targets'])
    iq={n:array(qi,n) for n in qi.column_names}
    choices=first_choices(h,iq)
    write_table(tmp/'outcomes_private.parquet',pa.table(choices))
    qj=read_table(job['chooser_targets'])
    jq={n:array(qj,n) for n in qj.column_names}
    filterh=h['arm'] & np.isin(h['j'],np.unique(jq['chooser_id']))
    # Each scalar score uses earlier decisions across all observed states, not only granters.
    hj,hi,ht,hy,hc=(h[n][filterh] for n in ['j','i','t','y','cell'])
    del h,choices,iq,qi,qj
    model=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
    output={'pilot_row':jq['pilot_row']}
    for l,lag in enumerate(LAGS):
        arrays={n:np.full(len(jq['pilot_row']),np.nan) for n in ['raw','adjusted','expected']}
        arrays.update({n:np.zeros(len(jq['pilot_row']),np.int64) for n in ['n','counterparts','pair_removed']})
        for m in sorted(np.unique(jq['month_code'])):
            rows=np.flatnonzero(jq['month_code']==m)
            sc=num.score_month(hj,hi,ht,hy,hc,jq['chooser_id'][rows],jq['recipient_id'][rows],
                 int(STARTS[int(m)]-lag*DAY),model[l,int(m)],FOLDS)
            for n in arrays: arrays[n][rows]=sc[n]
        for n,v in arrays.items(): output[f'{n}_{lag}d']=v
        output[f'shrunken_adjusted_{lag}d']=arrays['adjusted']*arrays['n']/(arrays['n']+20.0)
    write_table(tmp/'scores_private.parquet',pa.table(output))
    return finish_dir(tmp,final,job['config_hash'],{'score_rows':len(jq['pilot_row']),
          'outcome_rows':len(read_table(job['recipient_targets'])),'history_rows_loaded':len(hj)})


def combine_ordered(paths,n,columns=None):
    pa,_=deps()
    tabs=[read_table(p,columns) for p in paths]
    t=pa.concat_tables(tabs)
    order=np.argsort(array(t,'pilot_row',np.int64))
    t=t.take(pa.array(order))
    if not np.array_equal(array(t,'pilot_row',np.int64),np.arange(n)):
        raise RuntimeError('Shards lost or duplicated target rows')
    return t


def build_shards(args,projection_jobs,cohort,private):
    pa,pq=deps()
    jobs=[]; maxrows=0
    for s in range(args.shards):
        parts=[str(Path(j['output'])/f'shard-{s:02d}.parquet') for j in projection_jobs]
        nr=sum(pq.ParquetFile(p).metadata.num_rows for p in parts); maxrows=max(maxrows,nr)
        jobs.append({'parts':parts,'output':str(private/'score_outcome_shards'/f'shard-{s:02d}'),
          'recipient_targets':str(cohort.parent/'recipient_targets'/f'shard-{s:02d}.parquet'),
          'chooser_targets':str(cohort.parent/'chooser_targets'/f'shard-{s:02d}.parquet'),
          'reference':str(private/'reference_means.npy'),'config_hash':args.config_hash})
    peak=maxrows*320+300*1024**2
    workers=max(1,min(args.workers,args.shards,int(max(1,(args.memory_gb-1.5)*1024**3//peak))))
    log(f'SCORES_AND_OUTCOMES_BEGIN shards={args.shards} workers={workers} estimated_GiB_per_worker={peak/1024**3:.2f}')
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        for k,r in enumerate(ex.map(shard_worker,jobs),1): log(f'SCORES_AND_OUTCOMES_SHARD {k}/{len(jobs)}')
    t=read_table(cohort); n=len(t)
    for filename in ['scores_private.parquet','outcomes_private.parquet']:
        joined=combine_ordered([Path(j['output'])/filename for j in jobs],n)
        for col in joined.column_names:
            if col!='pilot_row': t=t.append_column(col,joined[col])
    # Sum independently computed recipient histories. No focal or future rows enter them.
    pre=np.zeros((n,4),np.int64)
    for job in projection_jobs:
        b=read_table(Path(job['output'])/'recipient_prehistory.parquet')
        r=array(b,'pilot_row',np.int64)
        for k,name in enumerate(['own_fair_n','own_kind_n','prior_disconnects','prior_receipts']):
            pre[r,k]+=array(b,name,np.int64)
    for k,name in enumerate(['own_fair_n','own_kind_n','prior_disconnects','prior_receipts']):
        t=t.append_column(name,pa.array(pre[:,k]))
    legacy=array(t,'legacy_reached',bool)
    expected=array(t,'reached_fair_chooser_within_90d',bool)
    if not np.array_equal(legacy,expected): raise RuntimeError('Legacy first-opportunity reach failed exact reproduction')
    oldy=array(t,'first_subsequent_kind_draw',float,nullable=True)
    if not np.isfinite(oldy[expected]).all(): raise RuntimeError('Old reached outcomes missing')
    if not np.array_equal(array(t,'legacy_y',bool)[legacy],oldy[expected].astype(bool)):
        raise RuntimeError('Legacy first-opportunity choices failed exact reproduction')
    olddt=array(t,'first_subsequent_delta_ms',float,nullable=True)
    if not np.array_equal(array(t,'legacy_delta_ms',np.int64)[legacy],olddt[expected]):
        raise RuntimeError('Legacy first-opportunity timing failed exact reproduction')
    j=array(t,'chooser_id',np.int64)
    for label in ['other_anchor','other_started_after']:
        r=array(t,label+'_reached',bool); o=array(t,label+'_opponent_id',np.int64)
        if np.any(r & (o==j)): raise RuntimeError('Original chooser entered different-opponent outcome')
        if np.any(array(t,label+'_y',bool)&~r): raise RuntimeError('Nonreacher incorrectly coded kind')
    same=legacy & (array(t,'legacy_opponent_id',np.int64)==j)
    qa={'legacy_outcome_reproduced_row_by_row':True,
       'pool_rows':n,'legacy_reachers':int(legacy.sum()),
       'legacy_next_opponent_is_original_chooser':int(same.sum()),
       'legacy_next_game_started_before_or_at_exposure_anchor':int((legacy & (array(t,'legacy_start_delta_ms',np.int64)<=0)).sum()),
       'other_anchor_reachers':int(array(t,'other_anchor_reached',bool).sum()),
       'primary_other_started_after_reachers':int(array(t,'other_started_after_reached',bool).sum()),
       'primary_outcome':'first fair other-opponent game STARTED AFTER focal last-move anchor; decision anchor within 90d; otherwise zero',
       'terminal_click_time_observed':False,'source_for_all_24m_created':False}
    write_json(private/'outcome_audit.json',qa)
    write_table(private/'analysis_private.parquet',t)
    log('LEGACY_OUTCOME_REPRODUCED_AND_DIFFERENT_OPPONENT_OUTCOME_BUILT')
    return private/'analysis_private.parquet',qa


def imputed_scaled(a):
    a=np.asarray(a,float).copy(); missing=~np.isfinite(a)
    finite=a[~missing]
    med=float(np.median(finite)) if len(finite) else 0.0
    a[missing]=med
    scale=float(np.std(a))
    return (a-med)/(scale if scale>1e-12 else 1.0), missing.astype(float)


def model_inputs(data,mask,spec):
    d={k:v[mask] for k,v in data.items()}
    lag=spec['lag']; controls=[]; control_names=[]; missing_counts={}
    def control(name,values):
        v,m=imputed_scaled(values)
        controls.append(v); control_names.append(name)
        missing_counts[name]=int(m.sum())
        if m.any() and not m.all(): controls.append(m); control_names.append(name+'_missing')
    er=d['exposure_recipient_elo']; ej=d['exposure_chooser_elo']; gap=(ej-er)/100.0
    for name,v in [('recipient_rating',er),('rating_gap',gap),('rating_gap_square',gap**2),
                   ('rating_gap_absolute',np.abs(gap)),('recipient_RD',d['exposure_recipient_rd']),
                   ('chooser_RD',d['exposure_chooser_rd']),
                   ('log_chooser_prior_count',np.log1p(d[f'n_{lag}d'])),
                   ('log_chooser_prior_counterparts',np.log1p(d[f'counterparts_{lag}d'])),
                   ('chooser_history_expected_rate',d[f'expected_{lag}d'])]: control(name,v)
    if spec.get('state_controls'):
        for name,v in [('exposure_eval',np.sign(d['exposure_eval_cp'])*np.log1p(np.abs(d['exposure_eval_cp']))),
                       ('log_exposure_ply',np.log1p(d['exposure_ply_count'])),
                       ('log_chooser_clock',np.log1p(np.maximum(d['exposure_chooser_clock_s'],0))),
                       ('log_recipient_clock',np.log1p(np.maximum(d['exposure_recipient_clock_s'],0)))]: control(name,v)
    if spec.get('recipient_history_controls'):
        for name,v in [('log_prior_disconnects',np.log1p(d['prior_disconnects'])),
                       ('log_prior_receipts',np.log1p(d['prior_receipts'])),
                       ('log_pre_games30',np.log1p(d['pre_games_30d'])),
                       ('log_prior_fair',np.log1p(d['own_fair_n'])),
                       ('prior_kind_ever',(d['own_kind_n']>0).astype(float))]: control(name,v)
    if not np.isfinite(er).all() or not np.isfinite(ej).all():
        mean=np.nan_to_num((er+ej)/2,nan=-10000.0)
    else: mean=(er+ej)/2
    base=d['tc_base_s']; inc=d['tc_inc_s']
    if not np.isfinite(base).all() or not np.isfinite(inc).all(): raise RuntimeError('Missing exact time-control assignment fields')
    _,cell=num.factor(d['month_code'],base.astype(int),inc.astype(int),np.floor(mean/100).astype(int))
    day=d['archive_start_ms']//DAY
    hour=(d['archive_start_ms']//3_600_000)%168
    groups=[cell,hour,day]
    has=(d['own_fair_n']>0)
    priorrate=np.divide(d['own_kind_n'],d['own_fair_n'],out=np.zeros(len(has),float),where=has)
    traits={
      'prior_fair_history_present':has.astype(float),
      'log_prior_fair_opportunities':np.log1p(d['own_fair_n']),
      'prior_kind_indicator':(d['own_kind_n']>0).astype(float),
      'prior_kind_rate_zero_without_history':priorrate,
      'log_prior_disconnections':np.log1p(d['prior_disconnects']),
      'log_prior_receipts':np.log1p(d['prior_receipts']),
      'log_pre_game_volume30':np.log1p(d['pre_games_30d'])}
    z=d[f'{spec["score"]}_{lag}d']
    y=d[spec.get('outcome','other_started_after_y')].astype(float)
    reach=d[spec.get('reach','other_started_after_reached')].astype(float)
    treatment=d['received'].astype(float)
    columns=controls+[z,treatment,y,reach]
    tnames=[]; tsds={}
    for name,v in traits.items():
        v,m=imputed_scaled(v)
        columns.append(v); tnames.append(name); tsds[name]=float(np.std(traits[name]))
    a=np.column_stack(columns)
    res,absinfo=num.partial_out(a,groups,len(controls))
    rz,rd,ry,rr=res[:,0],res[:,1],res[:,2],res[:,3]
    zsd=float(np.sqrt(np.mean(rz**2)))
    if zsd<=1e-12: return None
    rz/=zsd
    rd_sd=float(np.sqrt(np.mean(rd**2)))
    diag={'n':len(y),'receipts':int(treatment.sum()),'outcome_mean':float(y.mean()),
      'control_outcome_mean':float(y[treatment==0].mean()) if np.any(treatment==0) else None,
      'treated_outcome_mean':float(y[treatment==1].mean()) if np.any(treatment==1) else None,
      'reached_n':int(reach.sum()),'raw_instrument_sd':float(np.std(z)),
      'residual_instrument_sd':zsd,'assignment_cells':int(cell.max()+1),
      'exposure_dates':int(len(np.unique(day))),'choosers':int(len(np.unique(d['chooser_id']))),
      'continuous_controls':control_names,'missing_control_counts':missing_counts,**absinfo}
    return {'z':rz,'d':rd,'y':ry,'reach':rr,'traits':res[:,4:],'trait_names':tnames,
            'trait_sd':tsds,'diag':diag,'j':d['chooser_id'],'date':day,'d_sd':rd_sd}


def specification_mask(data,spec):
    z=data[f'{spec["score"]}_{spec["lag"]}d']
    mask=np.isfinite(z)&(data[f'n_{spec["lag"]}d']>=spec['floor'])
    if spec.get('frozen'): mask &= data['frozen_a1_support'].astype(bool)
    if spec.get('breadth'): mask &= data[f'counterparts_{spec["lag"]}d']>=spec['breadth']
    if spec.get('own_history'): mask &= data['own_fair_n']>0
    if spec.get('conditional'): mask &= data[spec.get('reach','other_started_after_reached')].astype(bool)
    return mask


def flatten_ols(label,r,extra):
    row={**extra,'estimator':label,'supported':r.get('supported',False)}
    for k,v in r.items():
        row[k]=v
        if k in ('coefficient','standard_error','ci_low','ci_high'):
            row[k+'_pp']=None if v is None else 100*v
    return row


def estimate_spec(data,spec,extra_mask=None,balance=False):
    mask=specification_mask(data,spec)
    if extra_mask is not None: mask &= extra_mask
    n=int(mask.sum())
    if n<2000 or int(data['received'][mask].sum())<20:
        return [{'specification':spec['name'],'supported':False,'reason':'INSUFFICIENT_PILOT_SUPPORT','n':n}],[],[]
    r=model_inputs(data,mask,spec)
    if r is None: return [{'specification':spec['name'],'supported':False,'reason':'NO_RESIDUAL_Z_VARIATION','n':n}],[],[]
    rows=[]; balance_rows=[]; joint=[]
    for name,groups in [('chooser_CR0',num.cluster_codes(r['j'])),
                        ('chooser_and_exposure_date_CR0',num.cluster_codes(r['j'],r['date']))]:
        result=num.iv_fit(r['y'],r['d'],r['z'],groups)
        common={'specification':spec['name'],'clustering':name,'n':n,'receipts':r['diag']['receipts'],
          'outcome':spec.get('outcome','other_started_after_y'),'lag_days':spec['lag'],'minimum_history':spec['floor'],
          'post_assignment_state_controls':bool(spec.get('state_controls')),
          'conditional_on_reaching_opportunity':bool(spec.get('conditional')),
          'residual_instrument_sd':r['diag']['residual_instrument_sd'],'choosers':r['diag']['choosers'],
          'exposure_dates':r['diag']['exposure_dates'],'assignment_cells':r['diag']['assignment_cells'],
          'causal_identification_certified':False,'inference_small_cluster_warning':bool(r['diag']['choosers']<50 or (len(groups)==3 and r['diag']['exposure_dates']<50))}
        for label,out in [('first_stage_receipt_per_SD_Z',result['first_stage']),
                          ('reduced_form_kindness_per_SD_Z',result['reduced_form']),
                          ('same_sample_OLS',num.scalar_ols(r['y'],r['d'],groups)),
                          ('reduced_form_reach_per_SD_Z',num.scalar_ols(r['reach'],r['z'],groups))]:
            rows.append(flatten_ols(label,out,common))
        iv={**common,'estimator':'candidate_2SLS','supported':result['supported'],
            'partial_first_stage_R2':result.get('partial_first_stage_R2'),
            'control_outcome_mean_pp':100*r['diag']['control_outcome_mean'] if r['diag']['control_outcome_mean'] is not None else None,
            'reached_n':r['diag']['reached_n']}
        for k in ['iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high']:
            iv[k]=result.get(k)
            iv[k+'_pp']=100*result[k] if k in result else None
        for k in ['AR95_intervals','AR95_unbounded','AR95_reason','AR_covariance_psd']:
            iv[k]=result.get(k)
        fs=result['first_stage']; rf=result['reduced_form']
        if fs.get('supported') and rf.get('supported') and abs(fs['coefficient'])>1e-12:
            iv['approx_MDE80_IV_pp']=100*(1.959963984540054+0.8416212335729143)*rf['standard_error']/abs(fs['coefficient'])
            iv['MDE_caveat']='conditional large-sample approximation; does not include first-stage estimation uncertainty'
        rows.append(iv)
        if balance:
            for predictor,pred in [('Z_per_residual_SD',r['z']),('receipt_D_per_residual_SD',r['d']/r['d_sd'])]:
                for k,trait in enumerate(r['trait_names']):
                    out=num.scalar_ols(r['traits'][:,k],pred,groups)
                    balance_rows.append({**common,'trait':trait,'predictor':predictor,
                       'units':'trait SD per predictor residual SD','no_history_is_not_declining':True,**out})
                joint.append({**common,'predictor':predictor,**num.joint_balance(r['traits'],pred,groups)})
    return rows,balance_rows,joint


def estimates(args,analysis,private,public):
    needed=['pilot_row','received','frozen_a1_support','chooser_id','recipient_id','archive_start_ms','anchor_ms',
      'month_code','tc_base_s','tc_inc_s','speed_code','exposure_recipient_elo','exposure_chooser_elo',
      'exposure_recipient_rd','exposure_chooser_rd','exposure_eval_cp','exposure_ply_count',
      'exposure_chooser_clock_s','exposure_recipient_clock_s','pre_games_30d',
      'own_fair_n','own_kind_n','prior_disconnects','prior_receipts',
      'other_started_after_y','other_started_after_reached','other_anchor_y','other_anchor_reached']
    for lag in LAGS:
        needed += [f'{x}_{lag}d' for x in ['n','raw','adjusted','expected','counterparts','pair_removed','shrunken_adjusted']]
    t=read_table(analysis,needed)
    d={n:array(t,n,nullable=True) for n in needed}; del t
    if not np.isfinite(d['pre_games_30d']).all() or np.any(d['pre_games_30d']<0):
        raise RuntimeError('Invalid frozen pre-game chronology activity')
    support=[]
    for lag in LAGS:
        for floor in [1,5,10,25]:
            for pop in ['broader_pool','frozen_A1_pool']:
                denominator=np.ones(len(d['received']),bool) if pop=='broader_pool' else d['frozen_a1_support'].astype(bool)
                mask=denominator & (d[f'n_{lag}d']>=floor) & np.isfinite(d[f'adjusted_{lag}d'])
                support.append({'population':pop,'lag_days':lag,'history_cutoff':'month_start_minus_lag',
                  'minimum_history':floor,'denominator':int(denominator.sum()),'retained_exposures':int(mask.sum()),
                  'retained_receipts':int((mask & d['received']).sum()),'share':float(mask.sum()/denominator.sum())})
    write_csv(public/'T1_history_support.csv',support)
    main={'name':'PRIMARY_adjusted_7d_floor5_W','lag':7,'floor':5,'score':'adjusted'}
    specs=[main,
       {**main,'name':'raw_score_same_controls_algebraic_check','score':'raw'},
       {**main,'name':'adjusted_30d_floor5_W','lag':30},
       {**main,'name':'adjusted_7d_floor1_W','floor':1},
       {**main,'name':'adjusted_7d_floor10_W','floor':10},
       {**main,'name':'adjusted_7d_floor25_W','floor':25},
       {**main,'name':'fixed20_shrinkage_7d_floor1_W','score':'shrunken_adjusted','floor':1},
       {**main,'name':'adjusted_7d_floor5_W_plus_S','state_controls':True},
       {**main,'name':'adjusted_7d_floor5_W_plus_recipient_history','recipient_history_controls':True},
       {**main,'name':'adjusted_7d_floor5_frozen_support_W','frozen':True},
       {**main,'name':'adjusted_7d_floor5_min5_counterparts_W','breadth':5},
       {**main,'name':'other_opponent_anchor_only_outcome','outcome':'other_anchor_y','reach':'other_anchor_reached'},
       {**main,'name':'conditional_outcome_SELECTION_CAVEAT','conditional':True}]
    allrows=[]; balances=[]; joint=[]
    receipt=private/'model_checkpoints'; receipt.mkdir(exist_ok=True)
    for k,spec in enumerate(specs,1):
        p=receipt/(spec['name']+'.json')
        if p.exists(): result=load(p)
        else:
            log(f'ESTIMATING {k}/{len(specs)} {spec["name"]}')
            rows,bal,joi=estimate_spec(d,spec,balance=spec is main)
            result={'config_sha256':args.config_hash,'rows':rows,'balance':bal,'joint':joi}
            write_json(p,result)
        if result['config_sha256']!=args.config_hash: raise RuntimeError('Model checkpoint configuration changed')
        allrows+=result['rows']; balances+=result['balance']; joint+=result['joint']
        for r in result['rows']:
            if r.get('estimator')=='candidate_2SLS' and r.get('clustering')=='chooser_CR0':
                log(f'CANDIDATE_IV {spec["name"]} n={r["n"]:,} coefficient_pp={r.get("iv_coefficient_pp")} AR_unbounded={r.get("AR95_unbounded")}')
    # History-conditional balance avoids treating no opportunity as an observed zero propensity.
    spec={**main,'name':'balance_among_recipients_with_prior_opportunities','own_history':True}
    _,b,j=estimate_spec(d,spec,balance=True); balances+=b; joint+=j
    strata=[]
    groups=[]
    for speed in np.unique(d['speed_code']): groups.append((f'speed_code_{int(speed)}',d['speed_code']==speed))
    groups += [('board_equal',d['exposure_eval_cp']<=100),
               ('board_better',(d['exposure_eval_cp']>100)&(d['exposure_eval_cp']<300)),
               ('board_clearly_better',d['exposure_eval_cp']>=300),
               ('exposure_before_2025',d['archive_start_ms']<int(dt.datetime(2025,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)),
               ('exposure_in_2025',d['archive_start_ms']>=int(dt.datetime(2025,1,1,tzinfo=dt.timezone.utc).timestamp()*1000))]
    for name,mask in groups:
        log('FIRST_STAGE_STRATUM '+name)
        r,_,_=estimate_spec(d,{**main,'name':name},extra_mask=mask)
        strata += [x for x in r if x.get('estimator')=='first_stage_receipt_per_SD_Z' or not x.get('supported',True)]
    write_csv(public/'T2_first_stage_strata.csv',strata)
    write_csv(public/'T3_candidate_IV_and_comparisons.csv',allrows)
    write_csv(public/'T1_balance.csv',balances)
    write_csv(public/'T1_joint_balance.csv',joint)
    primary=[r for r in allrows if r.get('specification')==main['name']]
    return {'specifications':specs,'primary_rows':primary,'model_rows':len(allrows),
      'balance_rows':len(balances),'joint_balance':joint[:4],
      'negative_first_stage_strata':[r['specification'] for r in strata if r.get('coefficient',0)<0],
      'monotonicity_verified':False,'first_stage_states':'competitive A1 region only; no losing-state test claimed'}


def package_public(public,desktop,run_id):
    allowed={'REPORT.md','summary.json','T0_reused_counts.json','outcome_audit.json',
       'T1_history_support.csv','T1_balance.csv','T1_joint_balance.csv',
       'T2_first_stage_strata.csv','T3_candidate_IV_and_comparisons.csv','failure_summary.json'}
    files=[p for p in sorted(public.iterdir()) if p.is_file() and p.name in allowed]
    rows=[{'file':p.name,'sha256':digest(p),'bytes':p.stat().st_size} for p in files]
    write_csv(public/'REPORT_MANIFEST.csv',rows); files.append(public/'REPORT_MANIFEST.csv')
    name=f'CHOOSER_LENIENCY_IV_PILOT_REPORT_{run_id}.zip'
    out=desktop/name
    if out.exists(): out=desktop/(out.stem+'_'+uuid.uuid4().hex[:8]+'.zip')
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,'CHOOSER_LENIENCY_IV_PILOT_REPORT/'+p.name)
    out.with_suffix('.zip.sha256').write_text(digest(out)+'  '+out.name+'\n')
    log('UPLOAD_REPORT_ZIP '+str(out)); log('UPLOAD_REPORT_SHA256 '+digest(out))
    return out


def public_report(summary):
    main=summary['estimation']['primary_rows']
    def find(est,cl='chooser_CR0'):
        return next((r for r in main if r.get('estimator')==est and r.get('clustering')==cl),{})
    fs=find('first_stage_receipt_per_SD_Z'); rf=find('reduced_form_kindness_per_SD_Z')
    iv=find('candidate_2SLS'); ols=find('same_sample_OLS')
    def f(x): return 'not supported' if x is None else f'{x:.6g}'
    lines=['# Chooser-leniency IV pilot','',
      '**Status: candidate estimates; causal assumptions remain open.**','',
      '## What was run','',
      'Previously recovered API sources were reused. No raw API scan, network request, raw-PGN read, Stockfish calculation, or all-game chronology replay was performed.',
      'The primary population contains the broader first-pair, arm-eligible, complete-follow-up pool cohort. Receipt-dependent ATT weights and support restrictions are not inherited. The original support population is a sensitivity.',
      '', '## Predetermined score','',
      'For each exposure month, histories stop strictly before the first day of that month minus 7 days (primary) or 30 days (sensitivity). This is more conservative than T0\'s rolling daily support count, so retention need not match T0. November 2023 supplies histories but has no prior-month score.',
      'Every earlier chooser decision involving the focal recipient is excluded. Raw grant rates and state-adjusted residual rates are stored separately. The state-reference model uses only history before the same cutoff and excludes every game involving either focal participant\'s held-out fold. It uses fixed merit, ply, speed and rating-gap cells with a stated smoothing rule.',
      'The optional n/(n+20) shrinkage is a fixed-strength sensitivity, NOT empirical-Bayes estimation. Historical source was not recovered for every training decision; training uses eligible real-time Stage07 decisions across recorded sources.',
      '', '## Outcome','',
      'The frozen A1 next-opportunity outcome was first reconstructed exactly at the row level. The primary pilot outcome is kindness at the first fair other-opponent game started after the focal last-move anchor and resolved within the existing 90-day anchored window, or zero if no such game occurs. A separate sensitivity uses only the anchor ordering and other-opponent exclusion.',
      'API last-move anchors are not authenticated terminal click times. The 7/30-day history washouts reduce temporal-overlap concerns but do not create unobserved event logs. The outcome is a composite of reaching an opportunity and granting at that opportunity.',
      '', '## Primary candidate results (chooser-cluster CR0)','',
      f'- Usable exposures: {iv.get("n",fs.get("n","not supported"))}.',
      f'- Receipt change per residual SD of leniency: {f(fs.get("coefficient_pp"))} percentage points.',
      f'- First-stage one-df cluster-robust Wald F: {f(fs.get("wald_F_one_df"))}.',
      f'- Reduced form on later kindness: {f(rf.get("coefficient_pp"))} percentage points per residual SD.',
      f'- Same-sample OLS: {f(ols.get("coefficient_pp"))} percentage points.',
      f'- Candidate IV: {f(iv.get("iv_coefficient_pp"))} percentage points.',
      f'- Anderson–Rubin 95% confidence set (fraction units, multiply finite endpoints by 100 for pp): {iv.get("AR95_intervals","not supported")}.',
      f'- Approximate 80%-power detectable IV effect: {f(iv.get("approx_MDE80_IV_pp"))} percentage points. This conditions on the observed first-stage movement and is not a power guarantee.',
      '', '## Inference and balance','',
      'Tables report chooser-cluster and chooser-plus-exposure-date cluster CR0 sandwiches. Recipients have one observation each. These are conditional-history, large-cluster approximations, not design-exact permutation inference or UJIVE. Negative/non-positive covariance diagnostics are retained rather than repaired silently.',
      'Balance compares the leniency score and realized receipt against recipient histories measured before game start, with a seven-day separation for Stage07-based history. The prior-rate diagnostic is accompanied by a history-presence indicator and repeated among recipients with observed prior opportunities. No prior opportunity is not interpreted as an observed refusal.',
      'Assignment controls include exact-time-control x month x pair-mean-rating-100 cells, hour-of-week and calendar-date fixed effects, continuous rating/RD controls, and observable chooser-history composition/reliability. State controls and recipient-history controls are separate sensitivities. Variables explicitly controlled are not advertised as independent balance tests.',
      '', '## What this run does NOT establish','',
      'A strong first stage, balanced observables, a small p-value, or agreement with OLS does not certify identification. Historical rage-sit categories, queue restrictions, terminal selection, exclusion and monotonicity remain unresolved. Subgroup first stages cover competitive A1 states only; no clearly-losing or formal average-monotonicity verification is claimed.',
      'Ordinary-game and disconnect-selection placebos require a separately specified broader game sample and are not part of this run. This run also does not create source coverage for every game in all 24 months.',
      '', '## Next decision','',
      'Inspect residual score strength, confidence sets and recipient-history balance before deciding how much weight to put on the candidate IV. The estimates and all specified sensitivities are produced regardless of the direction of the result; no causal claim is automatically promoted.',
      '', 'All user IDs, game IDs, row-level scores, outcomes, and private paths remain on XT_Pro. Only allowlisted aggregate report files are packaged.','']
    return '\n'.join(lines)


def execute(args):
    args.project_root=args.project_root.expanduser().resolve()
    args.desktop_root=args.desktop_root.expanduser().resolve()
    package=Path(__file__).resolve().parent
    if not args.project_root.is_dir(): raise RuntimeError('Project root is not mounted')
    if not 1<=args.workers<=10 or args.memory_gb<4 or args.shards<8:
        raise RuntimeError('Use 1–10 workers, at least 4 GiB planning memory and at least 8 shards')
    private=args.project_root/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/args.run_id
    public=args.project_root/'output/chooser_leniency_iv_pilot_v100'/args.run_id
    private.mkdir(parents=True,exist_ok=True); public.mkdir(parents=True,exist_ok=True)
    args.desktop_root.mkdir(parents=True,exist_ok=True)
    lock=open(private/'RUN.lock','a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This IV pilot run is already active')
    config={'version':VERSION,'shards':args.shards,'lag_days':LAGS,'folds':FOLDS,
      'reference_cells':CELLS,'T0_report_sha256':T0_REPORT_SHA,
      'scripts':{n:digest(package/n) for n in ['run_iv_pilot.py','iv_numerics.py','t0_reference.py']},
      'primary_population':'broader_first_pair_arm_complete90_pool',
      'primary_history_floor':5,'scores_frozen_at_month_start_minus_lag':True,
      'no_effect_estimate_selects_specification':True}
    args.config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    cp=private/'config.json'
    if cp.exists() and load(cp)!=clean(config): raise RuntimeError('Resume settings or scripts changed; use a fresh run ID')
    write_json(cp,config)
    stage='preflight'; started=time.monotonic()
    try:
        free=shutil.disk_usage(args.project_root).free
        if free<20*1024**3: raise RuntimeError('At least 20 GiB free disk is required')
        log(f'IV_PILOT_PREFLIGHT free_GiB={free/1024**3:.1f} max_workers={args.workers} planning_memory_GiB={args.memory_gb}')
        summary,_=verify_t0_report(package)
        stage='input_authentication'; rec,paths=t0.authenticate(args,private)
        authorities=load(private/'input_authorities.json')
        stage='reuse_T0_and_build_cohort'; cohort,cqa=prepare_cohort(args,rec,private,package)
        stage='project_panel_and_reference'; jobs=build_projections(args,paths,cohort,private,authorities)
        stage='scores_and_outcomes'; analysis,oqa=build_shards(args,jobs,cohort,private)
        stage='estimation'; est=estimates(args,analysis,private,public)
        pa,_=deps()
        result={'status':'CHOOSER_LENIENCY_IV_PILOT_V100_COMPLETE','version':VERSION,'run_id':args.run_id,
          'T0_run_id':T0_ID,'T0_report_sha256':T0_REPORT_SHA,
          'cohort':{k:v for k,v in cqa.items() if k not in ('files','config_sha256')},
          'outcome_audit':oqa,'estimation':est,'config_sha256':args.config_hash,
          'runtime':{'seconds':time.monotonic()-started,'python':sys.version.split()[0],'numpy':np.__version__,
             'pyarrow':pa.__version__,'platform':platform.system(),'max_workers':args.workers,'planning_memory_GiB':args.memory_gb},
          'causal_identification_certified':False,'historical_conduct_category_observed':False,
          'raw_API_network_requests':0,'raw_API_source_scan_repeated':False,'all_game_chronology_replayed':False,
          'assumptions_open':['conditional assignment including internal conduct sorting',
             'selection into active resolutions','exclusion including event-specific communications',
             'monotonicity for marginal recipient types','terminal-time versus last-move-anchor ordering']}
        write_json(public/'summary.json',result)
        write_json(public/'outcome_audit.json',oqa)
        write_json(public/'T0_reused_counts.json',summary)
        (public/'REPORT.md').write_text(public_report(result),encoding='utf-8')
        archive=package_public(public,args.desktop_root,args.run_id)
        write_json(private/'_SUCCESS.json',{'status':result['status'],'config_sha256':args.config_hash,
            'analysis_sha256':digest(analysis),'report_zip_sha256':digest(archive),
            'causal_identification_certified':False})
        log(result['status']); log('CAUSAL_ASSUMPTIONS_REMAIN_OPEN')
        log('PRIVATE_OUTPUT '+str(private)); log('Resume ID: '+args.run_id)
        return 0
    except BaseException as e:
        (private/'exception_PRIVATE.txt').write_text(traceback.format_exc())
        failure=public/('failure_'+uuid.uuid4().hex[:8]); failure.mkdir()
        write_json(failure/'failure_summary.json',{'status':'CHOOSER_LENIENCY_IV_PILOT_BLOCKED',
           'stage':stage,'exception_type':type(e).__name__,'causal_identification_certified':False})
        (failure/'REPORT.md').write_text(f'# IV pilot blocked\n\nStage: {stage}. {type(e).__name__}.\n\nDetailed traceback remains private. Existing certified inputs are unchanged.\n')
        package_public(failure,args.desktop_root,args.run_id)
        log('BLOCKED '+str(e)); log('PRIVATE_DIAGNOSTIC '+str(private/'exception_PRIVATE.txt'))
        return 2
    finally: lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--memory-gb',type=float,default=8)
    p.add_argument('--shards',type=int,default=16)
    p.add_argument('--run-id',default=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid()))
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    if not args.execute: p.error('Pass --execute')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.run_id): p.error('Unsafe run ID')
    os.umask(0o077)
    return execute(args)

if __name__=='__main__': sys.exit(main())
