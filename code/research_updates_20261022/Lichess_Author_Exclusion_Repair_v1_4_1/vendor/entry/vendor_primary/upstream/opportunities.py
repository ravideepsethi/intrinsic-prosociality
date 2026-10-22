"""R12 clocks and R13(a), with exact chooser absorption and stacked influences."""
from __future__ import annotations
import concurrent.futures as cf, multiprocessing as mp, os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from local_common import *
sys.path.insert(0,str(ROOT/'vendor/r11'))
from source import pool_wave1_common as authority
import design as frozen_design
from estimate import demean,grouped

MODELS=['pooled','rating_below1600','rating_1600_1999','rating_2000plus',
        'speed_bullet','speed_blitz','speed_rapid_classical',
        'intensity_low','intensity_high','intensity_insufficient','clocks']

def project_month(job):
    p=Path(job['out']);k=key([job['key'],job['month'],job['sha']])
    if cached(p,k):
        require(cached(str(p)+'.engine.json',k),'Engine configuration checkpoint missing/corrupt')
        return str(p)
    require(sha(job['path'])==job['sha'],'Opportunity source checksum differs')
    c=db(p.parent/'spill'/job['month'],1)
    try:
        c.execute('CREATE VIEW s AS SELECT * FROM '+parq([job['path']]))
        bad=c.execute('''SELECT count(*) FROM s WHERE chooser_user_id IS NULL OR outcome_kind_draw IS NULL OR outcome_kind_draw NOT IN (0,1)
          OR NOT coalesce(isfinite(engine_eval_cp_disconnected),false)
          OR engine_eval_cp_disconnected<>floor(engine_eval_cp_disconnected)
          OR NOT coalesce(ply_count>=0 AND ply_count=floor(ply_count),false)
          OR NOT coalesce(sf100k_nodes_requested=100000 AND sf100k_fen_turn_matches_disconnected_color
             AND disconnected_color=sf100k_disconnected_color_for_perspective
             AND side_to_move_after_last=disconnected_color
             AND api_status='timeout' AND five_second_rule_passed AND api_rated AND api_variant='standard',false)
          OR NOT coalesce(lower(api_speed) IN ('ultrabullet','bullet','blitz','rapid','classical'),false)
          OR NOT coalesce(isfinite(chooser_elo),false)''').fetchone()[0]
        require(bad==0,'Opportunity field meanings or chooser ratings changed')
        query=f'''SELECT chooser_user_id::BIGINT chooser,outcome_kind_draw::TINYINT y,
          engine_eval_cp_disconnected::DOUBLE board,ply_count::INTEGER ply,
          CASE WHEN engine_eval_cp_disconnected>=300 THEN 4 WHEN engine_eval_cp_disconnected>=101 THEN 3
               WHEN engine_eval_cp_disconnected>=-100 THEN 2 WHEN engine_eval_cp_disconnected>=-299 THEN 1 ELSE 0 END::TINYINT "position",
          CASE WHEN ply_count<=4 THEN 0 WHEN ply_count<=6 THEN 1 WHEN ply_count<=8 THEN 2 WHEN ply_count<=10 THEN 3
               WHEN ply_count<=20 THEN 4 WHEN ply_count<=40 THEN 5 WHEN ply_count<=80 THEN 6 ELSE 7 END::TINYINT stage,
          chooser_elo::DOUBLE chooser_rating,(disconnected_elo-chooser_elo)::DOUBLE gap,
          chooser_clock_last_obs_s::DOUBLE clock_c,disconnected_clock_last_obs_s::DOUBLE clock_d,
          chooser_win_premium_v2::DOUBLE premium,chooser_pre_rd_v2::DOUBLE rd_c,disconnected_pre_rd_v2::DOUBLE rd_d,
          {MONTHS.index(job['month'])}::TINYINT month_code,
          CASE lower(api_speed) WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 END::TINYINT speed_code
          FROM s'''
        copy_query(c,query,p);require(pq.ParquetFile(p).metadata.num_rows==job['rows'],'Projection row count differs')
        engine_cols=['sf100k_stockfish_name','sf100k_stockfish_sha256','sf100k_nodes_requested','sf100k_threads','sf100k_hash_mb','sf100k_eval_method']
        configs=c.execute('SELECT DISTINCT '+','.join(engine_cols)+' FROM s').fetchdf().to_dict('records')
        save(str(p)+'.engine.json',configs);seal(str(p)+'.engine.json',k);seal(p,k)
        log('Projected '+job['month']);return str(p)
    finally:c.close()

def prepare(a,run,k):
    private=run/'PRIVATE/opportunity';private.mkdir(parents=True,exist_ok=True)
    sample=a.sample_root or a.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    with heartbeat('Authenticate 24 opportunity months'):
        auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=min(a.workers,4))
    jobs=[dict(path=str(r['path']),month=r['month'],sha=r['expected_sha256'],rows=r['rows'],
               out=str(private/'months'/(r['month']+'.parquet')),key=k) for r in auth['month_records']]
    with cf.ProcessPoolExecutor(max_workers=min(4,a.workers),mp_context=mp.get_context('spawn')) as pool:
        paths=list(pool.map(project_month,jobs))
    engines=[]
    for p in paths:
        for v in load(p+'.engine.json'):
            if v not in engines:engines.append(v)
    save(private/'ENGINE_CONFIGURATIONS.json',engines)
    save(run/'report/opportunity_source_checksums.json',[dict(month=r['month'],sha256=r['expected_sha256'],rows=r['rows']) for r in auth['month_records']])
    receipt=private/'PARTITIONS.json';partkey=key([k,'partition',a.shards,[j['sha'] for j in jobs]])
    if cached(receipt,partkey):
        records=load(receipt)
        for r in records:require(sha(private/r['path'])==r['sha256'],'Chooser partition checksum changed')
        return private,records
    c=db(private/'spill',a.memory_gb-2,min(a.workers,4))
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parq(paths))
        n,comp,choosers=c.execute('SELECT count(*),count(*) FILTER(WHERE board>=-100),count(DISTINCT chooser) FROM p').fetchone()
        require((n,comp,choosers)==(41534331,15207423,3224173),'Certified opportunity census differs')
        c.execute('CREATE TEMP TABLE history AS SELECT chooser,(month_code//12)::INTEGER AS "year",count(*) n,avg(y) rate FROM p WHERE board>=-100 GROUP BY ALL')
        c.execute('CREATE TEMP TABLE medians AS SELECT "year",median(rate) median_rate,count(*) accounts FROM history WHERE n>=4 GROUP BY "year"')
        medians=c.execute('SELECT * FROM medians ORDER BY "year"').fetchdf().to_dict('records')
        require(len(medians)==2,'Other-year grouping lacks one panel year')
        save(run/'report/intensity_group_definition.json',dict(year0='2023-11 through 2024-10',year1='2024-11 through 2025-10',medians=medians,
             rule='Unweighted account median among accounts with >=4 competitive opportunities in the OTHER year; equality goes to low; <4 goes to insufficient'))
        c.execute('CREATE VIEW labelled AS SELECT p.*, CASE WHEN h.n IS NULL OR h.n<4 THEN 2 WHEN h.rate>m.median_rate THEN 1 ELSE 0 END::TINYINT intensity FROM p LEFT JOIN history h ON p.chooser=h.chooser AND h."year"=1-(p.month_code//12) LEFT JOIN medians m ON m."year"=h."year"')
        c.execute('CREATE VIEW competitive AS SELECT * FROM p WHERE board>=-100')
        hist=c.execute('SELECT ply,count(*) opportunities FROM competitive GROUP BY ply ORDER BY ply').fetchdf()
        csv_out(run/'report/competitive_ply_histogram.csv',hist.to_dict('records'))
        counts=c.execute('SELECT "position",stage,count(*) opportunities,sum(y)::BIGINT grants FROM p GROUP BY ALL ORDER BY ALL').fetchdf()
        csv_out(run/'report/opportunity_bin_counts.csv',counts.to_dict('records'))
        root=private/'buckets';temp=private/'buckets.partial'
        if temp.exists():temp.rename(private/('interrupted_buckets_'+str(time.time_ns())))
        c.execute(f'COPY (SELECT *,((chooser%{a.shards}+{a.shards})%{a.shards})::INTEGER bucket FROM labelled) TO '+quote(temp)+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 122880)')
        require(not root.exists(),'Uncertified final partition folder exists; inspect before moving it aside')
        temp.rename(root)
        records=[dict(path=str(p.relative_to(private)),rows=pq.ParquetFile(p).metadata.num_rows,sha256=sha(p)) for p in sorted(root.glob('bucket=*/*.parquet'))]
        require(sum(r['rows'] for r in records)==n,'Partition conservation failed');save(receipt,records);seal(receipt,partkey)
        return private,records
    finally:c.close()

def selection(d,model):
    if model=='clocks':return np.ones(len(d),bool)
    C=d.board.to_numpy()>=-100
    if model=='pooled':return C
    if model.startswith('rating_'):
        g=np.searchsorted([1600,2000],d.chooser_rating.to_numpy(),side='right');return C&(g==MODELS[1:4].index(model))
    if model.startswith('speed_'):
        g=np.select([d.speed_code==1,d.speed_code==2,d.speed_code>=3],[0,1,2],default=-1)
        return C&(g==MODELS[4:7].index(model))
    return C&(d.intensity.to_numpy()==MODELS[7:10].index(model))

def clock_design(d):
    x,names,ix=frozen_design.design(d);indices=ix['column1'];x=x[:,indices];names=[names[j] for j in indices]
    C=d.position.to_numpy()>=2
    for role in ['clock_c','clock_d']:
        name='log1p_'+role;j=names.index(name);v=x[:,j].copy()
        x[:,j]=v*(~C);names[j]=name+':noncompetitive'
        x=np.column_stack([x,v*C]);names.append(name+':competitive')
    W=np.zeros((6,len(names)))
    terms=[]
    for i,(role,region) in enumerate([(r,g) for r in ['clock_c','clock_d'] for g in ['noncompetitive','competitive']]):
        W[i,names.index('log1p_'+role+':'+region)]=1;terms.append('log1p_'+role+':'+region)
    W[4]=W[1]-W[0];W[5]=W[3]-W[2]
    return x,names,W,terms+['clock_c_competitive_minus_noncompetitive','clock_d_competitive_minus_noncompetitive']

def build(d,model):
    if model=='clocks':return clock_design(d)
    x,names=competitive_design(d);return x,names,exchange_contrasts(names),['E_small','R_small','E_large','R_large']

def bucket_job(job):
    out=Path(job['out']);k=job['key']
    if cached(out,k):return str(out)
    d=pd.concat([pq.ParquetFile(p).read(use_threads=False).to_pandas(use_threads=False) for p in job['paths']],ignore_index=True)
    d=d.sort_values('chooser',kind='stable').reset_index(drop=True);answer={}
    all_people=np.unique(d.chooser.to_numpy());offset=0
    influence=np.zeros((len(all_people),46)) if job['phase']==2 else None
    for m in MODELS:
        sub=d.loc[selection(d,m)];X,names,W,terms=build(sub,m)
        if not len(sub):
            if job['phase']==1:
                answer[m+'_xx']=np.zeros((len(names),len(names)));answer[m+'_xy']=np.zeros(len(names));answer[m+'_counts']=np.zeros(3,np.int64)
                if m!='clocks':answer[m+'_bins']=np.zeros(8,np.int64)
            else:offset+=len(W)
            continue
        y=sub.y.to_numpy(float)*100;starts,counts=grouped(sub.chooser.to_numpy());demean(X,y,starts,counts)
        if job['phase']==1:
            answer[m+'_xx']=X.T@X;answer[m+'_xy']=X.T@y
            answer[m+'_counts']=np.array([len(sub),len(starts),counts[counts>=2].sum()],np.int64)
            if m!='clocks':answer[m+'_bins']=np.bincount(eval_code(sub.board),minlength=8)
        else:
            f=job['fits'][m];resid=y-X@f['beta'];scores=np.zeros((len(starts),X.shape[1]))
            for lo in range(0,len(starts),2048):
                hi=min(lo+2048,len(starts));left=starts[lo];right=starts[hi] if hi<len(starts) else len(y)
                scores[lo:hi]=np.add.reduceat(X[left:right]*resid[left:right,None],starts[lo:hi]-left,axis=0)
            psi=scores@f['bread']@W.T*np.sqrt(f['g']/(f['g']-1))
            person=sub.chooser.to_numpy()[starts];idx=np.searchsorted(all_people,person)
            influence[idx,offset:offset+len(W)]=psi;offset+=len(W)
    if job['phase']==2:answer['stacked_covariance']=influence.T@influence
    npz(out,**answer);seal(out,k);return str(out)

def run(a,run,k):
    private,records=prepare(a,run,k);buckets={}
    for r in records:
        b=int(Path(r['path']).parts[1].split('=')[1]);buckets.setdefault(b,[]).append(str(private/r['path']))
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in paths) for paths in buckets.values())
    worker_gb=0.35+largest*8*420/2**30
    workers=max(1,min(a.workers,int((a.memory_gb-1)/worker_gb)))
    require(worker_gb<a.memory_gb-1,'Largest chooser partition exceeds memory budget; raise --shards')
    log(f'Opportunity fits: {workers} workers, {a.shards} shards, estimated {worker_gb:.2f} GiB/worker')
    fits={};first=[]
    for phase in [1,2]:
        jobs=[dict(paths=paths,out=str(private/f'pass{phase}'/f'{b:04d}.npz'),key=key([k,phase,b,[r['sha256'] for r in records if str(Path(r['path']).parts[1])==f'bucket={b}']]),phase=phase,fits=fits) for b,paths in sorted(buckets.items())]
        with heartbeat(f'Opportunity pass {phase}'),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
            paths=list(pool.map(bucket_job,jobs))
        sums={}
        for p in paths:
            with np.load(p,allow_pickle=False) as z:
                for name in z.files:sums[name]=sums.get(name,0)+z[name]
        if phase==1:
            sample=pd.read_parquet(buckets[min(buckets)][0]).iloc[:1].copy();sample['board']=0.
            for model in MODELS:
                _,names,W,terms=build(sample,model);f=solve(sums[model+'_xx'],sums[model+'_xy'])
                f.update(n=int(sums[model+'_counts'][0]),g=int(sums[model+'_counts'][1]),within_n=int(sums[model+'_counts'][2]),names=names,W=W,terms=terms)
                f['estimable']=estimable(W,f);fits[model]=f
                if model!='clocks':
                    for label,n in zip(EVALS,sums[model+'_bins']):first.append(dict(model=model,evaluation_bin=label,opportunities=int(n)))
            require(fits['pooled']['n']==15207423 and fits['clocks']['n']==41534331,'Fit census changed')
            for lo in [1,4,7]:require(sum(fits[m]['n'] for m in MODELS[lo:lo+3])==15207423,'Subgroups fail to partition competitive sample')
            csv_out(run/'report/exchange_rate_bin_counts.csv',first)
    V=sums['stacked_covariance'];rows=[];offsets={};offset=0;theta=[]
    for m in MODELS:
        f=fits[m];w=f['W'];est=w@f['beta'];theta.extend(est);offsets[m]=offset
        if m=='clocks':
            clockrows=[]
            for j,name in enumerate(f['terms']):
                out=inference(est[j],V[offset+j,offset+j]) if f['estimable'][j] else dict(estimate=None,se=None,p=None,ci_low=None,ci_high=None,status='NOT_IDENTIFIED')
                clockrows.append(dict(term=name,**out,opportunities=f['n'],choosers=f['g'],covariance='chooser G/(G-1)',units='percentage points per log(1+second)'))
            csv_out(run/'report/clocks_by_region.csv',clockrows)
        else:
            for step,j in [('small',0),('large',2)]:
                idx=[offset+j,offset+j+1]
                out=ratio_stats(est[j],est[j+1],V[np.ix_(idx,idx)]) if f['estimable'][j:j+2].all() else dict(E=None,R=None,ratio=None,se=None,status='NOT_IDENTIFIED')
                rows.append(dict(row_type='estimate',group=m,step=step,opportunities=f['n'],choosers=f['g'],opportunities_in_repeated_choosers=f['within_n'],**out))
        offset+=len(w)
    theta=np.array(theta);tests=[]
    for split,models in [('rating',MODELS[1:4]),('speed',MODELS[4:7]),('intensity',MODELS[7:10])]:
        for step,j in [('small',0),('large',2)]:
            grad=np.zeros((3,len(theta)));ratios=[];identified=True
            for i,m in enumerate(models):
                at=offsets[m]+j;E,R=theta[at:at+2]
                if not fits[m]['estimable'][j:j+2].all() or abs(E)<1e-14:identified=False;break
                grad[i,at:at+2]=[-R/E**2,1/E];ratios.append(R/E)
            if identified:
                H=np.array([[-1,1,0],[-1,0,1]]);out=wald(H@ratios,H@grad@V@grad.T@H.T)
            else:out=dict(wald_chi2=None,df=2,p=None,status='NOT_IDENTIFIED')
            tests.append(dict(row_type='equality_test',group=split,step=step,**out,covariance='stacked chooser scores; same chooser covariance retained'))
    csv_out(run/'report/exchange_rate_part_a.csv',rows+tests)
    npz(private/'exchange_rate_joint.npz',theta=theta,covariance=V,models=np.array(MODELS),offsets=np.array([offsets[m] for m in MODELS]))
    save(private/'POOLED.json',[r for r in rows if r['group']=='pooled'])
    save(run/'report/opportunity_fit_metadata.json',{m:dict(n=f['n'],choosers=f['g'],rank=f['rank'],coefficient_names=f['names'],contrast_estimable=f['estimable']) for m,f in fits.items()})
    log('R12 clocks and R13(a) completed')
