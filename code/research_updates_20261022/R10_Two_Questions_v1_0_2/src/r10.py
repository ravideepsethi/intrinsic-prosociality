#!/usr/bin/env python3
"""R10: four joint chooser-FE models and cluster-robust aggregate contrast tables.

All new code; original 41.5m-row input is read-only. No web/API/PGN/Stockfish.
Requires DuckDB, PyArrow, Pandas, NumPy, Python 3.10+. Safe for Mac.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, csv, datetime as dt, hashlib, json
import math, os, sys, time, traceback, zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from r10_math import (NAMES,INDEX,POSITION,STAGE,SPEED,MONTHS,
    chooser_crossproducts, chooser_within, identified, solve_gram,
    construct_design, model_indices, position_vector,stage_vector,
    contrast,holm,p_value,rate_if_covariance,
    solve_gram_rank_aware, estimable_linear)

VERSION='1.0.2'
OLD_V101_PRODUCER_SHA256='fb6ed0f40d9a81c606e2682a1e15520a40fbe338648bec4f2933379b88ffa8f8'
EXPECTED={'opportunities':41534331,'grants':570091,'competitive':15207423,
          'competitive_grants':419463,'clearly_worse':22664818,
          'clearly_worse_grants':106556,'choosers':3224173}
ALIASES={
 'chooser':['chooser_user_id','chooser_id','chooser','chooser_username'],
 'grant':['outcome_kind_draw','grant','kind_draw','is_kind_draw'],
 'v':['engine_eval_cp_disconnected','eval_cp_disconnected','engine_eval_cp','v'],
 'ply':['ply_count','ply','num_plies'],
 'speed':['api_speed','speed','speed_category'],
 'month':['month','game_month','partition_month'],
 'kappa':['chooser_win_premium_v2','chooser_win_premium','kappa','forgone_premium'],
 'rd_chooser':['chooser_pre_rd_v2','chooser_pre_rd','chooser_rd'],
 'rd_opponent':['disconnected_pre_rd_v2','disconnected_pre_rd','opponent_rd'],
 'clock_chooser':['chooser_clock_last_obs_s','chooser_clock_s','chooser_seconds'],
 'clock_opponent':['disconnected_clock_last_obs_s','disconnected_clock_s','opponent_seconds'],
 'rating_chooser':['chooser_elo','chooser_rating','rating_chooser'],
 'rating_opponent':['disconnected_elo','disconnected_rating','opponent_rating'],
}


def quote(s):return "'"+str(s).replace("'","''")+"'"
def ident(s):return '"'+str(s).replace('"','""')+'"'
def now():return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def log(s):print(f'[{dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}] {s}',flush=True)
def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+'\n')
    os.replace(temp,path)
def atomic_npz(path,**items):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp.npz')
    np.savez_compressed(temp,**items)
    os.replace(temp,path)
def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while True:
            b=f.read(4*1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()
def files_for_input(inp):
    p=Path(inp).expanduser().resolve()
    if p.is_file() and p.suffix=='.parquet':return [p]
    if not p.is_dir():raise ValueError(f'--input not a Parquet file/directory: {p}')
    months=[p/f'month={mo}' for mo in MONTHS]
    if all(q.is_dir() for q in months):
        other=[q.name for q in p.iterdir() if q.is_dir() and q.name.startswith('month=') and q.name not in {f'month={mo}' for mo in MONTHS}]
        if other:raise ValueError('Unexpected additional months: '+str(other))
        files=[file.resolve() for q in months for file in sorted(q.glob('*.parquet'))]
        if not files or len({f.parent for f in files})>10000:raise ValueError('No supported monthly Parquet inputs')
        return files
    files=[f.resolve() for f in p.rglob('*.parquet') if not any(part.startswith('_audit') for part in f.parts)]
    if not files:raise ValueError(f'No supported Parquet files in {p}')
    return sorted(set(files))

def connect(root,threads,memory_gb):
    import duckdb
    c=duckdb.connect(database=':memory:')
    c.execute(f'SET threads={int(threads)}')
    c.execute('SET memory_limit='+quote(str(int(memory_gb))+'GB'))
    tmp=root/'private'/'spill';tmp.mkdir(parents=True,exist_ok=True)
    c.execute('SET temp_directory='+quote(str(tmp)))
    return c

def main_view(c,inputs):
    source='read_parquet(['+','.join(quote(str(x)) for x in inputs)+'], union_by_name=true, hive_partitioning=true)'
    desc=c.execute('DESCRIBE SELECT * FROM '+source+' LIMIT 0').fetchall()
    columns={z[0].lower():z[0] for z in desc}
    found={}
    for semantic,choices in ALIASES.items():
        col=next((columns[x.lower()] for x in choices if x.lower() in columns),None)
        if col is None:raise ValueError(f'Missing required {semantic}; schema={sorted(columns)}')
        found[semantic]=col
    col=lambda key:'TRY_CAST('+ident(found[key])+' AS DOUBLE)'
    # code assignment is deliberately fixed, with five speed categories and 24 months
    speed='LOWER(TRIM(TRY_CAST('+ident(found['speed'])+' AS VARCHAR)))'
    month='SUBSTR(TRY_CAST('+ident(found['month'])+' AS VARCHAR),1,7)'
    v=col('v');ply=col('ply')
    pos=f'CASE WHEN {v}<=-300 THEN 0 WHEN {v}<=-101 THEN 1 WHEN {v}<=100 THEN 2 WHEN {v}<=299 THEN 3 ELSE 4 END'
    st=f'CASE WHEN {ply}<=4 THEN 0 WHEN {ply}<=6 THEN 1 WHEN {ply}<=8 THEN 2 WHEN {ply}<=10 THEN 3 WHEN {ply}<=20 THEN 4 WHEN {ply}<=40 THEN 5 WHEN {ply}<=80 THEN 6 ELSE 7 END'
    speedcase='CASE '+ ' '.join(f'WHEN {speed}={quote(sp)} THEN {i}' for i,sp in enumerate(SPEED)) + ' ELSE -1 END'
    monthcase='CASE '+ ' '.join(f'WHEN {month}={quote(mo)} THEN {i}' for i,mo in enumerate(MONTHS)) + ' ELSE -1 END'
    expr={
        'chooser':f'TRY_CAST({ident(found["chooser"])} AS VARCHAR)',
        'grant':f'TRY_CAST({ident(found["grant"])} AS INTEGER)',
        'v':v,'ply':f'TRY_CAST({ident(found["ply"])} AS BIGINT)',
        'pos':pos,'stage':st,'speed_i':speedcase,'month_i':monthcase,
        'kappa':col('kappa'),'rd_chooser':col('rd_chooser'),'rd_opponent':col('rd_opponent'),
        'clock_chooser':col('clock_chooser'),'clock_opponent':col('clock_opponent'),
        'gap':f'({col("rating_opponent")}-{col("rating_chooser")})',
        'speed_label':speed, 'month_label':month,
    }
    c.execute('CREATE OR REPLACE VIEW norm AS SELECT '+ ', '.join(f'{e} AS {ident(k)}' for k,e in expr.items())+' FROM '+source)
    return found

def preflight(c,root):
    log('[PRE] validating frozen opportunity sample and the rating/clock control fields')
    stats=c.execute('''SELECT COUNT(*) N, SUM(grant) grants,
        COUNT(DISTINCT chooser) choosers,
        SUM(CASE WHEN pos>=2 THEN 1 ELSE 0 END) competitive,
        SUM(CASE WHEN pos>=2 THEN grant ELSE 0 END) competitive_grants,
        SUM(CASE WHEN pos=0 THEN 1 ELSE 0 END) clearly_worse,
        SUM(CASE WHEN pos=0 THEN grant ELSE 0 END) clearly_worse_grants,
        SUM(CASE WHEN chooser IS NULL OR grant NOT IN (0,1) OR grant IS NULL
        OR v IS NULL OR v<>ROUND(v) OR ply IS NULL OR ply<0 OR speed_i<0 OR month_i<0
        OR kappa IS NULL OR kappa<=0 OR rd_chooser IS NULL OR rd_chooser<=0
        OR rd_opponent IS NULL OR rd_opponent<=0 OR gap IS NULL
        OR clock_chooser<0 OR clock_opponent<0 THEN 1 ELSE 0 END) bad,
        COUNT(DISTINCT month_i) AS n_months, MIN(month_i) AS first_month, MAX(month_i) AS last_month
        FROM norm''').fetchone()
    labels=['opportunities','grants','choosers','competitive','competitive_grants',
            'clearly_worse','clearly_worse_grants','invalid_rows','n_months','first_month','last_month']
    d=dict(zip(labels,stats))
    for k,v in EXPECTED.items():
        if d[k]!=v:raise ValueError(f'FAIL CLOSED sample mismatch {k}: observed {d[k]}, expected {v}; source likely not the 24-month pool/nonadjacent paper sample')
    if (d['invalid_rows'],d['n_months'],d['first_month'],d['last_month'])!=(0,24,0,23):
        raise ValueError('FAIL CLOSED: incomplete dates or invalid essential data: '+str(d))
    atomic_json(root/'public'/'sample_preflight.json',d)
    log(f"[PRE] verified N={d['opportunities']:,}, grants={d['grants']:,}, accounts={d['choosers']:,}, all 24 months")
    return d

def descriptives(c,root):
    data=c.execute('''SELECT pos,stage,speed_i,COUNT(*) n,SUM(grant) grants
                       FROM norm GROUP BY pos,stage,speed_i ORDER BY pos,stage,speed_i''').fetchdf()
    data['pos_name']=data.pos.map(lambda k:POSITION[int(k)])
    data['stage_name']=data.stage.map(lambda k:STAGE[int(k)])
    data['speed_name']=data.speed_i.map(lambda k:SPEED[int(k)])
    data['grant_rate_pp']=100*data.grants/data.n
    data.to_csv(root/'public'/'R10_raw_5x8x5.csv',index=False)
    comp=data.groupby(['stage','speed_i'],as_index=False)[['n','grants']].sum()
    n_stage=comp.groupby('stage').n.transform('sum')
    n_speed=comp.groupby('speed_i').n.transform('sum')
    comp['share_of_stage_pct']=100*comp.n/n_stage
    comp['share_of_speed_pct']=100*comp.n/n_speed
    comp['grant_rate_pp']=100*comp.grants/comp.n
    comp['stage_label']=comp.stage.map(lambda k:STAGE[int(k)])
    comp['speed_label']=comp.speed_i.map(lambda k:SPEED[int(k)])
    comp.to_csv(root/'public'/'R10_stage_speed_composition.csv',index=False)
    # Complete 5x8 support inventory, including zero-count classical cells.
    support=comp.set_index(['speed_i','stage'])
    full=[]
    for speed_id in range(5):
        for band in range(8):
            key=(speed_id,band)
            if key in support.index:
                match=support.loc[key]
                n=int(match['n']);g=int(match['grants'])
            else:n=g=0
            full.append({'speed':SPEED[speed_id], 'stage':STAGE[band],
                'opportunities':n,'grants':g,'grant_rate_pp':100*g/n if n else None,
                'observed':bool(n)})
    pd.DataFrame(full).to_csv(root/'public'/'R10_speed_stage_support_all40.csv',index=False)
    if int(data.n.sum())!=EXPECTED['opportunities']:raise ValueError('Descriptive cells do not partition sample')
    by_pos=data.groupby('pos').n.sum().reindex(range(5),fill_value=0).to_numpy(dtype=np.float64)
    by_stage=data.groupby('stage').n.sum().reindex(range(8),fill_value=0).to_numpy(dtype=np.float64)
    counts_pos=np.zeros((2,8),dtype=np.float64)
    counts_sp=np.zeros((5,8),dtype=np.float64)
    for row in data.itertuples(index=False):
        counts_pos[int(row.pos>=2),int(row.stage)]+=row.n
        counts_sp[int(row.speed_i),int(row.stage)]+=row.n
    # Raw profile by region/position to audit late-game composition.
    dpos=data.groupby(['pos','stage'],as_index=False)[['n','grants']].sum()
    dpos['grant_rate_pp']=100*dpos.grants/dpos.n
    dpos.to_csv(root/'public'/'R10_raw_position_by_stage.csv',index=False)
    return {'pos_n':by_pos,'stage_n':by_stage,'region_stage_n':counts_pos,'speed_stage_n':counts_sp,'raw':data}


def prepare_buckets(c,root,num_buckets,cols):
    private=root/'private'
    bucketroot=private/'buckets'
    sortedroot=private/'sorted'
    sortedroot.mkdir(parents=True,exist_ok=True)
    marker=private/'bucketed_complete.json'
    allsorted=[sortedroot/f'bucket_{i:03}.parquet' for i in range(num_buckets)]
    if not marker.exists():
        if bucketroot.exists():
            raise ValueError('Uncertified bucket output exists. Preserve it; choose a fresh run root instead of overwriting.')
        staging=private/('buckets_BUILDING_'+now())
        if staging.exists():raise ValueError('Bucket staging name conflict')
        log('[25%] Materialize private, chooser-hashed Parquet buckets (one full scan)')
        fields=','.join(ident(z) for z in cols)
        c.execute('COPY (SELECT '+fields+f',CAST(hash(chooser)%{num_buckets} AS INTEGER) bucket FROM norm) TO '
                  +quote(str(staging))+
                  ' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (bucket), ROW_GROUP_SIZE 200000)')
        os.replace(staging,bucketroot)
        atomic_json(marker,{'buckets':num_buckets,'columns':cols,'rows':EXPECTED['opportunities']})
    else:
        previous=json.loads(marker.read_text())
        if previous['buckets']!=num_buckets or previous['columns']!=cols:raise ValueError('Bucket definition changed across resume')
        log('[25%] Reusing completed bucket materialization')
    log('[25%] Sorting each bounded bucket by chooser; accounts never cross bucket boundaries')
    t0=time.monotonic()
    for b,dst in enumerate(allsorted):
        if dst.exists():continue
        src=bucketroot/f'bucket={b}'
        matches=sorted(src.glob('*.parquet')) if src.is_dir() else []
        if not matches:raise ValueError(f'Missing bucket {b}: {src}')
        source='read_parquet('+quote(str(src/'*.parquet'))+',union_by_name=true)'
        ordered='SELECT '+','.join(ident(z) for z in cols)+' FROM '+source+' ORDER BY chooser'
        tmp=dst.with_suffix('.temporary.parquet')
        if tmp.exists():tmp.unlink()  # last process died before atomic completion
        c.execute('COPY ('+ordered+') TO '+quote(str(tmp))+' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)')
        os.replace(tmp,dst)
        if (b+1)%8==0 or b==num_buckets-1:
            elapsed=time.monotonic()-t0
            log(f'[25%] sorted {b+1}/{num_buckets} buckets; elapsed {elapsed/60:.1f} min; remaining sorts approx {(num_buckets-b-1)*elapsed/max(1,b+1)/60:.1f} min')
    return allsorted


def account_batches(parquet_file,batch_size):
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(str(parquet_file))
    carry=None
    last_emitted=None
    for record in pf.iter_batches(batch_size=batch_size):
        df=record.to_pandas()
        if carry is not None:
            df=pd.concat([carry,df],ignore_index=True); carry=None
        if len(df)==0:continue
        ids=df['chooser'].to_numpy(dtype=str)
        if np.any(ids[1:]<ids[:-1]):raise ValueError('Sorted input is not sorted by chooser')
        last=ids[-1]
        boundary=len(ids)-int(np.sum(np.cumprod(ids[::-1]==last)))
        if boundary<=0:
            carry=df;continue
        block=df.iloc[:boundary].copy()
        carry=df.iloc[boundary:].copy()
        if last_emitted is not None and block['chooser'].iloc[0] <= last_emitted:
            raise ValueError('Chooser was split or sorted ordering violated')
        last_emitted=str(block['chooser'].iloc[-1])
        yield block
    if carry is not None and len(carry):
        if last_emitted is not None and str(carry['chooser'].iloc[0])<=last_emitted:
            raise ValueError('Trailing chooser continuity violation')
        yield carry


def pass_one_task(args):
    b,src,batch_size=args
    xx=np.zeros((85,85),np.float64);xy=np.zeros(85,np.float64)
    N=0;accounts=0;within_rows=0;grants=0
    for frame in account_batches(src,batch_size):
        x,y=construct_design(frame)
        sx,sy,g,w=chooser_crossproducts(x,y,frame['chooser'].to_numpy(dtype=str))
        xx+=sx;xy+=sy
        accounts+=g;within_rows+=w;N+=len(frame);grants+=int(frame.grant.sum())
    return b,xx,xy,N,accounts,within_rows,grants


def compute_models(xx,xy):
    # Keep the FROZEN regressors. Perfectly collinear/zero columns are handled
    # as unidentified, not silently dropped and reported as zero.
    mods={}
    for n in (1,2,3,4):
        requested,names=model_indices(n)
        S=xx[np.ix_(requested,requested)]
        Y=xy[requested]
        b,inv,rank_info,identification=solve_gram_rank_aware(S,Y)
        mods[n]={'ix':requested,'labels':list(names),'beta':b,'bread':inv,
                 'omitted':[],'min_eig':rank_info['smallest_identified_scaled_eigenvalue'],
                 'rank_info':rank_info,'identification':identification}
        log(f'[MODEL {n}] rank={rank_info["rank"]}/{rank_info["parameters"]}; '
            f'min positive standardized Gram eigenvalue={rank_info["smallest_identified_scaled_eigenvalue"]:.3g}; '
            f'unidentified dimensions={rank_info["parameters"]-rank_info["rank"]}')
        for term in names:
            if not term.startswith('stage_'):continue
            L=np.zeros(len(names));L[names.index(term)]=1
            ok,_=estimable_linear(L,identification)
            if not ok:log(f'[MODEL {n}] UNIDENTIFIED TERM: {term} (not a zero coefficient)')
    return mods


def pass_two_task(args):
    b,src,batch_size,model_payload=args
    M={}; S={}
    sum_xw={3:np.zeros((2,len(model_payload[3]['ix']))),4:np.zeros((5,len(model_payload[4]['ix'])))}
    Gcount=0;N=0
    for n in model_payload:
        p=len(model_payload[n]['ix'])
        group=0 if n in (1,2) else 2 if n==3 else 5
        q=p+(13 if n==2 else 0 if n==1 else group*10)
        M[n]=np.zeros((q,q),np.float64)
        S[n]=np.zeros(q,np.float64)
    for frame in account_batches(src,batch_size):
        x,y=construct_design(frame)
        ids=frame['chooser'].to_numpy(dtype=str)
        xw,yw,xbar,ybar,counts,starts,acc=chooser_within(x,y,ids)
        g=len(counts);Gcount+=g;N+=len(y)
        pos=frame.pos.to_numpy(dtype=np.int8)
        stage=frame.stage.to_numpy(dtype=np.int8)
        sp=frame.speed_i.to_numpy(dtype=np.int8)
        for n,m in model_payload.items():
            ix=m['ix'];labels=m['labels'];beta=m['beta']
            xm=xw[:,ix]
            err=yw-xm@beta
            U=np.add.reduceat(xm*err[:,None],starts,axis=0)
            if n==1:
                Z=U
            elif n==2:
                pos4=np.bincount(acc*4+np.maximum(0,pos-1),weights=(pos>0).astype(float),minlength=g*4).reshape(g,4)
                stage7=np.bincount(acc*7+np.maximum(0,stage-1),weights=(stage>0).astype(float),minlength=g*7).reshape(g,7)
                sy=np.add.reduceat(y,starts)
                Z=np.column_stack([U,sy,counts,pos4,stage7])
            else:
                group=(pos>=2).astype(np.int8) if n==3 else sp
                ng=2 if n==3 else 5
                fit=ybar[acc]+xm@beta
                fitted=np.bincount(acc*ng+group,weights=fit,minlength=g*ng).reshape(g,ng)
                counts_g=np.bincount(acc*ng+group,minlength=g*ng).reshape(g,ng)
                counts_gst=np.bincount(acc*(ng*8)+group*8+stage,minlength=g*ng*8).reshape(g,ng*8)
                Z=np.column_stack([U,fitted,counts_g,counts_gst])
                for j in range(ng):sum_xw[n][j]+=xm[group==j].sum(axis=0)
            if Z.shape[1]!=M[n].shape[0]:raise ValueError('Cluster accounting vector dimension error')
            M[n]+=Z.T@Z
            S[n]+=Z.sum(axis=0)
    return b,M,S,sum_xw,N,Gcount


def safe_array(a):return np.asarray(a,dtype=float)

def report_row(model,group,measure,L,beta,vcov,identification=None,**extra):
    if identification is not None:
        ok,fraction=estimable_linear(L,identification)
        if not ok:
            return {'model':model,'group':group,'estimand':measure,
                    'estimate_pp':None,'se_pp':None,'ci95_low':None,'ci95_high':None,
                    'p_value':None,'status':'NOT_ESTIMABLE',
                    'relative_nullspace_projection':fraction,**extra}
    est,se,lo,hi,p=contrast(beta,vcov,L)
    return {'model':model,'group':group,'estimand':measure,'estimate_pp':est,'se_pp':se,
            'ci95_low':lo,'ci95_high':hi,'p_value':p,'status':'ESTIMATED',**extra}

def covariance_for_model(m,meat,G):
    p=len(m['beta'])
    inv=m['bread']
    cov=(G/(G-1))*inv@meat[:p,:p]@inv
    cov=(cov+cov.T)/2
    if np.min(np.diag(cov))<-1e-9:raise ValueError('Negative coefficient variance')
    return cov


def adjusted_rate_results(mod,des,meat,G):
    """Produce model 2 positions/stage and models 3/4 group-stage rates.

    Rates standardize to the empirical composition of the named population.
    SEs use chooser-account bootstrap-equivalent IFs, including uncertainty
    in within-account intercepts, group mix, fitted coefficients, and means.
    """
    b=mod['beta'];inv=mod['bread'];labs=mod['labels'];p=len(b)
    out=[];lookup={}
    if mod['id']==2:
        total=float(des['pos_n'].sum())
        groups=[('position',j) for j in range(5)]+[('stage',j) for j in range(8)]
        for kind,j in groups:
            if kind=='position':
                ct=des['pos_n'];vv=[position_vector(k,labs) for k in range(5)]
                vec=position_vector(j,labs)
            else:
                ct=des['stage_n'];vv=[stage_vector(2,0,k,labs) for k in range(8)]
                vec=stage_vector(2,0,j,labs)
            avg=sum(float(ct[k]/total)*vv[k] for k in range(len(vv)))
            d=vec-avg
            mu=float(mod['mu_y'])
            T=float(mu+d@b)
            W=np.zeros(meat.shape[0])
            W[:p]=inv@d/total
            W[p]=1/total                     # sum y_i in percentage points
            W[p+1]=(float(vec@b)-T)/total    # account opportunity count
            start=p+2 if kind=='position' else p+2+4
            for k in range(1,len(vv)):
                W[start+k-1]=float(-vv[k]@b)/total
            var=rate_if_covariance(meat,W,G)
            se=math.sqrt(max(0,var))
            key=(kind,j)
            lookup[key]={'T':T,'se':se,'W':W,'population_n':int(total), 'status':'ESTIMATED'}
            out.append({'model':2,'dimension':kind,'group':'all','level':(POSITION if kind=='position' else STAGE)[j],
                        'adjusted_rate_pp':T,'se_pp':se,'ci95_low':T-1.96*se,
                        'ci95_high':T+1.96*se,'N':int(total),'status':'ESTIMATED'})
        return out,lookup
    nmodel=mod['id'];counts=des['region_stage_n'] if nmodel==3 else des['speed_stage_n']
    ng=len(counts)
    for group in range(ng):
        N_g=float(counts[group].sum())
        if N_g<=0:raise ValueError('Empty region/speed in sample')
        kstage=[stage_vector(nmodel,group,k,labs) for k in range(8)]
        fidx=p+group; nidx=p+ng+group; stidx=p+2*ng+group*8
        # Sum of fitted actual y by group = sum of account-level fit moments.
        # Recover it separately from the first moment of Z, provided in mod.
        fitted_sum=mod['zsum'][fidx]
        ave_stage=sum(float(counts[group,k])*kstage[k] for k in range(8))
        for stage in range(8):
            e=kstage[stage]
            # The standardized rate is a group-mean prediction plus an
            # observed-composition-centered stage contrast. Its identification
            # can survive absence of the named 0-4 reference cell.
            ok,fraction=estimable_linear(e-ave_stage/N_g,mod['identification'])
            if not ok:
                lookup[group,stage]={'T':None,'se':None,'W':None,
                    'population_n':int(N_g),'status':'NOT_ESTIMABLE'}
                out.append({'model':nmodel,'dimension':'stage',
                    'group':('noncompetitive','competitive')[group] if nmodel==3 else SPEED[group],
                    'level':STAGE[stage],'adjusted_rate_pp':None,'se_pp':None,
                    'ci95_low':None,'ci95_high':None,'N':int(N_g),
                    'status':'NOT_ESTIMABLE',
                    'relative_nullspace_projection':fraction})
                continue
            stage_effect=float(e@b)
            T=float((fitted_sum+N_g*stage_effect-float(ave_stage@b))/N_g)
            H=mod['sum_xw'][group]+N_g*e-ave_stage
            W=np.zeros(meat.shape[0])
            W[:p]=inv@H/N_g
            W[fidx]=1/N_g
            W[nidx]=(stage_effect-T)/N_g
            for k in range(8): W[stidx+k]=float(-kstage[k]@b)/N_g
            var=rate_if_covariance(meat,W,G);se=math.sqrt(max(0,var))
            lookup[group,stage]={'T':T,'se':se,'W':W,'population_n':int(N_g),'status':'ESTIMATED'}
            out.append({'model':nmodel,'dimension':'stage','group':('noncompetitive','competitive')[group] if nmodel==3 else SPEED[group],
                        'level':STAGE[stage],'adjusted_rate_pp':T,'se_pp':se,
                        'ci95_low':T-1.96*se,'ci95_high':T+1.96*se,'N':int(N_g),'status':'ESTIMATED'})
    return out,lookup




def make_latex_main(path,models,N,G,W):
    """Manuscript-ready main four-column tabular; adjusted comparisons in CSV."""
    rows=[r'\begin{table}[!htbp]',r'\centering',
          r'\caption{\textbf{Opponent position and game stage: chooser fixed effects}}',
          r'\label{tab:r10_position_stage}',r'\begin{threeparttable}',r'\small',
          r'\begin{tabular}{lrrrr}',r'\toprule',
          r' & (1) & (2) & (3) & (4) \\',r'\midrule',
          r'\multicolumn{5}{l}{\textit{Panel A. Position (reference: clearly worse)}} \\']
    varlabels=[('position_clearly_better','Clearly better'),
               ('position_better','Better'),('position_roughly_equal','Roughly equal'),
               ('position_modestly_worse','Modestly worse')]
    display=varlabels+[('','')]+[(f'stage_{z}',lab) for z,lab in (
        ('5_6','Plies 5--6'),('7_8','Plies 7--8'),('9_10','Plies 9--10'),
        ('11_20','Plies 11--20'),('21_40','Plies 21--40'),
        ('41_80','Plies 41--80'),('81plus','Plies 81+'))]
    # append section break between position and stage terms
    for i,(name,label) in enumerate(display):
        if i==4:
            rows.extend([r'\addlinespace[4pt]',r'\multicolumn{5}{l}{\textit{Panel B. Stage (reference: plies 0--4)}} \\'])
            continue
        vals=[];ses=[]
        for m in (1,2,3,4):
            mod=models[m]
            if name not in mod['labels']:
                vals.append('---');ses.append('')
                continue
            j=mod['labels'].index(name)
            L=np.zeros(len(mod['labels']));L[j]=1
            if not estimable_linear(L,mod['identification'])[0]:
                vals.append('n.e.');ses.append('')
                continue
            beta=float(mod['beta'][j]);se=float(math.sqrt(max(0,mod['vcov'][j,j])))
            vals.append(f'{beta:.3f}');ses.append(f'({se:.3f})')
        rows.append(label+' & '+' & '.join(vals)+r' \\')
        rows.append(' & '+' & '.join(ses)+r' \\')
    rows += [r'\midrule',
             r'Clock and rating controls & No & Yes & Yes & Yes \\',
             r'Stage $\times$ competitive & No & No & Yes & No \\',
             r'Stage $\times$ speed & No & No & No & Yes \\',
             f'Opportunities & {N:,} & {N:,} & {N:,} & {N:,} '+' \\\\',
             f'Chooser accounts & {G:,} & {G:,} & {G:,} & {G:,} '+' \\\\',
             r'\bottomrule',r'\end{tabular}',r'\begin{tablenotes}[flushleft]',r'\footnotesize',
             r'\item Notes: Dependent variable is 100 times the grant indicator; estimates are in percentage points, with chooser-account-clustered CR0 standard errors in parentheses, multiplied by $G/(G-1)$. All columns include chooser, game-speed, and calendar-month fixed effects. Column 2 adds logged last-clock seconds and pregame rating-environment controls, with the same controls in 3--4. In column 3 the reported baseline stage coefficients apply to noncompetitive positions (stage interactions yield the separate competitive estimates). In column 4 the reported baseline stage coefficients apply to ultrabullet (speed interactions yield the other speed estimates). Position coefficients in column 3 compare categories at plies 0--4. The R10 report supplies the interaction profiles, adjacent contrasts, Holm adjustments, and standardized adjusted rates. ``n.e.`` means the indicated linear contrast is not separately estimable in the within-chooser design; no zero coefficient is imposed.',
             r'\end{tablenotes}',r'\end{threeparttable}',r'\end{table}']
    path.write_text('\n'.join(x for x in rows if x!='')+'\n')

def generate_tables(root,models,meats,zsums,sums_xw,des,G,N,within_rows):
    out=root/'public'
    metadata=[];coefs=[];A=[];B=[];C=[];D=[];rates=[]
    profile_info={}
    for model in (1,2,3,4):
        m=models[model];m['id']=model;m['mu_y']=100*EXPECTED['grants']/N
        b=m['beta'];labs=m['labels'];p=len(b)
        vc=covariance_for_model(m,meats[model],G)
        m['vcov']=vc;m['zsum']=zsums[model]
        if model in sums_xw:m['sum_xw']=sums_xw[model]
        m['adjusted_rates']=None
        for j,name in enumerate(labs):
            L=np.zeros(p);L[j]=1
            row=report_row(model,'all',name,L,b,vc,identification=m['identification'])
            row['is_focal']=name.startswith('position_') or name.startswith('stage_')
            coefs.append(row)
        metadata.append({'model':model,'n_opportunities':N,'n_choosers':G,
            'n_opportunities_accounts_at_least_2':within_rows,
            'raw_grant_rate_pp':100*EXPECTED['grants']/N,'parameters':p,
            'min_scaled_gram_eigenvalue':m['min_eig'],
            'dropped_nuisance_terms':'none; rank-aware pseudoinverse with explicit non-estimability',
            'design_rank':m['rank_info']['rank'],
            'rank_deficiency':m['rank_info']['parameters']-m['rank_info']['rank'],
            'SE':'Chooser CR0 times G/(G-1)'})
        # Panel A: exactly 4 position contrasts + 3 adjacent, Holm family 7 per model
        vec_pos={j:position_vector(j,labs) for j in range(5)}
        pos_tests=[]
        for pos in (4,3,2,1):pos_tests.append((POSITION[pos]+' minus clearly_worse',vec_pos[pos]))
        for a,c in ((4,3),(3,2),(2,1)):
            pos_tests.append((POSITION[a]+' minus '+POSITION[c],vec_pos[a]-vec_pos[c]))
        this=[]
        for name,v in pos_tests:this.append(report_row(model,'all',name,v,b,vc,identification=m['identification']))
        # Fixed family size 7; a non-estimable member consumes a conservative p=1.
        ps=holm([v['p_value'] if v['p_value'] is not None else 1. for v in this])
        for j,z in enumerate(this):z['holm_p_7']=ps[j] if z['status']=='ESTIMATED' else None
        A.extend(this)
        # Panel B: common stage reference. For models 3/4 this is explicitly
        # the noncompetitive/ultrabullet baseline, never silently pooled.
        group_label='all' if model in (1,2) else 'noncompetitive' if model==3 else 'ultrabullet'
        stages=[stage_vector(model,0,j,labs) for j in range(8)]
        stage_tests=[]
        for j in range(1,8):stage_tests.append((f'{STAGE[j]} minus 0_4',stages[j]))
        for j in range(2,8):stage_tests.append((f'{STAGE[j]} minus {STAGE[j-1]}',stages[j]-stages[j-1]))
        this=[]
        for nm,L in stage_tests:this.append(report_row(model,group_label,nm,L,b,vc,identification=m['identification']))
        ps=holm([v['p_value'] if v['p_value'] is not None else 1. for v in this])
        for j,z in enumerate(this):z['holm_p_13']=ps[j] if z['status']=='ESTIMATED' else None
        B.extend(this)
        if model>=2:
            add,lookup=adjusted_rate_results(m,des,meats[model],G)
            rates.extend(add)
            profile_info[model]=lookup
    # Region (3) and speed (4) contrasts. Stage coefficient profiles for each.
    for model,ng,groups,dest in ((3,2,('noncompetitive','competitive'),C),
                                 (4,5,SPEED,D)):
        m=models[model];b=m['beta'];labs=m['labels'];cov=m['vcov'];lookup=profile_info[model]
        for group in range(ng):
            stages=[stage_vector(model,group,k,labs) for k in range(8)]
            for j in range(1,8):
                dest.append(report_row(model,groups[group],f'stage_{STAGE[j]} minus 0_4',stages[j],b,cov,identification=m['identification']))
            for nm,L in [('81plus minus 41_80',stages[7]-stages[6]),
                         ('41_80 minus 0_4',stages[6])]:
                dest.append(report_row(model,groups[group],nm,L,b,cov,identification=m['identification']))
            # Delta method for decline relative to *adjusted* stage-0 baseline.
            dvec=stages[6];R0=lookup[group,0]
            label='(41_80 minus 0_4) / adjusted grant rate at 0_4'
            ok,fraction=estimable_linear(dvec,m['identification'])
            if not ok or R0['status']!='ESTIMATED' or abs(R0['T'])<1e-9:
                dest.append({'model':model,'group':groups[group],'estimand':label,
                    'estimate_pp':None,'se_pp':None,'ci95_low':None,'ci95_high':None,
                    'p_value':None,'unit':'fraction of reference grant rate',
                    'status':'NOT_ESTIMABLE',
                    'relative_nullspace_projection':fraction})
                continue
            V=np.zeros(meats[model].shape[0]);V[:len(b)]=m['bread']@dvec
            D0=float(dvec@b)
            ratio=D0/R0['T'];W=V/R0['T']-D0*R0['W']/(R0['T']**2)
            se=math.sqrt(max(0,rate_if_covariance(meats[model],W,G)))
            dest.append({'model':model,'group':groups[group],'estimand':label,
                'estimate_pp':ratio,'se_pp':se,'ci95_low':ratio-1.96*se,
                'ci95_high':ratio+1.96*se,'p_value':p_value(ratio,se),
                'unit':'fraction of reference grant rate','status':'ESTIMATED'})
        if model==3:
            # The focal question: is the 81+ rebound specific to competitive positions?
            s0=[stage_vector(3,0,k,labs) for k in range(8)]
            s1=[stage_vector(3,1,k,labs) for k in range(8)]
            C.append(report_row(3,'competitive minus noncompetitive',
                 'difference in (81plus minus 41_80)',
                 (s1[7]-s1[6])-(s0[7]-s0[6]),b,cov,identification=m['identification']))
            C.append(report_row(3,'competitive minus noncompetitive',
                 'difference in (41_80 minus 0_4)',s1[6]-s0[6],b,cov,identification=m['identification']))
        if model==4:
            # Speed contrasts for 81+ rebound and 41-80 cumulative decline.
            contrasts=[('ultrabullet','bullet',0,1),('bullet','blitz',1,2),
                       ('blitz','rapid',2,3),('rapid','classical',3,4)]
            for label1,label2,i,j in contrasts:
                stages_i=[stage_vector(4,i,k,labs) for k in range(8)]
                stages_j=[stage_vector(4,j,k,labs) for k in range(8)]
                for metric,La,Lb in [('81plus_minus_41_80',stages_i[7]-stages_i[6],stages_j[7]-stages_j[6]),
                                     ('41_80_minus_0_4',stages_i[6],stages_j[6])]:
                    D.append(report_row(4,f'{label1} minus {label2}',metric,La-Lb,b,cov,identification=m['identification']))
            # Dedicated combined ultrabullet/bullet vs blitz, pre-fixed opportunity weights.
            n0=float(des['speed_stage_n'][0].sum());n1=float(des['speed_stage_n'][1].sum())
            w0=n0/(n0+n1);w1=1-w0
            v0=[stage_vector(4,0,k,labs) for k in range(8)]
            v1=[stage_vector(4,1,k,labs) for k in range(8)]
            v2=[stage_vector(4,2,k,labs) for k in range(8)]
            for metric,spec in [('81plus_minus_41_80',(7,6)),('41_80_minus_0_4',(6,0))]:
                a,c=spec
                L=w0*(v0[a]-v0[c])+w1*(v1[a]-v1[c])-(v2[a]-v2[c])
                D.append(report_row(4,'(ultrabullet+bullet) minus blitz',metric,L,b,cov,
                                    identification=m['identification'],
                                    composite_ultrabullet_weight=w0,composite_bullet_weight=w1))
    # Aggregate-level identification diagnostics for referees and replication.
    id_rows=[]
    for model,mod in models.items():
        for label in mod['labels']:
            L=np.zeros(len(mod['labels']));L[mod['labels'].index(label)]=1
            ok,f=estimable_linear(L,mod['identification'])
            if not ok:id_rows.append({'model':model,'nonestimable_term':label,
                'relative_nullspace_projection':f})
    pd.DataFrame(id_rows,columns=['model','nonestimable_term','relative_nullspace_projection']).to_csv(
        out/'R10_nonidentification_audit.csv',index=False)
    # Write outputs as CSV without private IDs
    for fn,rows in [('R10_all_coefficients.csv',coefs),('R10_panel_A_positions.csv',A),
                    ('R10_panel_B_stage.csv',B),('R10_panel_C_region_stage.csv',C),
                    ('R10_panel_D_speed_stage.csv',D),('R10_adjusted_rates.csv',rates),
                    ('R10_model_metadata.csv',metadata)]:
        pd.DataFrame(rows).to_csv(out/fn,index=False)
    make_latex_main(out/'R10_MAIN_REGRESSION_TABLE.tex',models,N,G,W)
    return {'metadata':metadata,'primary_position': [z for z in A if z['model']==2],
            'primary_stage':[z for z in B if z['model']==2],
            'rebound_regions':[z for z in C if z['estimand']=='81plus minus 41_80'],
            'rebound_speeds':[z for z in D if z['estimand']=='81plus minus 41_80']}


def package_output(root,desktop,start,input_records,source_map,summary):
    public=root/'public';public.mkdir(exist_ok=True)
    for file in public.iterdir():
        if file.suffix not in {'.csv','.json','.md','.tex'}:raise ValueError('Unexpected public output extension: '+file.name)
    manifests={p.name:sha256(p) for p in sorted(public.iterdir()) if p.is_file()}
    atomic_json(public/'PUBLIC_HASHES.json',manifests)
    atomic_json(public/'_SUCCESS.json',{'status':'R10_COMPLETE','version':VERSION,
                 'created_utc':now(),'source_map':source_map,
                 'input_manifest_sha256':sha256(root/'private'/'INPUT_FILES.json'),
                 'number_public_outputs':len(manifests),'notes':'Frozen 41,534,331 pool/nonadjacent sample; all chooser account data local only.'})
    zipname=f'R10_TWO_QUESTIONS_REPORT_{start}.zip'
    dst=desktop/zipname
    with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as zipf:
        for f in sorted(public.iterdir()):
            if f.is_file():zipf.write(f,arcname=f.name)
    digest=sha256(dst)
    (desktop/(zipname+'.sha256')).write_text(digest+'  '+zipname+'\n')
    log(f'[100%] report ZIP: {dst}; SHA-256: {digest}')
    return dst


def run(args):
    start=now()
    root=Path(args.run_root).expanduser() if args.run_root else Path(args.project_root)/'output'/'r10_two_questions_v102'/start
    root=root.resolve()
    (root/'public').mkdir(parents=True,exist_ok=True)
    (root/'private').mkdir(exist_ok=True)
    desktop=Path(args.desktop).expanduser().resolve(); desktop.mkdir(parents=True,exist_ok=True)
    # Fail closed across resume when exact inputs changed.
    if args.run_root and args.reuse_from and Path(args.run_root).expanduser().resolve()==Path(args.reuse_from).expanduser().resolve():
        raise ValueError('Output must not overwrite prior producer cache')
    inputs=files_for_input(args.input)
    source_map={}
    t0=time.monotonic()
    log(f'R10 v{VERSION}: output root {root}; {len(inputs)} input Parquet files, {args.buckets} hash buckets')
    fingerprint=[]
    for i,p in enumerate(inputs):
        fingerprint.append({'path':str(p),'size':p.stat().st_size,'sha256':sha256(p)})
        if len(inputs)>8 and (i+1)%8==0:log(f'[PRE] SHA-256 verified {i+1}/{len(inputs)} files')
    manifest={'version':VERSION,'input_files':fingerprint,'requested_buckets':args.buckets,'code_sha256':sha256(Path(__file__)),
              'source_sample':'41,534,331 pool/nonadjacent 2023-11..2025-10'}
    path=root/'private'/'INPUT_FILES.json'
    if path.exists() and json.loads(path.read_text())!=manifest:
        raise ValueError('Reused output root has different code/inputs/configuration: refusing to resume')
    atomic_json(path,manifest)
    import duckdb,pyarrow
    source_map={'duckdb':duckdb.__version__,'pyarrow':pyarrow.__version__,
                'pandas':pd.__version__,'numpy':np.__version__,
                'python':sys.version.split()[0],'compute_workers':args.compute_workers,
                'sql_workers':args.sql_workers,'memory_gb':args.memory_gb}
    c=connect(root,args.sql_workers,args.memory_gb)
    names=main_view(c,inputs);source_map['resolved_source_fields']=names
    d=preflight(c,root)
    des=descriptives(c,root)
    cols=('chooser','grant','pos','stage','speed_i','month_i','kappa',
          'rd_chooser','rd_opponent','clock_chooser','clock_opponent','gap')
    if args.reuse_from:
        # Reuse only verified 1.0.1 private caches, WITHOUT modifying old run.
        # Its original producer is checked by SHA; current inputs by SHA above.
        old=Path(args.reuse_from).expanduser().resolve()
        oldmanifest=old/'private'/'INPUT_FILES.json'
        if not oldmanifest.is_file():raise ValueError('Missing frozen prior input manifest')
        prev=json.loads(oldmanifest.read_text())
        if prev.get('version')!='1.0.1' or prev.get('input_files')!=fingerprint or prev.get('requested_buckets')!=args.buckets:
            raise ValueError('Old R10 run does not match 1.0.1 frozen inputs and bucket count')
        if prev.get('code_sha256')!=OLD_V101_PRODUCER_SHA256:
            raise ValueError('Prior producing code hash is not authenticated v1.0.1')
        checkpoint=old/'private'/'bucketed_complete.json'
        if not checkpoint.is_file():raise ValueError('Missing previous bucket-completion receipt')
        status=json.loads(checkpoint.read_text())
        if status.get('buckets')!=args.buckets or list(status.get('columns',[]))!=list(cols):
            raise ValueError('Prior bucket schema differs from requested frozen design')
        sorted_files=[old/'private'/'sorted'/f'bucket_{i:03}.parquet' for i in range(args.buckets)]
        oldpass=old/'private'/'pass1'
        from pyarrow.parquet import ParquetFile
        row_total=0
        for i,pth in enumerate(sorted_files):
            if not pth.is_file() or not (oldpass/f'{i:03d}.npz').is_file():
                raise ValueError(f'Incomplete old R10 private sorted/pass1 cache at bucket {i}')
            pqf=ParquetFile(str(pth))
            if not set(cols).issubset(pqf.schema_arrow.names):
                raise ValueError(f'Invalid cached sorted schema bucket {i}')
            row_total+=pqf.metadata.num_rows
        if row_total!=EXPECTED['opportunities']:
            raise ValueError(f'Prior sorted cache N mismatch: {row_total}')
        reuse={'old_root':str(old),'prior_manifest_sha256':sha256(oldmanifest),
            'producer_sha256':prev['code_sha256'],
            'bucket_receipt_sha256':sha256(checkpoint),
            'sorted_count':len(sorted_files),'verified_sorted_rows':row_total,
            'cache_mode':'read-only prior pass1 and sorted Parquet; new pass2 output'}
        atomic_json(root/'public'/'R10_CACHE_REUSE_PROVENANCE.json',reuse)
        log(f'[25%] Authenticated and reusing 64 sorted files and all pass1 summaries: {old}')
        pass1cache=oldpass
    else:
        sorted_files=prepare_buckets(c,root,args.buckets,cols)
        pass1cache=root/'private'/'pass1'
        pass1cache.mkdir(exist_ok=True)
    c.close()
    pending=[]
    for b,src in enumerate(sorted_files):
        if not (pass1cache/f'{b:03d}.npz').is_file():pending.append((b,str(src),args.batch_size))
    log(f'[50%] chooser-within sufficient statistics; {len(pending)} pending of {args.buckets} buckets')
    startpass=time.monotonic()
    if pending and args.reuse_from:
        raise ValueError('Prior cache is incomplete: cannot write into frozen producer output')
    if pending:
        with cf.ProcessPoolExecutor(max_workers=args.compute_workers) as pool:
            for done,result in enumerate(pool.map(pass_one_task,pending),start=1):
                b,xx,xy,n,g,w,grants=result
                atomic_npz(pass1cache/f'{b:03d}.npz',xx=xx,xy=xy,N=n,G=g,within=w,grants=grants)
                if done%max(1,len(pending)//4)==0 or done==len(pending):
                    elapsed=time.monotonic()-startpass
                    log(f'[50%] pass1 {done}/{len(pending)} new buckets; ETA next checkpoint / finish approx {(len(pending)-done)*elapsed/max(done,1)/60:.1f} min')
    xx=np.zeros((85,85));xy=np.zeros(85);G=N=W=grants=0
    for b in range(args.buckets):
        with np.load(pass1cache/f'{b:03d}.npz') as z:
            xx+=z['xx'];xy+=z['xy'];N+=int(z['N']);G+=int(z['G']);
            W+=int(z['within']);grants+=int(z['grants'])
    if (N,G,grants)!=(d['opportunities'],d['choosers'],d['grants']):
        raise ValueError(f'Pass1 count mismatch: N={N}, G={G}, grants={grants}')
    models=compute_models(xx,xy)
    # Pass2 exact account-CR0 covariance and account bootstrap-equivalent rate IFs.
    pass2cache=root/'private'/'pass2';pass2cache.mkdir(exist_ok=True)
    model_payload={n:{'ix':m['ix'],'labels':m['labels'],'beta':m['beta']} for n,m in models.items()}
    pending=[]
    for b,src in enumerate(sorted_files):
        if not (pass2cache/f'{b:03d}.npz').exists():pending.append((b,str(src),args.batch_size,model_payload))
    log(f'[75%] account-clustered covariance and adjusted-rate moments; {len(pending)} pending buckets')
    startpass=time.monotonic()
    if pending:
        with cf.ProcessPoolExecutor(max_workers=args.compute_workers) as pool:
            for done,result in enumerate(pool.map(pass_two_task,pending),start=1):
                b,M,S,sx,n,g=result
                saved={f'M{m}':M[m] for m in (1,2,3,4)}
                saved.update({f'S{m}':S[m] for m in (1,2,3,4)})
                saved.update({'sum_xw3':sx[3],'sum_xw4':sx[4],'N':n,'G':g})
                atomic_npz(pass2cache/f'{b:03d}.npz',**saved)
                if done%max(1,len(pending)//4)==0 or done==len(pending):
                    elapsed=time.monotonic()-startpass
                    log(f'[75%] pass2 {done}/{len(pending)} new buckets; ETA finish approx {(len(pending)-done)*elapsed/max(done,1)/60:.1f} min')
    meats={};zsums={};sums_xw={3:np.zeros((2,len(models[3]['beta']))),
                         4:np.zeros((5,len(models[4]['beta'])))}
    # z sums require saving per-bucket Z sums, not merely Z'Z.
    for n in models:
        p=len(models[n]['beta'])
        ng=0 if n==1 else 13 if n==2 else 20 if n==3 else 50
        meats[n]=np.zeros((p+ng,p+ng))
        zsums[n]=np.zeros(p+ng)
    N2=G2=0
    for bucket in range(args.buckets):
        with np.load(pass2cache/f'{bucket:03d}.npz') as z:
            for n in models:
                meats[n]+=z[f'M{n}']
                zsums[n]+=z[f'S{n}']
            sums_xw[3]+=z['sum_xw3'];sums_xw[4]+=z['sum_xw4']
            N2+=int(z['N']);G2+=int(z['G'])
    if (N2,G2)!=(N,G):raise ValueError('Cross-pass opportunity/account totals changed')
    summary=generate_tables(root,models,meats,zsums,sums_xw,des,G,N,W)
    atomic_json(root/'public'/'R10_SUMMARY.json',summary)
    total=time.monotonic()-t0
    (root/'public'/'README_RESULTS.md').write_text(
        '# R10 regression run\n\n'+
        f'Complete. Frozen sample: {N:,} opportunities, {G:,} chooser accounts; {W:,} opportunities from accounts with ≥2 opportunities.\n\n'+
        'Columns 1–4: chooser FE with month and five speed categories; col 2 adds last clocks and pregame rating-environment controls; col 3 stage×competitive; col 4 stage×speed.\n\n'+
        'Rank-deficient terms are NOT estimated as zero. The frozen design is solved in its identified subspace; any nonidentified linear contrast is marked NOT_ESTIMABLE with blank estimate/SE/p-value. The matrix-nullspace audit and complete 5x8 stage-speed cell counts are in the CSVs.\n\n'+
        'All outcome coefficients are in percentage points. Cluster covariance CR0 × G/(G−1). Holm families of 7 and 13 are within each column.\n\n'+
        'The column-3/4 baseline stage terms refer specifically to noncompetitive/ultrabullet, respectively; group profiles and contrasts are in Panels C/D. A classical stage contrast relative to 0-4 is not identified if there is no reference-stage support; 81+ versus 41-80 may still be identified.\n\n'+
        'Adjusted rates use opportunity-weighted predictions in the named population, standardized to its observed nonfocal composition; their SEs account for chooser-level variation in predictions, group composition and coefficients.\n\n'+
        'Position bins include integer-inclusive endpoints. A speed comparison conditional on ply is descriptive, not proof of time invested or proportion of a game completed.\n\n'+
        'All-games median plies are NOT inferable from the timeout-only opportunity panel. They require the separately validated all-rated-games corpus and are not supplied by this regression.\n\n'+
        f'Elapsed wall time: {total/60:.1f} minutes. Environment: {source_map}.\n')
    package_output(root,desktop,start,fingerprint,source_map,summary)


def main():
    parser=argparse.ArgumentParser(description='R10 four chooser-FE regressions on frozen 41.5m sample')
    parser.add_argument('--input',required=True,help='Verified cleaned monthly Parquet links from Test F')
    parser.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness')
    parser.add_argument('--desktop',default=str(Path.home()/'Desktop'/'Lichess_Desktop'))
    parser.add_argument('--run-root',help='Explicit immutable run root, for interrupted-run resume')
    parser.add_argument('--reuse-from',help='Read-only reuse of previous verified v1.0.1 failed-run sorted and pass1 caches')
    parser.add_argument('--sql-workers',type=int,default=10)
    parser.add_argument('--compute-workers',type=int,default=6)
    parser.add_argument('--memory-gb',type=int,default=11)
    parser.add_argument('--buckets',type=int,default=64)
    parser.add_argument('--batch-size',type=int,default=32768)
    a=parser.parse_args()
    if not (1<=a.sql_workers<=16 and 1<=a.compute_workers<=10 and 4<=a.memory_gb<=64 and 4<=a.buckets<=256 and 1024<=a.batch_size<=131072):
        parser.error('Out-of-range resources')
    try:run(a)
    except Exception as e:
        log('R10 FAILED CLOSED: '+repr(e))
        traceback.print_exc()
        raise SystemExit(1)

if __name__=='__main__':main()
