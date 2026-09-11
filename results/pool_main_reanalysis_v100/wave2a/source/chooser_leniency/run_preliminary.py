#!/usr/bin/env python3
"""Source-known exploratory placebo + outcome-blind 200,000-game pilot preparation.

No API calls. No all-game selection regression on availability-selected records.
Private inputs are read-only; only allowlisted aggregate outputs are transferable.
"""
from __future__ import annotations
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import fcntl
import hashlib
import io
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
from collections import Counter, defaultdict
import numpy as np
import iv_numerics as num
import preliminary_core as core

VERSION='1.0.0'
VALIDITY_ID='20260906T052017Z_46893'
VALIDITY_SHA='ff14f791073667bb57324c5c80ca727bcdc2fb72e6d802a9d482386c12de9e7d'
VALIDITY_CONFIG='f472f94e84149d4ee75626b87977a46457bdb41ea69a29e44c82ab33f83cd46b'
IV_ID='20260906T034402Z_47553'
IV_SHA='e5cdcf5c9e27d858955fdeec3691b901c370a011db912602a6db3b6fc31c93eb'
IV_CONFIG='aacbd96652dd4c184e6694975c4fac7d38b028c5357b8bb937ce5c3a4578bc30'
STAGE_SHA='8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7'
PUBLIC={'REPORT.md','summary.json','sample_flow.csv','status_breakdown.csv','metadata_audit.csv',
        'pilot200k_readiness.csv','placebo_support.csv','exploratory_placebos.csv',
        'identity_audit.json','history_diagnostics.json','input_verification.json',
        'failure_summary.json','open_assumptions.json'}


def log(s): print('['+dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%SZ')+'] '+str(s),flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''): h.update(b)
    return h.hexdigest()
def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean(v) for v in x]
    if isinstance(x,np.ndarray): return clean(x.tolist())
    if isinstance(x,np.generic): return clean(x.item())
    if isinstance(x,float) and not math.isfinite(x): return None
    return x
def load(p): return json.loads(Path(p).read_text())
def js(p,x):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_name(p.name+'.partial.'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(clean(x),sort_keys=True,indent=2)+'\n'); os.replace(tmp,p)
def cfgsha(x): return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def check(p,expected):
    p=Path(p)
    if not p.is_file() or sha(p)!=expected: raise RuntimeError('Input hash mismatch: '+str(p))
    return p

def deps():
    import pyarrow as pa
    import pyarrow.parquet as pq
    pa.set_cpu_count(1); pa.set_io_thread_count(1)
    return pa,pq

def read(p,cols=None): return deps()[1].ParquetFile(p).read(columns=cols,use_threads=False)
def array(t,name,dtype=None):
    a=t[name].combine_chunks()
    if a.null_count: raise RuntimeError('Unexpected null in '+name)
    return np.asarray(a.to_numpy(zero_copy_only=False),dtype=dtype)
def write(p,t):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists(): raise RuntimeError('Refusing to overwrite finalized Parquet: '+str(p))
    tmp=p.with_name(p.name+'.partial.'+uuid.uuid4().hex)
    deps()[1].write_table(t,tmp,compression='zstd',row_group_size=131072)
    os.replace(tmp,p)
def csvout(p,rows):
    rows=[clean(r) for r in rows] or [{'status':'NO_ROWS'}]
    names=sorted({k for r in rows for k in r})
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.partial.'+uuid.uuid4().hex)
    with tmp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names); w.writeheader()
        for r in rows: w.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(dict,list)) else v for k,v in r.items()})
    os.replace(tmp,p)

def receipt_file(root,conf,name,verify=True):
    root=Path(root); r=load(root/'_COMPLETE.json')
    if r.get('config_sha256')!=conf: raise RuntimeError('Checkpoint config mismatch: '+str(root))
    rows=[f for f in r['files'] if f['path']==name]
    if len(rows)!=1: raise RuntimeError('Checkpoint missing or duplicate file: '+str(root/name))
    rel=Path(name)
    if rel.is_absolute() or '..' in rel.parts: raise RuntimeError('Unsafe checkpoint path')
    f=rows[0]; p=root/rel
    if not p.is_file() or p.stat().st_size!=int(f['bytes']): raise RuntimeError('Checkpoint byte-size mismatch: '+str(p))
    if verify: check(p,f['sha256'])
    return p,f,r

def done(root,conf):
    p=Path(root)/'_COMPLETE.json'
    if not p.exists(): return None
    r=load(p)
    if r['config_sha256']!=conf: raise RuntimeError('Resume settings changed')
    for f in r['files']: receipt_file(root,conf,f['path'])
    return r

def newdir(final):
    final=Path(final); final.parent.mkdir(parents=True,exist_ok=True)
    tmp=final.with_name(final.name+'.partial.'+uuid.uuid4().hex); tmp.mkdir(); return tmp

def finish(tmp,final,conf,extra=None):
    files=[{'path':str(p.relative_to(tmp)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(Path(tmp).rglob('*')) if p.is_file()]
    r={'config_sha256':conf,'files':files,**(extra or {})}; js(Path(tmp)/'_COMPLETE.json',r)
    if Path(final).exists(): raise RuntimeError('Final checkpoint already exists')
    os.replace(tmp,final); return r

def zipreport(public,desktop,run):
    public=Path(public); files=[p for p in sorted(public.iterdir()) if p.is_file() and p.name in PUBLIC]
    manifest=public/'REPORT_MANIFEST.csv'
    csvout(manifest,[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]); files.append(manifest)
    dest=Path(desktop)/f'CHOOSER_LENIENCY_PRELIMINARY_REPORT_{run}.zip'
    if dest.exists(): dest=dest.with_name(dest.stem+'_'+uuid.uuid4().hex[:8]+'.zip')
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,'CHOOSER_LENIENCY_PRELIMINARY_REPORT/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_REPORT_ZIP '+str(dest)); log('UPLOAD_REPORT_SHA256 '+sha(dest)); return dest

def report_evidence(package,which,expected,prefix):
    p=check(package/'evidence'/which,expected)
    with zipfile.ZipFile(p) as z:
        for r in csv.DictReader(io.StringIO(z.read(prefix+'/REPORT_MANIFEST.csv').decode())):
            b=z.read(prefix+'/'+r['file'])
            if len(b)!=int(r['bytes']) or hashlib.sha256(b).hexdigest()!=r['sha256']:
                raise RuntimeError('Evidence archive internal manifest mismatch')
        return json.loads(z.read(prefix+'/summary.json'))


def authenticate(args,private,public):
    package=Path(__file__).parent
    vr=report_evidence(package,'VALIDITY_REPORT.zip',VALIDITY_SHA,'CHOOSER_LENIENCY_VALIDITY_LOCAL_REPORT')
    ir=report_evidence(package,'IV_PILOT_REPORT.zip',IV_SHA,'CHOOSER_LENIENCY_IV_PILOT_REPORT')
    if vr['run_id']!=VALIDITY_ID or vr['config_sha256']!=VALIDITY_CONFIG: raise RuntimeError('Wrong validity evidence')
    old=args.project_root/'derived/replication/chooser_leniency_validity_local_v100_PRIVATE'/VALIDITY_ID
    iv=args.project_root/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/IV_ID
    s=load(old/'_SUCCESS.json'); c=load(old/'config.json')
    if s.get('report_sha256')!=VALIDITY_SHA or s.get('config_sha256')!=VALIDITY_CONFIG or cfgsha(c)!=VALIDITY_CONFIG:
        raise RuntimeError('Local validity run is not the completed uploaded run')
    si=load(iv/'_SUCCESS.json'); ci=load(iv/'config.json')
    if si.get('report_zip_sha256')!=IV_SHA or si.get('config_sha256')!=IV_CONFIG or cfgsha(ci)!=IV_CONFIG:
        raise RuntimeError('Local IV pilot lineage changed')
    check(package/'iv_numerics.py',ci['scripts']['iv_numerics.py'])
    frame,ff,_=receipt_file(old/'comparison_sample',VALIDITY_CONFIG,'games.parquet')
    ledger,lf,_=receipt_file(old/'source24m_and_comparison',VALIDITY_CONFIG,'comparison_source_status.parquet')
    reference=iv/'reference_means.npy'; check(reference,load(iv/'reference_receipt.json')['sha256'])
    rf=next(x for x in ir['estimation']['primary_rows'] if x['estimator']=='reduced_form_kindness_per_SD_Z' and x['clustering']=='chooser_CR0')
    if not math.isclose(rf['residual_instrument_sd'],core.PILOT_Z_SD,rel_tol=0,abs_tol=1e-15): raise RuntimeError('Pilot scale changed')
    audit={'validity_report_sha256':VALIDITY_SHA,'pilot_report_sha256':IV_SHA,
           'comparison_frame_sha256':ff['sha256'],'comparison_ledger_sha256':lf['sha256'],
           'reused_reference_sha256':sha(reference),'expected_comparison_games':1912023,
           'network_requests':0,'raw_API_scan_repeated':False,'chronology_scan_repeated':False,
           'numerical_score_routines_match_completed_pilot':True}
    js(public/'input_verification.json',audit); js(private/'private_input_paths.json',{'validity':str(old),'iv':str(iv),'frame':str(frame),'ledger':str(ledger)})
    log('UPLOADED_LINEAGES_AND_REUSED_COMPARISON_INPUTS_VERIFIED')
    return old,iv,frame,ledger


def prepare_frame(args,framepath,ledgerpath,private,public):
    pa,_=deps(); frame=read(framepath); ledger=read(ledgerpath)
    if len(frame)!=1912023 or len(ledger)!=len(frame): raise RuntimeError('Comparison frame row count changed')
    ids=frame['game_id'].to_pylist(); gids=np.asarray(ids,dtype='U8')
    # Match explicitly by exact game ID. Row order is never assumed.
    lg=np.asarray(ledger['game_id'].to_pylist(),dtype='U8'); order=np.argsort(lg)
    if len(np.unique(lg))!=len(lg): raise RuntimeError('Duplicate game IDs in source ledger')
    index=num.lookup(lg[order],gids)
    if np.any(index<0): raise RuntimeError('Ledger lost comparison games')
    ledger=ledger.take(pa.array(order[index]))
    final=private/'pilot200k'; existing=done(final,args.conf)
    if not existing:
        # Critically, select using frame IDs alone. Do not supply the ledger to selection.
        selected=core.independent_indices(ids,args.pilot_size)
        tmp=newdir(final); chosen=frame.take(pa.array(selected))
        write(tmp/'frame.parquet',chosen)
        js(tmp/'sampling_receipt.json',{'frame_rows':len(frame),'selected_rows':len(chosen),
             'sampling_rule':'SHA256 fixed-seed bottom-k with game-ID tie-break; keep original recipient orientation',
             'seed':core.PILOT_SAMPLE_SEED.decode(),'selected_without_source_status_or_availability':True,
             'conditional_sampling_fraction':len(chosen)/len(frame),'historical_matchmaker_randomization_claimed':False})
        finish(tmp,final,args.conf)
    chosen=read(final/'frame.parquet'); smallset=set(chosen['game_id'].to_pylist())
    if len(smallset)!=args.pilot_size: raise RuntimeError('Frozen independent pilot size mismatch')
    source=ledger['source'].to_pylist(); ready=np.asarray(ledger['metadata_usable_records'].to_numpy())>0
    explicit=np.array([s is not None for s in source]); pool=np.array([s=='pool' for s in source])
    conflict=np.asarray(ledger['source_conflict'].to_numpy(),bool)
    known=(explicit & ~conflict & ready)
    if int(known.sum())!=147420 or int(pool.sum())!=133753:
        raise RuntimeError('Source-known comparison counts do not reproduce uploaded report')
    in_stage=np.asarray(ledger['in_certified_stage07'].to_numpy(),bool)
    rows=[]
    for label,m in [('whole_comparison_frame',np.ones(len(frame),bool)),('metadata_known_original_subset',known),
                    ('explicit_pool_original_subset',pool & known),('independent_200k_all_sources',np.array([g in smallset for g in ids]))]:
        rows.append(dict(sample=label,games=int(m.sum()),certified_stage07_games=int(in_stage[m].sum()),
                         pool_source_games=int(pool[m].sum()),metadata_known=int(known[m].sum())))
    csvout(public/'sample_flow.csv',rows)
    counts=Counter((core.safe_source(s),core.terminal_label(st)) for s,st,k in zip(source,ledger['api_status'].to_pylist(),known) if k)
    csvout(public/'status_breakdown.csv',[dict(sample='source_known_selected_subset',source=s,status=st,games=n) for (s,st),n in sorted(counts.items())])
    # Only about 330k rows at most are retained in memory for reconciliation.
    needed=known | np.array([g in smallset for g in ids])
    keep=np.flatnonzero(needed)
    f=frame.take(pa.array(keep)); l=ledger.take(pa.array(keep))
    joined={r['game_id']:(r,s) for r,s in zip(f.to_pylist(),l.to_pylist())}
    log(f'INDEPENDENT_PILOT_FROZEN games={args.pilot_size:,}; metadata_known_subset={int(known.sum()):,}')
    return joined,smallset,rows


def metadata_jobs(old):
    jobs=load(old/'source_scan_jobs_PRIVATE.json'); selected=[]; seen=set()
    for j in jobs:
        root=Path(j['out']).resolve()
        if not root.is_relative_to(old.resolve()): raise RuntimeError('Source checkpoint outside authenticated validity root')
        if root in seen: raise RuntimeError('Duplicate source-scan checkpoint');
        seen.add(root)
        p,f,r=receipt_file(root,VALIDITY_CONFIG,'metadata.parquet',verify=False)
        # Even zero-row metadata artifacts are verified during the worker stage.
        selected.append({'path':str(p),'sha256':f['sha256'],'bytes':f['bytes'],'rows':int(r.get('metadata_rows',-1))})
    return selected


def read_metadata_job(job):
    check(job['path'],job['sha256'])
    if job['rows']==0: return [],1
    t=read(job['path'],['game_id','metadata_json'])
    if job['rows']>=0 and len(t)!=job['rows']: raise RuntimeError('Metadata checkpoint row count changed')
    result=[]
    for r in t.to_pylist():
        obj=json.loads(r['metadata_json'])
        if not isinstance(obj,dict): raise RuntimeError('Metadata JSON is not an object')
        out,errors=core.normalize_export(obj,r['game_id']); result.append((out,errors))
    return result,1


def audited_schema():
    pa,_=deps()
    base=[('game_id',pa.string()),('source',pa.string()),('status',pa.string()),('api_start_ms',pa.int64()),
        ('anchor_ms',pa.int64()),('rated',pa.bool_()),('variant',pa.string()),('speed',pa.string()),
        ('winner',pa.string()),('tc_base_s',pa.int64()),('tc_inc_s',pa.int64())]
    for side in ('white','black'):
        base += [(side+'_username',pa.string()),(side+'_rating',pa.float64()),(side+'_provisional',pa.bool_())]
    base += [('metadata_records_audited',pa.int64()),('error_codes',pa.string()),('metadata_valid',pa.bool_()),
             ('in_independent_pilot',pa.bool_()),('in_source_known_subset',pa.bool_()),('month',pa.string()),
             ('archive_start_ms',pa.int64()),('recipient_id',pa.int64()),('opponent_id',pa.int64()),
             ('recipient_color',pa.string()),('stage07_identity_agrees',pa.bool_()),('in_certified_stage07',pa.bool_())]
    return pa.schema(base)


def consolidate(args,old,joined,smallset,private,public):
    pa,_=deps(); final=private/'audited_metadata'; existing=done(final,args.conf)
    if existing: rows=read(final/'records.parquet').to_pylist()
    else:
        jobs=metadata_jobs(old); bygame=defaultdict(list); start=time.monotonic(); completed=0
        log(f'CACHED_METADATA_AUDIT_BEGIN files={len(jobs):,}; no raw NDJSON is opened')
        with cf.ThreadPoolExecutor(max_workers=min(args.workers,6)) as ex:
            # executor.map order keeps peak completed-result buffering bounded with small input files.
            for records,_ in ex.map(read_metadata_job,jobs):
                for r,e in records:
                    if r['game_id'] in joined: bygame[r['game_id']].append((r,e))
                completed+=1
                if completed%1000==0 or completed==len(jobs): log(f'CACHED_METADATA_AUDIT {completed}/{len(jobs)} elapsed_min={(time.monotonic()-start)/60:.1f}')
        rows=[]
        for gid,(frame,ledger) in sorted(joined.items()):
            r,errs=core.merge_records(bygame.get(gid,[]),gid)
            errors=core.validate_metadata(r,frame,ledger,errs)
            r.update(error_codes=';'.join(errors),metadata_valid=not errors,in_independent_pilot=gid in smallset,
                in_source_known_subset=bool(ledger.get('source') is not None and not ledger['source_conflict'] and ledger['metadata_usable_records']>0),
                month=frame['month'],archive_start_ms=frame['utc_ms'],recipient_id=frame['recipient_id'],
                opponent_id=frame['opponent_id'],recipient_color=frame['recipient_color'],
                stage07_identity_agrees=ledger['stage07_identity_agrees'],in_certified_stage07=ledger['in_certified_stage07'])
            rows.append(r)
        tmp=newdir(final); write(tmp/'records.parquet',pa.Table.from_pylist(rows,schema=audited_schema())); finish(tmp,final,args.conf)
    errors=Counter()
    for r in rows:
        for e in r['error_codes'].split(';'):
            if e: errors[(r['in_independent_pilot'],e)]+=1
    csvout(public/'metadata_audit.csv',[{'in_independent_pilot':s,'error_code':e,'games':n} for (s,e),n in sorted(errors.items())])
    readiness=Counter()
    pending=[]
    for r in rows:
        if not r['in_independent_pilot']: continue
        state=('READY_POOL' if r['source']=='pool' else 'READY_NONPOOL') if r['metadata_valid'] else 'PENDING_METADATA'
        readiness[(r['month'],state)]+=1
        if state=='PENDING_METADATA': pending.append({'game_id':r['game_id'],'month':r['month'],'reason':r['error_codes']})
    rp=[{'month':m,'status':s,'games':n} for (m,s),n in sorted(readiness.items())]
    if sum(r['games'] for r in rp)!=args.pilot_size: raise RuntimeError('Independent-pilot denominator changed')
    csvout(public/'pilot200k_readiness.csv',rp)
    out=private/'pilot200k_readiness'; oldc=done(out,args.conf)
    if not oldc:
        tmp=newdir(out)
        write(tmp/'pending_API_targets.parquet',pa.Table.from_pylist(pending,schema=pa.schema([('game_id',pa.string()),('month',pa.string()),('reason',pa.string())])))
        subset=[r for r in rows if r['in_independent_pilot']]
        write(tmp/'cached_metadata.parquet',pa.Table.from_pylist(subset,schema=audited_schema()))
        js(tmp/'retrieval_plan.json',{'target_rows':len(pending),'independent_pilot_rows':args.pilot_size,
             'network_requests_started':0,'source_rule':'explicit only; never infer missing pool status',
             'next_phase':'reconcile these exact IDs against any ongoing/new API cache before fetching; one Lichess API job at a time',
             'do_not_replace_nonreturns_with_other_games':True,'full_denominator_preserved':True})
        finish(tmp,out,args.conf)
    log(f'PILOT200K_PENDING_TARGETS_PREPARED n={len(pending):,}; NO_NETWORK')
    candidates=[]
    for r in rows:
        if not (r['in_source_known_subset'] and r['metadata_valid'] and r['source']=='pool' and core.normal_group(r['status'],True)): continue
        if r['anchor_ms']+90*core.DAY>core.PANEL_END: continue
        side=r['recipient_color']; other='black' if side=='white' else 'white'
        q=dict(r,sample_row=len(candidates),month_code=core.MONTHS.index(r['month']),
               recipient_rating=r[side+'_rating'],opponent_rating=r[other+'_rating'],
               recipient_username=r[side+'_username'],opponent_username=r[other+'_username'])
        candidates.append(q)
    return rows,candidates,len(pending)


def stage_paths(args):
    root=args.project_root/'derived/replication/analysis_panel_24m_sf100k'
    check(root/'_SUCCESS.json',STAGE_SHA)
    with (root/'_manifests/month_status.csv').open() as f: rows=list(csv.DictReader(f))
    if [r['month'] for r in rows]!=list(core.MONTHS): raise RuntimeError('Stage07 month manifest changed')
    return [(root/f'month={r["month"]}/analysis_panel.parquet',r['output_sha256']) for r in rows]


def identity_month(job):
    pa,pq=deps(); import pyarrow.compute as pc
    path=check(job['path'],job['sha']); ids=pa.array(job['ids'],type=pa.int64()); names=pa.array(job['names'],type=pa.string())
    found=set()
    cols=['chooser_user_id','disconnected_user_id','chooser_username_norm','disconnected_username_norm']
    for batch in pq.ParquetFile(path).iter_batches(columns=cols,batch_size=131072,use_threads=False):
        t=pa.Table.from_batches([batch])
        for idcol,nmcol in [('chooser_user_id','chooser_username_norm'),('disconnected_user_id','disconnected_username_norm')]:
            mask=pc.or_(pc.is_in(t[idcol],value_set=ids),pc.is_in(t[nmcol],value_set=names))
            filtered=t.select([idcol,nmcol]).filter(mask)
            for rr in filtered.to_pylist(): found.add((rr[idcol],rr[nmcol]))
    return sorted(found,key=lambda x:(x[0],str(x[1])))


def identity_check(args,candidates,private,public):
    pa,_=deps(); final=private/'identity'; chk=done(final,args.conf)
    if chk:
        info=load(final/'audit.json'); js(public/'identity_audit.json',info)
        if info['conflicting_queries']: return False
        return True
    required=sorted({int(r[k]) for r in candidates for k in ('recipient_id','opponent_id')})
    names=sorted({r[k] for r in candidates for k in ('recipient_username','opponent_username')})
    pairs=set(); jobs=[{'path':str(p),'sha':s,'ids':required,'names':names} for p,s in stage_paths(args)]
    workers=max(1,min(args.workers,4,int((args.memory_gb-2)//1.5)))
    log(f'IDENTITY_CHECK_BEGIN months=24 workers={workers}; no all-game chronology scan')
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        for k,found in enumerate(ex.map(identity_month,jobs),1): pairs.update(found); log(f'IDENTITY_CHECK_MONTH {k}/24')
    idnames=defaultdict(set); nameids=defaultdict(set)
    for ident,name in pairs:
        idnames[ident].add(name)
        if isinstance(name,str): nameids[name].add(ident)
    conflicts=[]; missing=0
    for r in candidates:
        bad=[]
        for role in ('recipient','opponent'):
            ident,name=r[role+'_id'],r[role+'_username']
            ni,ii=idnames.get(ident,set()),nameids.get(name,set())
            if (ni and ni!={name}) or (ii and ii!={ident}): bad.append(role)
            elif not ni and not ii: missing+=1
        if bad: conflicts.append({'game_id':r['game_id'],'roles':','.join(bad)})
    info={'queries':len(candidates),'conflicting_queries':len(conflicts),
          'participant_occurrences_absent_from_24m_Stage07_identity_map':missing,
          'absence_does_not_trigger_person_exclusion':True,'numeric_and_normalized_name_crosschecks':True,
          'automatic_identity_repairs':0,'gate':'BLOCKED_IDENTITY' if conflicts else 'IDENTITY_CHECK_PASSED'}
    tmp=newdir(final); write(tmp/'conflicts.parquet',pa.Table.from_pylist(conflicts,schema=pa.schema([('game_id',pa.string()),('roles',pa.string())])))
    js(tmp/'audit.json',info); finish(tmp,final,args.conf); js(public/'identity_audit.json',info)
    return not conflicts


def load_histories(parts,people):
    pa,pq=deps(); import pyarrow.compute as pc
    cols=['j','i','t','start','ord','gid','y','arm','fair','cell']; tabs=[]
    if not len(people):
        return {k:np.array([],dtype=('U8' if k=='gid' else bool if k in ('y','arm','fair') else np.int64)) for k in cols}
    pset=pa.array(np.unique(people),type=pa.int64())
    for p in parts:
        for batch in pq.ParquetFile(p).iter_batches(columns=cols,batch_size=131072,use_threads=False):
            t=pa.Table.from_batches([batch]); keep=pc.is_in(t['j'],value_set=pset)
            selected=t.filter(keep)
            if len(selected): tabs.append(selected)
    if not tabs:
        return {k:np.array([],dtype=('U8' if k=='gid' else bool if k in ('y','arm','fair') else np.int64)) for k in cols}
    t=pa.concat_tables(tabs)
    return {k:(np.asarray(t[k].to_pylist(),dtype='U8') if k=='gid' else array(t,k)) for k in cols}


def history_shard(job):
    pa,_=deps(); final=Path(job['out']); chk=done(final,job['conf'])
    if chk: return chk
    qtab=read(job['queries']); q={k:(np.array(qtab[k].to_pylist(),dtype='U8') if k=='game_id' else array(qtab,k)) for k in qtab.column_names}
    qj={k:v[(num.user_hash(q['opponent_id'])%16)==job['shard']] for k,v in q.items()}
    qi={k:v[(num.user_hash(q['recipient_id'])%16)==job['shard']] for k,v in q.items()}
    h=load_histories(job['parts'],np.r_[qj['opponent_id'],qi['recipient_id']])
    tmp=newdir(final); outcomes=core.first_other_and_history(h,qi); write(tmp/'outcomes.parquet',pa.table(outcomes))
    scores={'sample_row':qj['sample_row']}; model=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
    arm=h['arm']; hj,hi,ht,hy,hc=(h[k][arm] for k in ['j','i','t','y','cell'])
    for l,lag in enumerate((7,30)):
        values={n:np.zeros(len(qj['sample_row']),np.int64) for n in ('n','counterparts','pair_removed')}
        values.update({n:np.full(len(qj['sample_row']),np.nan) for n in ('raw','expected','adjusted')})
        for m in np.unique(qj['month_code']):
            ix=np.flatnonzero(qj['month_code']==m)
            r=num.score_month(hj,hi,ht,hy,hc,qj['opponent_id'][ix],qj['recipient_id'][ix],
                 int(core.STARTS[int(m)]-lag*core.DAY),model[l,int(m)],folds=4)
            for k in values: values[k][ix]=r[k]
        for k,v in values.items(): scores[f'{k}_{lag}d']=v
    write(tmp/'scores.parquet',pa.table(scores))
    return finish(tmp,final,job['conf'],{'outcome_queries':len(qi['sample_row']),'score_queries':len(qj['sample_row']),'loaded_history_rows':len(h['j'])})


def build_analysis(args,iv,candidates,private,public):
    pa,pq=deps(); qdir=private/'normal_queries'; qpath=qdir/'queries.parquet'
    qcols=['sample_row','game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code']
    if not done(qdir,args.conf):
        tmp=newdir(qdir); write(tmp/'queries.parquet',pa.Table.from_pylist([{k:r[k] for k in qcols} for r in candidates])); finish(tmp,qdir,args.conf)
    # Verify only projection artifacts used here, never rescan the billions-row chronology.
    paths_by_shard=[[] for _ in range(16)]
    for k,m in enumerate(core.MONTHS,1):
        root=iv/'projection'/f'month={m}'
        for s in range(16):
            p,_,_=receipt_file(root,IV_CONFIG,f'shard-{s:02d}.parquet')
            paths_by_shard[s].append(str(p))
        if k%4==0: log(f'REUSED_PROJECTION_HASHES {k}/24 months')
    jobs=[{'parts':parts,'queries':str(qpath),'reference':str(iv/'reference_means.npy'),
           'out':str(private/'history_shards'/f'shard-{s:02d}'),'conf':args.conf,'shard':s} for s,parts in enumerate(paths_by_shard)]
    peak=max(sum(pq.ParquetFile(p).metadata.num_rows for p in parts) for parts in paths_by_shard)*240+250*1024**2
    workers=max(1,min(args.workers,4,int(max(1,(args.memory_gb-2)*1024**3//peak))))
    log(f'NORMAL_GAME_SCORES_OUTCOMES_BEGIN queries={len(candidates):,} workers={workers}')
    results=[]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        for k,r in enumerate(ex.map(history_shard,jobs),1): results.append(r); log(f'NORMAL_GAME_HISTORY_SHARD {k}/16')
    d={k:np.asarray([r[k] for r in candidates]) for k in ('sample_row','game_id','status','recipient_id','opponent_id',
               'archive_start_ms','anchor_ms','month_code','tc_base_s','tc_inc_s','recipient_rating','opponent_rating')}
    for name in ('scores.parquet','outcomes.parquet'):
        tabs=[read(Path(j['out'])/name) for j in jobs]; t=pa.concat_tables(tabs); order=np.argsort(array(t,'sample_row',np.int64))
        t=t.take(pa.array(order))
        if not np.array_equal(array(t,'sample_row',np.int64),np.arange(len(candidates))): raise RuntimeError('History join lost/duplicated query rows')
        for col in t.column_names:
            if col!='sample_row': d[col]=array(t,col)
    if np.any(d['y'] & ~d['reached']): raise RuntimeError('Nonreacher coded kind')
    if np.any(d['reached'] & ((d['outcome_opponent']==d['opponent_id']) | (d['outcome_start']<=d['anchor_ms']))):
        raise RuntimeError('Invalid later other-opponent outcome')
    afinal=private/'analysis'; previous=done(afinal,args.conf)
    if not previous:
        tmp=newdir(afinal); write(tmp/'exploratory_analysis_PRIVATE.parquet',pa.table(d)); finish(tmp,afinal,args.conf)
    js(public/'history_diagnostics.json',{'queries':len(candidates),'reached':int(d['reached'].sum()),
        'kind_outcomes':int(d['y'].sum()),'unique_recipients':len(np.unique(d['recipient_id'])),
        'unique_opponents':len(np.unique(d['opponent_id'])),'repeated_exposures_per_recipient_allowed':True,
        'same_original_opponent_outcomes':0,'original_reference_model_reused':True,
        'timing':'month-start minus 7/30 days for histories; future games must start after focal API lastMoveAt; future lastMoveAt within 90d',
        'terminal_click_timestamp_observed':False,'chat_or_takeback_history_observed':False})
    return d


def estimate(d,public):
    specs=[('narrow_7d_floor5',False,7,5,False),('broad_draws_7d_floor5',True,7,5,False),
           ('narrow_7d_floor1',False,7,1,False),('narrow_7d_floor10',False,7,10,False),
           ('narrow_30d_floor5',False,30,5,False),('narrow_7d_floor5_recipient_history',False,7,5,True)]
    support=[]; estimates=[]
    for label,broad,lag,floor,hist in specs:
        status=np.isin(d['status'],list(core.BROAD if broad else core.NARROW))
        mask=status & (d[f'n_{lag}d']>=floor) & np.isfinite(d[f'adjusted_{lag}d']) & np.isfinite(d[f'expected_{lag}d'])
        nr=int(mask.sum()); ny=int(d['y'][mask].sum()); nj=len(np.unique(d['opponent_id'][mask])); ni=len(np.unique(d['recipient_id'][mask])); nd=len(np.unique(d['archive_start_ms'][mask]//core.DAY))
        base={'specification':label,'n':nr,'kind_outcomes':ny,'reached':int(d['reached'][mask].sum()),
             'recipients':ni,'opponents':nj,'exposure_dates':nd,'history_lag_days':lag,'minimum_prior_decisions':floor,
             'sample_is_availability_selected':True,'validity_test_pass_claimed':False}
        support.append(base)
        reasons=[]
        if nr<500: reasons.append('FEWER_THAN_500_ROWS')
        if ny<10: reasons.append('FEWER_THAN_10_KIND_OUTCOMES')
        if min(ni,nj,nd)<20: reasons.append('FEWER_THAN_20_ACCOUNTS_OR_EXPOSURE_DATES')
        if reasons:
            estimates.append({**base,'supported':False,'reason':';'.join(reasons)}); continue
        residual,diag=core.model_design(d,mask,lag,with_history=hist)
        z,y,reach=residual.T
        for outcome,values in [('zero_coded_other_opponent_kindness',y),('reach_other_opponent_opportunity',reach)]:
            for withdate in (False,True):
                result=core.fit_reduced_form(values,z,d['recipient_id'][mask],d['opponent_id'][mask],d['archive_start_ms'][mask]//core.DAY,withdate)
                estimates.append({**base,**diag,**result,'outcome':outcome,
                  'clustering':'shared_account_or_date_CR0' if withdate else 'shared_account_dyadic_CR0',
                  'control_specification':'pregame_export_observed_W; not identical to IV pilot W (RD unavailable)',
                  'historical_score_treated_as_fixed':True})
        log(f'EXPLORATORY_PLACEBO_ESTIMATED {label} n={nr:,}')
    csvout(public/'placebo_support.csv',support); csvout(public/'exploratory_placebos.csv',estimates)
    return sum(bool(r.get('supported')) for r in estimates)


def render_report(s):
    return f'''# Source-known exploratory placebo and independent pilot preparation

Run: {s['run_id']}. Status: {s['status']}.

## Scope and limits
This is a local exploratory exercise on an availability-selected subset, not an exclusion certificate.
The independent 200,000-game pilot was selected from all 1,912,023 original comparison games before
metadata or terminal status entered selection. Its original randomized recipient orientation is retained.
No games were substituted for missing/nonreturning records. No network requests were made.

## Outputs
- Source-known candidate normal-ending games after metadata/follow-up checks: **{s.get('normal_candidates',0):,}**.
- Supported exploratory coefficient rows: **{s.get('supported_coefficient_rows',0)}**.
- Independent pilot size: **{s['pilot_size']:,}**.
- Independent pilot IDs still needing metadata: **{s.get('pending_api_targets',0):,}**.

Read status_breakdown.csv before interpreting the placebo. If normal endings are absent, or a
specification lacks support, the program reports NOT_ESTIMATED / its explicit reason. That is not a null finding.
The narrow placebo uses mate/resign/stalemate; the broader version adds draw. Both exclude timeout and
outoftime. Out-of-time games remain in the independent pilot denominator and source-known status audit.
No all-game selection regression is run on the 7.7% fragment.

## Scores, outcomes and controls
Scores reuse the completed IV pilot's cross-fitted state reference and exact leave-all-pair-out
numerical routines. Histories end before the first day of the exposure month minus 7 or 30 days;
missing history is not a zero generosity score. The primary support floor is five earlier decisions.
The first future fair opportunity against someone OTHER than the original opponent is found separately
for every sampled exposure. An intervening encounter with the same opponent is skipped, not the person.
Future games must start after the focal API lastMoveAt; their own lastMoveAt must be within 90 days.
No qualifying opportunity is coded zero only with complete administrative follow-up.
LastMoveAt is an anchor, not a certified terminal-decision timestamp.

Controls use pregame export ratings, exact time controls, month/rating cells, exposure day and hour,
and chooser-history size/composition. Pregame RD and full prior 30-day game volume are unavailable here;
this is NOT a claim to have reproduced every pilot covariate. A recipient-history variant is separate.
Identity mismatches block all exploratory estimates rather than silently selecting favorable repairs.

## Inference and comparison scale
The table reports coefficients both per native residual SD and per the IV pilot's fixed score SD
({core.PILOT_Z_SD:.15f}). The latter is the appropriate unit for comparing the magnitude with the
pilot reduced form ({100*core.PILOT_RF:.6f} percentage points). Comparable units do not make the
populations or controls identical. Confidence intervals and 80% detectable-effect approximations are shown.
Shared-account dyadic CR0 handles accounts in either role; the second version also allows same-date
correlation. Generated-score uncertainty and wider network dependencies remain unaccounted for.
Nonpositive covariance estimates are flagged rather than repaired. Normal approximations are suppressed
with fewer than 500 rows, 10 positive kindness outcomes, or 20 recipient/opponent/date clusters.
Descriptive equivalence checks use the 90% interval and margins of ±0.03 and ±0.015 pp on the common scale;
even a tight interval in this selected sample does not certify exclusion.

## Next independent-sample stage
The exact pending IDs are in the PRIVATE pilot200k_readiness/pending_API_targets.parquet file.
They should be reconciled against other completed or running API recovery caches before a single,
rate-limited retrieval job. The current runner deliberately does not compete with API jobs.
Do not estimate a population selection effect by deleting unresolved source rows from this denominator.
Chat and takeback histories have not been recovered; an absent field does not mean no interaction.
'''


def execute(a):
    a.project_root=a.project_root.expanduser().resolve(); a.desktop_root=a.desktop_root.expanduser().resolve()
    if not a.project_root.is_dir(): raise RuntimeError('Project root is not mounted')
    if not 1<=a.workers<=10 or a.memory_gb<6 or a.pilot_size!=200000: raise RuntimeError('Use 1-10 workers, >=6 GiB and the fixed 200000 pilot size')
    if not re.fullmatch('[A-Za-z0-9_-]+',a.run_id): raise RuntimeError('Invalid run ID')
    private=a.project_root/'derived/replication/chooser_leniency_preliminary_v100_PRIVATE'/a.run_id
    public=a.project_root/'output/chooser_leniency_preliminary_v100'/a.run_id
    private.mkdir(parents=True,exist_ok=True); public.mkdir(parents=True,exist_ok=True); a.desktop_root.mkdir(parents=True,exist_ok=True)
    lock=(private/'RUN.lock').open('a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This run is already active')
    package=Path(__file__).parent
    config={'version':VERSION,'validity_report_sha256':VALIDITY_SHA,'pilot_report_sha256':IV_SHA,
         'pilot_size':a.pilot_size,'seed':core.PILOT_SAMPLE_SEED.decode(),'network_requests_permitted':False,
         'scripts':{p.name:sha(p) for p in sorted(package.glob('*.py'))}}
    a.conf=cfgsha(config)
    if (private/'config.json').exists() and load(private/'config.json')!=config: raise RuntimeError('Resume configuration changed')
    js(private/'config.json',config)
    completed=private/'_SUCCESS.json'
    if completed.exists():
        prev=load(completed)
        if prev['config_sha256']!=a.conf: raise RuntimeError('Completed run config mismatch')
        log('ALREADY_COMPLETE '+str(private)); lock.close(); return 0
    start=time.monotonic(); stage='preflight'
    s={'version':VERSION,'run_id':a.run_id,'pilot_size':a.pilot_size,'config_sha256':a.conf,'network_requests':0,
       'all_game_selection_estimated':False,'causal_identification_certified':False}
    try:
        free=shutil.disk_usage(a.project_root).free
        if free<12*1024**3: raise RuntimeError('At least 12 GiB free space is required')
        log(f'PRELIMINARY_PREFLIGHT workers={a.workers} memory_GiB={a.memory_gb} free_GiB={free/1024**3:.1f}')
        stage='authenticate'; old,iv,frame,ledger=authenticate(a,private,public)
        stage='freeze_independent_pilot'; joined,smallset,_=prepare_frame(a,frame,ledger,private,public)
        stage='audit_cached_metadata'; rows,candidates,pending=consolidate(a,old,joined,smallset,private,public)
        s.update(normal_candidates=len(candidates),pending_api_targets=pending)
        # Preserve immediately useful diagnostics before optional larger history work.
        js(public/'summary.json',{**s,'status':'METADATA_AND_INDEPENDENT_PILOT_READY'})
        zipreport(public,a.desktop_root,a.run_id+'_STATUS')
        stage='exploratory_placebo'; s['supported_coefficient_rows']=0
        if not candidates:
            s['placebo_status']='NOT_ESTIMATED_NO_AUDITED_NORMAL_ENDINGS'
            csvout(public/'placebo_support.csv',[{'sample':'source_known_normal_endings','n':0,'status':s['placebo_status']}])
            csvout(public/'exploratory_placebos.csv',[{'supported':False,'reason':'NO_AUDITED_NORMAL_ENDINGS','not_a_null_finding':True}])
        elif not identity_check(a,candidates,private,public):
            s['placebo_status']='NOT_ESTIMATED_IDENTITY_GATE'
            csvout(public/'exploratory_placebos.csv',[{'supported':False,'reason':'IDENTITY_DISAGREEMENT','not_a_null_finding':True}])
        else:
            stage='scores_and_other_opponent_outcomes'; d=build_analysis(a,iv,candidates,private,public)
            stage='exploratory_regressions'; s['supported_coefficient_rows']=estimate(d,public)
            s['placebo_status']='EXPLORATORY_ONLY' if s['supported_coefficient_rows'] else 'NOT_ESTIMATED_INSUFFICIENT_SUPPORT'
        s.update(status='CHOOSER_LENIENCY_PRELIMINARY_V100_COMPLETE_WITH_OPEN_GATES',elapsed_seconds=time.monotonic()-start)
        js(public/'summary.json',s)
        js(public/'open_assumptions.json',{'source_known_sample':'availability-selected; not representative; no exclusion pass/fail',
           'independent_pilot':'frozen denominator; missing metadata listed; no fetch yet',
           'chat_takebacks':'unobserved; no no-interaction sample inferred','all_game_selection':'not estimated',
           'ordinary_terminal_result':'does not establish no transient disconnect','cross_role_dependence':'CR0 shared-account/date approximation',
           'generated_score':'treated as fixed','monotonicity':'not tested by placebo'})
        (public/'REPORT.md').write_text(render_report(s))
        if (public/'failure_summary.json').exists():
            os.replace(public/'failure_summary.json',private/('previous_failure_'+uuid.uuid4().hex+'.json'))
        dest=zipreport(public,a.desktop_root,a.run_id)
        js(completed,{'status':s['status'],'config_sha256':a.conf,'report_sha256':sha(dest),'report_path':str(dest)})
        log(s['status']); log(s['placebo_status']); log('NO_API_REQUESTS_MADE')
        log('PRIVATE_OUTPUT '+str(private)); log('Resume ID: '+a.run_id); return 0
    except BaseException as e:
        (private/'exception_PRIVATE.txt').write_text(traceback.format_exc())
        js(public/'failure_summary.json',{'status':'PRELIMINARY_BLOCKED','stage':stage,'exception_type':type(e).__name__})
        (public/'REPORT.md').write_text(f'# Preliminary run stopped\n\nStage: {stage}. Exception: {type(e).__name__}.\nCompleted files remain preserved. Detailed traceback is private. No causal conclusion.\n')
        zipreport(public,a.desktop_root,a.run_id+'_BLOCKED'); log('BLOCKED '+str(e)); return 2
    finally: lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10); p.add_argument('--memory-gb',type=float,default=8)
    p.add_argument('--pilot-size',type=int,default=200000)
    p.add_argument('--run-id',default=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid()))
    p.add_argument('--execute',action='store_true'); a=p.parse_args()
    if not a.execute: p.error('Pass --execute')
    os.umask(0o077); return execute(a)
if __name__=='__main__': sys.exit(main())
