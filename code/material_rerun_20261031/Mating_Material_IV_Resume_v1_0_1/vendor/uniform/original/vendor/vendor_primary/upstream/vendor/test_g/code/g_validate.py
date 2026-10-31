"""Numerical and statistical gates for the 2,000-block approximation."""
from __future__ import annotations
from g_common import *
from g_design import *
from g_inputs import load_bucket
from g_outcome import predict_chunks
from g_fe import solve,quadratic,within_forms,BLOCKS

def validate_blocks(paths,g1,knots,run,replicates=300):
    target=run/'g2/BLOCK_VALIDATION.json'
    if target.exists():
        value=load(target);require(value['passed'],'Stored block validation failed','BLOCK_BOOTSTRAP_VALIDATION_FAILED');return value
    # Uniform within-group account sampling; every selected history remains whole.
    pool=[]
    for p in paths:
        d=pd.read_parquet(p,columns=['chooser','group']).drop_duplicates('chooser')
        d['priority']=[hash64(x,'block-validation-sample') for x in d.chooser]
        pool.append(d)
    accounts=pd.concat(pool).sort_values('priority').groupby('group',sort=True).head(300)
    selected=set(accounts.chooser);pieces=[]
    for p in paths:
        d=load_bucket(p);pieces.append(d.loc[d.chooser.isin(selected)].copy())
    d=pd.concat(pieces).sort_values(['chooser','event_ms','archive_ordinal','game_id']).reset_index(drop=True)
    require(d.chooser.nunique()>=100,'Too few accounts to validate the block approximation','BLOCK_VALIDATION_NO_SUPPORT')
    probability=predict_chunks(g1,d);X,names,_=g2_design(d,'MRU',probability[:,0],probability[:,0]+.5*probability[:,1],knots['knots'],knots['score_knots'])
    zt,_,train,_,layout=within_forms(d,X);start,count,index,unused=layout;G=len(start);P=X.shape[1]+1
    H=np.empty((G,2,P,P),float);groups=d.group.to_numpy()[start];ids=d.chooser.to_numpy()[start]
    for i,lo in enumerate(start):
        hi=lo+count[i];z=zt[lo:hi];t=train[lo:hi];H[i,0]=z[t].T@z[t];H[i,1]=z[~t].T@z[~t]
    nt=np.add.reduceat((~train).astype(float),start)
    indices={}
    for m in ['M0','MR','MRU']:
        _,n,_=g2_design(d.iloc[:1],m,probability[:1,0],probability[:1,0]+.5*probability[:1,1],knots['knots'],knots['score_knots'])
        indices[m]=[names.index(name) for name in n]+[P-1]
    direct_error=0.
    for m,ix in indices.items():
        hh=H[:,0].sum(axis=0)[np.ix_(ix,ix)];direct=zt[train][:,ix].T@zt[train][:,ix]
        direct_error=max(direct_error,float(np.max(np.abs(solve(hh)['beta']-solve(direct)['beta']))))
    require(direct_error<=1e-8,f'Direct versus accumulated FE fit differs by {direct_error:.3g}','BLOCK_ALGEBRA_FAILED')
    def statistics(w):
        h=np.einsum('g,gkij->kij',w,H,optimize=True);den=float(w@nt);loss={}
        for m,ix in indices.items():
            tr=h[0][np.ix_(ix,ix)];te=h[1][np.ix_(ix,ix)];b=solve(tr)['beta'];loss[m]=quadratic(te,b)/den
        gain=loss['M0']-loss['MRU'];raw=loss['MR']-loss['MRU'];return [gain,raw,raw-.1*gain]
    rng=np.random.default_rng(SEED+177);exact=[];cluster_indices=[np.flatnonzero(groups==g) for g in np.unique(groups)]
    for _ in range(replicates):
        w=np.zeros(G,int)
        for ix in cluster_indices:w[ix]=rng.multinomial(len(ix),np.full(len(ix),1/len(ix)))
        exact.append(statistics(w))
    se_ref=np.std(exact,axis=0,ddof=1);rows=[];passed=True
    for seed in [411,733,1091]:
        assignment=np.array([(int(g)+1)*400+hash64(int(u),'validation-block-'+str(seed))%400 for u,g in zip(ids,groups)],int)
        simulated=[]
        for _ in range(replicates):
            wblock=np.concatenate([rng.multinomial(400,np.full(400,1/400)) for _ in range(5)])
            simulated.append(statistics(wblock[assignment]))
        ratio=np.std(simulated,axis=0,ddof=1)/se_ref
        for name,value in zip(['gain_MRU','A_raw','D10'],ratio):
            ok=np.isfinite(value) and .8<=value<=1.25;passed &= ok
            rows.append(dict(statistic=name,block_seed=seed,se_ratio_to_exact_account_bootstrap=float(value),passed=bool(ok)))
    value=dict(passed=bool(passed),accounts=G,rows=len(d),draws_per_comparator=replicates,numerical_max_coefficient_difference=direct_error,
        acceptance_margin=[.8,1.25],comparisons=rows,scope='Fixed G1, manageable stratified account subsample, three independent block allocations; approximation check, not a proof at full scale')
    save(target,value);save(run/'report/BLOCK_VALIDATION.json',value)
    require(passed,'Block-bootstrap SE comparison failed. No final scientific classifications will be issued.','BLOCK_BOOTSTRAP_VALIDATION_FAILED')
    return value
