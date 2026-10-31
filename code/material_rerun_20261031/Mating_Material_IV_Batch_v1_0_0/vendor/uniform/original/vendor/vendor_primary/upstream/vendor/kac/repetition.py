"""Whole-chooser partitions; two-pass fixed effects and clustered covariance."""
from util import *
from scipy.stats import norm,chi2
import concurrent.futures as cf

def specs():
    out=[]
    for population in ('competitive','binary'):
        for label,gap,late,extra in [('primary',30,True,False),('all_stages',30,False,False),
            ('gap15',15,True,False),('gap60',60,True,False),('rating_clocks',30,True,True)]:
            out.append(dict(name=population+'_'+label,population=population,gap=gap,late=late,extra=extra))
    return out

def design(d,s):
    gap=s['gap'];competitive=d.board.to_numpy()>=-100
    use=(d.tie_n.to_numpy()==1)&~d['cens'+str(gap)].to_numpy(bool)
    use &= competitive if s['population']=='competitive' else competitive|(d.board.to_numpy()<=-300)
    if s['late']:use &= d.ply.to_numpy()>10
    a=d.loc[use].reset_index(drop=True);comp=(a.board.to_numpy()>=-100).astype(float)
    pos=a['pos'+str(gap)].to_numpy();bins=np.select([pos<=1,pos<=3,pos<=7,pos<=15],[0,1,2,3],default=4)
    names=['session_2_3','session_4_7','session_8_15','session_16plus','log1p_prior_same_speed']
    focal=np.column_stack([(bins==j).astype(float) for j in range(1,5)]+[np.log1p(a.prior_same_speed.to_numpy(float))])
    if s['population']=='binary':
        focal=np.column_stack([focal,comp,focal*comp[:,None]])
        names=names+['competitive']+[n+':competitive' for n in names]
    p=len(names);cols=[focal]
    def add(n,x):names.append(n);cols.append(np.asarray(x,float)[:,None])
    for j in range(1,24):add('month'+str(j),a.month_code.to_numpy()==j)
    for j in range(1,5):add('speed'+str(j),a.speed_code.to_numpy()==j)
    for j in (range(7,10) if s['late'] else range(1,10)):add('stage'+str(j),a.stage.to_numpy()==j)
    cp=a.board.to_numpy(float)
    b=np.select([cp< -50,cp<0,cp<50,cp<=100,cp<=200,cp<300,cp<600],list(range(7)),default=7)
    for j in range(1,8):add('competitive_eval_bin'+str(j),(b==j)&(comp==1))
    add('positive_mate',a.mate.to_numpy(bool)&(cp>0))
    if s['population']=='binary':
        add('negative_mate',a.mate.to_numpy(bool)&(cp<0));add('finite_losing_below600',~a.mate.to_numpy(bool)&(cp< -600))
    if s['extra']:
        for n in ('clock_c','clock_d','premium','rd_c','rd_d'):
            v=a[n].to_numpy(float);good=np.isfinite(v)&(v>=0);z=np.log1p(np.where(good,v,0))
            add('log_'+n,z);add('missing_'+n,~good)
        v=np.clip(a.gap.to_numpy(float),-600,600)/100
        add('rating_gap',v);add('rating_gap_sq',v*v)
    return a,np.column_stack(cols),names,p

def within(a,X):
    y=a.y.to_numpy(float)*100;c=a.chooser.to_numpy()
    if not len(a):return X,y,np.array([],int)
    starts=np.r_[0,np.flatnonzero(np.diff(c))+1];n=np.diff(np.r_[starts,len(a)])
    X=X-np.repeat(np.add.reduceat(X,starts,axis=0)/n[:,None],n,axis=0)
    y=y-np.repeat(np.add.reduceat(y,starts)/n,n)
    return X,y,starts

def solve(xx,xy):
    scale=np.sqrt(np.maximum(np.diag(xx),0));scale=np.where(scale>1e-12,scale,1.)
    z=xx/scale[:,None]/scale[None,:];v,V=np.linalg.eigh((z+z.T)/2)
    good=v>max(1e-10,float(v.max(initial=0))*1e-10)
    bread=((V[:,good]/v[good])@V[:,good].T)/scale[:,None]/scale[None,:]
    return dict(beta=bread@xy,bread=bread,scale=scale,null=V[:,~good],rank=int(good.sum()))

def worker(task):
    files,out,key,phase,models,fits=task;out=Path(out)
    if cached(out,key):return out/'moments.npz'
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    d=pd.concat([pq.ParquetFile(p).read(use_threads=False).to_pandas(use_threads=False) for p in files],ignore_index=True)
    d=d.sort_values('chooser',kind='stable').reset_index(drop=True);data={}
    for i,s in enumerate(models):
        a,X,names,p=design(d,s);W,y,starts=within(a,X);del X
        if phase==1:
            for name,val in dict(xx=W.T@W,xy=W.T@y,n=len(a),g=len(starts),grants=int(a.y.sum())).items():data[f'{i}_{name}']=val
        else:
            fit=fits[i];err=y-W@fit['beta']
            score=np.add.reduceat(W*err[:,None],starts,axis=0) if len(starts) else np.zeros((0,W.shape[1]))
            data[f'{i}_meat']=score.T@score
    out.mkdir(parents=True,exist_ok=True)
    with (out/'moments.npz').open('wb') as f:np.savez_compressed(f,**data)
    commit(out,key);return out/'moments.npz'

def reduce(paths):
    total={}
    for p in paths:
        with np.load(p,allow_pickle=False) as z:
            for k in z.files:total[k]=total.get(k,0)+z[k]
    return total

def contrast(fit,cov,names,values,label,s,n,g):
    v=np.zeros(len(names))
    for name,x in values.items():v[names.index(name)]=x
    qv=v/fit['scale'];identified=np.linalg.norm(qv@fit['null'])<=1e-7*max(np.linalg.norm(qv),1e-12)
    row=dict(specification=s['name'],contrast=label,rows=n,chooser_clusters=g,estimable=bool(identified),units='percentage points')
    if identified:
        b=float(v@fit['beta']);se=float(np.sqrt(max(0,v@cov@v)))
        row.update(estimate=b,se=se,ci_low=b-1.96*se,ci_high=b+1.96*se,p=float(2*norm.sf(abs(b/se))) if se>0 else None)
    return row

def run(files,run,key,budget,memory):
    target=Path(run)/'PRIVATE/repetition';report=Path(run)/'report/repetition'
    models=specs();conf=digest([key,models]);parts=target/'partitions'
    if not cached(parts,conf):
        threads,_=slots(budget,min(4,budget));c=db(parts/'spill',memory,threads)
        tmp=parts/'rows.partial'
        if tmp.exists():shutil.rmtree(tmp)
        try:c.execute('COPY (SELECT *,chooser%256 AS bucket FROM '+scan(files)+') TO '+q(tmp)+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 131072)')
        finally:c.close();shutil.rmtree(parts/'spill',ignore_errors=True)
        final=parts/'rows'
        if final.exists():shutil.rmtree(final)
        tmp.rename(final);commit(parts,conf)
    buckets=[list(d.glob('*.parquet')) for d in sorted((parts/'rows').glob('bucket=*'))]
    fits=[];paths=None
    for phase in (1,2):
        cap=max(1,min(budget,int(memory/1.5)))
        workers,_=slots(budget,cap)
        tasks=[(b,str(target/f'phase{phase}'/f'{i:03d}'),digest([conf,phase,i]),phase,models,fits) for i,b in enumerate(buckets)]
        from history import parallel_jobs
        paths=parallel_jobs(worker,tasks,workers,'Repetition regression pass '+str(phase))
        totals=reduce(paths)
        if phase==1:
            first=totals
            for i in range(len(models)):
                require(int(first[f'{i}_n'])>0,'Empty repetition model')
                fits.append(solve(first[f'{i}_xx'],first[f'{i}_xy']))
    sample=pq.ParquetFile(files[0]).read().slice(0,100).to_pandas()
    results=[];joint=[]
    for i,s in enumerate(models):
        _,_,names,p=design(sample,s);fit=fits[i];g=int(first[f'{i}_g']);n=int(first[f'{i}_n'])
        require(g>1,'Not enough chooser clusters')
        cov=g/(g-1)*fit['bread']@totals[f'{i}_meat']@fit['bread']
        for term in ['session_2_3','session_4_7','session_8_15','session_16plus','log1p_prior_same_speed']:
            if s['population']=='competitive':
                results.append(contrast(fit,cov,names,{term:1},term,s,n,g))
            else:
                results.append(contrast(fit,cov,names,{term:1},term+'_losing',s,n,g))
                results.append(contrast(fit,cov,names,{term:1,term+':competitive':1},term+'_competitive',s,n,g))
                results.append(contrast(fit,cov,names,{term+':competitive':1},term+'_gradient_change',s,n,g))
        if s['name'].endswith('_primary'):
            terms=['session_2_3','session_4_7','session_8_15','session_16plus']
            if s['population']=='binary':terms=[t+':competitive' for t in terms]
            idx=[names.index(t) for t in terms];V=cov[np.ix_(idx,idx)];df=np.linalg.matrix_rank(V)
            est=[contrast(fit,cov,names,{t:1},t,s,n,g)['estimable'] for t in terms]
            identified=all(est) and df==4
            stat=float(fit['beta'][idx]@np.linalg.pinv(V)@fit['beta'][idx]) if identified else None
            joint.append(dict(specification=s['name'],test='session_terms_joint',df=df,statistic=stat,p=float(chi2.sf(stat,df)) if identified else None,estimable=identified))
        js(report/(s['name']+'_model.json'),dict(specification=s,n=n,g=g,names=names,rank=fit['rank'],beta=fit['beta'],covariance=cov,
            grant_count=int(first[f'{i}_grants']),cluster_correction='G/(G-1)',chooser_fixed_effects=True,never_granters_retained=True))
    # Four primary tests fixed before new outcomes: two session joint tests and two history slopes.
    family=joint+[r for r in results if r['specification'] in ('competitive_primary','binary_primary') and
        r['contrast'] in ('log1p_prior_same_speed','log1p_prior_same_speed_gradient_change')]
    valid=[r for r in family if r.get('p') is not None];ordered=sorted(valid,key=lambda r:r['p']);last=0.
    for i,r in enumerate(ordered):last=max(last,min(1,r['p']*(len(family)-i)));r['p_holm_primary_four']=last
    tab(report/'coefficients',results);tab(report/'joint_tests',joint);js(report/'primary_family.json',family)
    threads,_=slots(budget,min(4,budget));c=db(target/'spill_summary',memory,threads)
    try:
        c.execute('CREATE VIEW f AS SELECT * FROM '+scan(files))
        c.execute('CREATE TEMP TABLE rates AS SELECT chooser,100.*avg(y) grant_rate,count(*) n FROM f WHERE board>=-100 GROUP BY chooser')
        composition=c.execute('''SELECT CASE WHEN grant_rate=0 THEN '0' WHEN grant_rate<=1 THEN '(0,1]' WHEN grant_rate<=5 THEN '(1,5]'
            WHEN grant_rate<=20 THEN '(5,20]' ELSE '>20' END account_grant_percent,
            CASE WHEN pos30<=1 THEN '1' WHEN pos30<=3 THEN '2-3' WHEN pos30<=7 THEN '4-7' WHEN pos30<=15 THEN '8-15' ELSE '16+' END session_position,
            count(*) opportunities,count(DISTINCT chooser) accounts,100.*avg(y) grant_percent
            FROM f JOIN rates USING(chooser) WHERE board>=-100 AND NOT cens30 AND tie_n=1 GROUP BY ALL ORDER BY ALL''').fetchdf()
        tab(report/'session_position_composition',composition)
        sessions=[Path(run)/'PRIVATE/history'/m/'sessions30.parquet' for m in ['2023-10']+MONTHS]
        c.execute('''CREATE TEMP TABLE session_lengths AS SELECT chooser,start30,
            max(observed_session_length) length,bool_or(left_censored) left_censored,max(last_t) last_t
            FROM '''+scan(sessions)+' GROUP BY chooser,start30')
        # No subsequent starts after panel end are read, so sessions in its last
        # hour are flagged and omitted from the completed-length description.
        cutoff=int(pd.Timestamp('2025-11-01',tz='UTC').timestamp()*1000)-HOUR
        lengths=c.execute(f'''SELECT CASE WHEN grant_rate=0 THEN '0' WHEN grant_rate<=1 THEN '(0,1]' WHEN grant_rate<=5 THEN '(1,5]'
            WHEN grant_rate<=20 THEN '(5,20]' ELSE '>20' END account_grant_percent,
            count(*) sessions,count(DISTINCT chooser) accounts,avg(length) mean_length,
            median(length) median_length,quantile_cont(length,.9) p90_length,avg((length>=16)::INTEGER) share_16plus
            FROM session_lengths JOIN rates USING(chooser) WHERE NOT left_censored AND last_t<{cutoff}
            AND start30>={int(pd.Timestamp('2023-11-01',tz='UTC').timestamp()*1000)} GROUP BY ALL ORDER BY ALL''').fetchdf()
        tab(report/'session_length_by_account_grant_rate',lengths)
        exclusions=c.execute('SELECT count(*) AS n_rows,count(*) FILTER(WHERE tie_n>1) tied_starts,count(*) FILTER(WHERE cens30) left_censored_session FROM f').fetchdf()
        tab(report/'exclusions',exclusions)
    finally:c.close();shutil.rmtree(target/'spill_summary',ignore_errors=True)
    textfile(report/'INTERPRETATION.md','Within-account associations. History counts are prior observed rated starts in the same speed, not verified lifetime play. Sessions use start-to-start gaps of 30 minutes, with 15/60-minute sensitivities. Current start ties and left-censored sessions are excluded. Session-length composition is descriptive; reaching later positions is selected. Month fixed effects do not remove account-specific drift. Models and all sensitivities are retained regardless of signs.\n')
    return dict(status='ESTIMATED',specifications=len(models),report=str(report))
