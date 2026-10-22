"""Five-fold account-held-out adjustment, using fold-subtracted sufficient statistics."""
from fw_common import *
from fw_design import nuisance

def moments_job(j):
    work=Path(j['out']);key=j['key']
    if completed(work,key):return str(work/'moments.npz')
    work.mkdir(parents=True,exist_ok=True);d=frame(j['path']);fold=fold_ids(d.chooser.to_numpy())
    X,names=nuisance(d);k=X.shape[1];sums={}
    for late in (0,1):
      for year in (1,2):
       for state in ('C','N'):
        base=(d.year.to_numpy()==year)&((d.board.to_numpy()>=-100)==(state=='C'))
        if late:base &= d.ply.to_numpy()>10
        for f in range(5):
            use=base&(fold==f);x=X[use];y=d.y.to_numpy(float)[use]
            sums[f'{late}_{year}_{state}_{f}_xx']=x.T@x
            sums[f'{late}_{year}_{state}_{f}_xy']=x.T@y
    np.savez(work/'moments.npz',**sums);save(work/'names.json',names);certify(work,key,[j['path']]);return str(work/'moments.npz')

def score_job(j):
    work=Path(j['out']);key=j['key']
    if completed(work,key):return str(work/'scores.parquet')
    work.mkdir(parents=True,exist_ok=True);d=frame(j['path']);fold=fold_ids(d.chooser.to_numpy());X,_=nuisance(d)
    with np.load(j['fits'],allow_pickle=False) as fits:
      blocks=[]
      for late in (0,1):
       for year in (1,2):
        for state in ('C','N'):
         use=(d.year.to_numpy()==year)&((d.board.to_numpy()>=-100)==(state=='C'))
         if late:use &= d.ply.to_numpy()>10
         pred=np.zeros(use.sum());fs=fold[use];xx=X[use]
         for f in range(5):
            label=f'{late}_{year}_{state}_{f}';hold=xx[fs==f]
            null=fits[label+'_null'];scale=fits[label+'_scale']
            if len(hold) and null.shape[1]:
                require(np.max(np.abs((hold/scale)@null),initial=0)<1e-6,'Held-out nuisance row lacks training support: '+label)
            pred[fs==f]=hold@fits[label]
         z=d.loc[use,['chooser','y','board']].copy();z['residual']=100*(z.y.to_numpy()-pred)
         for dest in ([state,'L'] if state=='N' else [state]):
            w=z.loc[z.board<=-300] if dest=='L' else z
            v=w.groupby('chooser',sort=True).agg(n=('y','size'),adjusted_sum=('residual','sum')).reset_index()
            v['year']=year;v['late']=bool(late);v['state']=dest;blocks.append(v)
    parquet(work/'scores.parquet',pd.concat(blocks,ignore_index=True));certify(work,key,[j['path'],j['fits']]);return str(work/'scores.parquet')

def adjust(parts,work,key,a):
    if completed(work,key):return work/'adjusted_accounts.parquet'
    work.mkdir(parents=True,exist_ok=True)
    jobs=[dict(path=str(p),out=str(work/'moments'/str(i)),key=digest([key,'moments',i])) for i,p in enumerate(parts)]
    moments=run_pool(moments_job,jobs,min(a.workers,max(1,int(a.memory_gb//1.2))),'F composition moments')
    sums={}
    for path in moments:
        with np.load(path) as z:
            for n in z.files:sums[n]=sums.get(n,0)+z[n]
    fits={};ranks=[]
    for late in (0,1):
     for year in (1,2):
      for state in ('C','N'):
       xx=sum(sums[f'{late}_{year}_{state}_{f}_xx'] for f in range(5));xy=sum(sums[f'{late}_{year}_{state}_{f}_xy'] for f in range(5))
       for f in range(5):
        fit=solve(xx-sums[f'{late}_{year}_{state}_{f}_xx'],xy-sums[f'{late}_{year}_{state}_{f}_xy'])
        require(fit['rank']>0,'Empty nuisance-training sample')
        label=f'{late}_{year}_{state}_{f}';fits[label]=fit['beta'];fits[label+'_null']=fit['null'];fits[label+'_scale']=fit['scale']
        ranks.append(dict(late=late,year=year,state=state,fold=f,rank=fit['rank']))
    if (work/'fits.npz').exists():
        with np.load(work/'fits.npz') as old:
            require(set(old.files)==set(fits) and all(np.array_equal(old[n],fits[n]) for n in fits),'Nuisance sufficient-statistic reconstruction differs from saved fits')
    else:np.savez(work/'fits.npz',**fits)
    table(work/'report','nuisance_ranks',ranks)
    jobs=[dict(path=str(p),out=str(work/'scores'/str(i)),key=digest([key,'scores',i]),fits=str(work/'fits.npz')) for i,p in enumerate(parts)]
    scored=run_pool(score_job,jobs,min(a.workers,max(1,int(a.memory_gb//1.2))),'F cross-fitted residuals')
    combine_scores(scored,work/'adjusted_accounts.parquet',a.memory_gb)
    certify(work,key,[*parts,work/'fits.npz']);return work/'adjusted_accounts.parquet'

def combine_scores(scored,output,memory):
    """Residual sums and exposure counts are additive across physical files."""
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    c=conn(output.parent/'spill',max(1,memory-2),2)
    try:
        tmp=output.with_suffix('.partial.parquet')
        c.execute(f'''COPY (SELECT chooser,year,late,state,sum(n)::BIGINT n,
          sum(adjusted_sum)::DOUBLE adjusted_sum,sum(adjusted_sum)/sum(n) adjusted
          FROM {parq(scored)} GROUP BY chooser,year,late,state
          ORDER BY chooser,year,late,state) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
        os.replace(tmp,output)
    finally:c.close()
    return output
