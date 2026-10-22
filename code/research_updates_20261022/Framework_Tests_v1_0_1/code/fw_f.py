"""State-specific year-to-year persistence and forward granting histories."""
from fw_common import *
from scipy.stats import rankdata

def corr(x,y,w=None):
    if len(x)<3:return np.nan
    if w is None:w=np.ones(len(x))
    n=w.sum()
    if n<=1:return np.nan
    mx=float(w@x/n);my=float(w@y/n);dx=x-mx;dy=y-my
    vx=float(w@(dx*dx));vy=float(w@(dy*dy))
    return float(w@(dx*dy)/math.sqrt(vx*vy)) if vx>1e-20 and vy>1e-20 else np.nan

def weighted_ranks(codes,counts):
    mass=np.bincount(codes,weights=counts)
    return (np.cumsum(mass)-.5*mass+.5)[codes]

def boot_matrix(q,n,reps,seed,full=True):
    # Each draw resamples complete chooser records. Weights are multinomial counts.
    pairs=[(0,2),(0,3),(1,2),(1,3)] if full else [(0,1)]
    names=['C_to_C','C_to_N','N_to_C','N_to_N'] if full else ['pair']
    rank_codes=[np.unique(q[:,i],return_inverse=True)[1] for i in range(q.shape[1])]
    h=[2*n[:,i]*n[:,j]/(n[:,i]+n[:,j]) for i,j in pairs]
    labels=[m+':'+s for m in ('pearson','harmonic','spearman') for s in names]
    if full:labels+=['pearson:within_state_difference','pearson:selectivity']
    def calculate(w):
        pear=[corr(q[:,i],q[:,j],w) for i,j in pairs]
        out=pear+[corr(q[:,i],q[:,j],w*v) for (i,j),v in zip(pairs,h)]
        ranks=[weighted_ranks(z,w) for z in rank_codes]
        out += [corr(ranks[i],ranks[j],w) for i,j in pairs]
        if full:out += [pear[0]-pear[3],corr(q[:,0]-q[:,1],q[:,2]-q[:,3],w)]
        return np.asarray(out)
    point=calculate(np.ones(len(q)));draws=np.empty((reps,len(point)));rng=np.random.default_rng(seed)
    for b in range(reps):
        w=np.bincount(rng.integers(0,len(q),size=len(q)),minlength=len(q))
        draws[b]=calculate(w)
    rows=[]
    for j,name in enumerate(labels):
        good=np.isfinite(draws[:,j]);ok=np.isfinite(point[j]) and good.sum()>=max(20,.95*reps)
        lo,hi=np.quantile(draws[good,j],[.025,.975]) if ok else (np.nan,np.nan)
        rows.append(dict(statistic=name,estimate=point[j],se=np.std(draws[good,j],ddof=1) if ok else None,
          ci_low=lo,ci_high=hi,valid_bootstraps=int(good.sum()),requested_bootstraps=reps,
          status='ESTIMATED' if ok else 'UNRESOLVED_VARIANCE_OR_BOOTSTRAP',accounts=len(q)))
    return rows

def wide_panel(accounts,adjusted,work,key,state,late,memory):
    out=work/f'wide_{state}_{int(late)}'
    if completed(out,key):return out/'wide.parquet'
    out.mkdir(parents=True,exist_ok=True);c=conn(out/'spill',max(1,memory-2),1)
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+parq([accounts]))
        if adjusted:
            c.execute('CREATE VIEW adj AS SELECT * FROM '+parq([adjusted]))
            for name in ('raw','adj'):
                duplicate=c.execute(f'SELECT count(*) FROM (SELECT chooser,year,late,state FROM {name} GROUP BY ALL HAVING count(*)<>1)').fetchone()[0]
                require(duplicate==0,'Duplicate account/state/year cells in '+name)
            mismatch=c.execute('''SELECT count(*) FROM raw r FULL JOIN adj a USING(chooser,year,late,state)
                WHERE r.n IS DISTINCT FROM a.n''').fetchone()[0]
            require(mismatch==0,'Adjusted/raw account cells differ')
            src='(SELECT r.*,a.adjusted FROM raw r JOIN adj a USING(chooser,year,late,state))'
        else:src='(SELECT *,NULL::DOUBLE adjusted FROM raw)'
        cols=[]
        for k,(s,year) in enumerate([('C',1),(state,1),('C',2),(state,2)]):
            cond=f'state={qs(s)} AND year={year}'
            cols += [f'coalesce(max(n) FILTER(WHERE {cond}),0) n{k}',f'coalesce(max(y) FILTER(WHERE {cond}),0) y{k}',
                     f'max(adjusted) FILTER(WHERE {cond}) a{k}']
        cols.append("coalesce(sum(n) FILTER(WHERE year=2 AND state IN ('C','N')),0) any_p2_n")
        c.execute(f'COPY (SELECT chooser,{",".join(cols)} FROM {src} WHERE late={str(late).lower()} GROUP BY chooser ORDER BY chooser) TO {qs(out/"wide.parquet")} (FORMAT PARQUET,COMPRESSION ZSTD)')
    finally:c.close()
    certify(out,key,[accounts]+([adjusted] if adjusted else []));return out/'wide.parquet'

def job(j):
    work=Path(j['out']);key=j['key']
    if completed(work,key):return load(work/'results.json')
    work.mkdir(parents=True,exist_ok=True);d=frame(j['source']);n=d[[f'n{k}' for k in range(4)]].to_numpy(float)
    indices=j.get('pair');ix=list(indices) if indices else [0,1,2,3]
    use=(n[:,ix]>=j['minimum']).all(axis=1)
    if j['adjusted']:q=d[[f'a{k}' for k in ix]].to_numpy(float)[use]
    else:q=100*d[[f'y{k}' for k in ix]].to_numpy(float)[use]/n[use][:,ix]
    require(np.isfinite(q).all(),'Missing score on eligible persistence cell')
    label=dict(comparison='C/'+j['state'],late=j['late'],adjusted=j['adjusted'],minimum=j['minimum'],
      sample='common' if indices is None else 'pair_specific',pair=str(indices),conditional_on_nuisance_fits=j['adjusted'])
    if len(q)<3:rows=[dict(label,status='INSUFFICIENT_ACCOUNTS',accounts=len(q))]
    else:
        rows=[dict(label,**r) for r in boot_matrix(q,n[use][:,ix],j['reps'],SEED,j.get('pair') is None)]
        for r in rows:
            if indices is not None:r['statistic']=r['statistic'].replace('pair',{(0,2):'C_to_C',(0,3):'C_to_N',(1,2):'N_to_C',(1,3):'N_to_N'}[tuple(indices)])
            r['statistic']=r['statistic'].replace('N',j['state'])
    save(work/'results.json',rows);certify(work,key,[j['source']]);return rows

def coverage_forward(path,state,late):
    d=frame(path);n=d[[f'n{k}' for k in range(4)]].to_numpy(float);y=d[[f'y{k}' for k in range(4)]].to_numpy(float)
    first=(n[:,:2]>=4).all(axis=1);common=(n>=4).all(axis=1)
    group=np.select([(y[:,0]>0)&(y[:,1]==0),(y[:,0]>0)&(y[:,1]>0),(y[:,0]==0)&(y[:,1]>0)],['C_only','BOTH',state+'_only'],default='NEITHER')
    coverage=[];forward=[]
    for g in ['ALL','C_only','BOTH',state+'_only','NEITHER']:
        z=(first if g=='ALL' else first&(group==g)).copy();den=int(z.sum())
        coverage.append(dict(comparison='C/'+state,late=late,P1_group=g,P1_eligible=den,
          any_P2=int((z&(d.any_p2_n.to_numpy()>0)).sum()),P2_C_min4=int((z&(n[:,2]>=4)).sum()),
          comparison_state=state,P2_comparison_state_min4=int((z&(n[:,3]>=4)).sum()),P2_both_min4=int((z&common).sum()),
          retention_any=float((d.any_p2_n.to_numpy()[z]>0).mean()) if den else None))
        z &= common
        for k,s in [(2,'C'),(3,state)]:
            nn=n[z,k];yy=y[z,k];G=len(nn)
            if G<2:continue
            for scheme in ['account_mean','pooled_opportunities']:
                q=100*yy/nn;rate=float(q.mean()) if scheme=='account_mean' else float(100*yy.sum()/nn.sum())
                influence=(q-rate)/G if scheme=='account_mean' else (100*yy-rate*nn)/nn.sum()
                forward.append(dict(comparison='C/'+state,late=late,P1_group=g,P2_state=s,weighting=scheme,accounts=G,
                  opportunities=int(nn.sum()),grants=int(yy.sum()),**infer(rate,G/(G-1)*float(influence@influence))))
    for k,s in enumerate(['C1',state+'1','C2',state+'2']):
        nn=n[common,k];yy=y[common,k]
        coverage.append(dict(comparison='C/'+state,late=late,sample='common_min4',state_year=s,accounts=len(nn),
          opportunities=int(nn.sum()),grants=int(yy.sum()),nonzero_accounts=int((yy>0).sum()),
          exposure_p25=float(np.quantile(nn,.25)) if len(nn) else None,exposure_median=float(np.median(nn)) if len(nn) else None,
          exposure_p75=float(np.quantile(nn,.75)) if len(nn) else None))
    return coverage,forward

def run(a,run,accounts,adjusted,key):
    work=run/'F';report=work/'report';report.mkdir(parents=True,exist_ok=True)
    mode='adjusted' if adjusted else 'raw';phasekey=digest([key,mode,a.bootstrap])
    end=work/mode
    if completed(end,phasekey):return load(end/'status.json')
    jobs=[];cover=[];forward=[]
    for state in ('N','L'):
     for late in (False,True):
      p=wide_panel(accounts,adjusted,work/'wide'/mode,digest([phasekey,state,late]),state,late,a.memory_gb)
      if not adjusted:
        c,f=coverage_forward(p,state,late);cover+=c;forward+=f
      for minimum in (4,10,20):
        ident=f'{mode}_{state}_{int(late)}_{minimum}'
        jobs.append(dict(source=str(p),out=str(work/'bootstrap'/ident),key=digest([phasekey,ident]),state=state,late=late,
                         minimum=minimum,reps=a.bootstrap,adjusted=bool(adjusted)))
      if not late:
       for i,j in [(0,2),(0,3),(1,2),(1,3)]:
        ident=f'{mode}_{state}_pair_{i}{j}'
        jobs.append(dict(source=str(p),out=str(work/'bootstrap'/ident),key=digest([phasekey,ident]),state=state,late=False,
                         minimum=4,reps=a.bootstrap,adjusted=bool(adjusted),pair=(i,j)))
    rows=[r for batch in run_pool(job,jobs,min(a.workers,max(1,int(a.memory_gb//2.5))),'F '+mode+' bootstrap') for r in batch]
    table(report,'tabF2_persistence_matrix_'+mode,[r for r in rows if r.get('statistic','').split(':')[-1]!='selectivity'])
    table(report,'tabF3_selectivity_persistence_'+mode,[r for r in rows if r.get('statistic','').endswith('selectivity')])
    table(report,'tabF5_sensitivity_'+mode,[r for r in rows if r.get('minimum')!=4 or r.get('late')])
    if not adjusted:
        table(report,'tabF1_coverage_and_retention',cover);table(report,'tabF4_forward_rates_by_P1_group',forward)
    status=dict(status='ESTIMATED',mode=mode,bootstrap_reps=a.bootstrap,primary_window='P1 2023-11 to 2024-10; P2 2024-11 to 2025-10',
      zero_variance='Not estimable; never reported as zero persistence',nuisance_intervals='Conditional on fixed nuisance fits' if adjusted else None)
    outputs=list(report.glob('*_'+mode+'.*'))+(list(report.glob('tabF1*'))+list(report.glob('tabF4*')) if not adjusted else [])
    save(end/'status.json',status);certify(end,phasekey,[accounts]+([adjusted] if adjusted else []),outputs=outputs);return status
