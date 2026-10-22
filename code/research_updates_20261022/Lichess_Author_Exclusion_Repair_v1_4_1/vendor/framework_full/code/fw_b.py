"""Holdout history groups, chooser FE, joint slopes and proportional contrasts."""
from fw_common import *
from fw_design import *

def sample(d,spec):
    # History classification uses all stages in P1, even for late-position outcomes.
    use=np.ones(len(d),bool) if spec.get('full') else d.year.to_numpy()==1
    nc=d.loc[use&(d.board>=-100)].groupby('chooser').y.agg(['size','sum']).rename(columns={'size':'nc','sum':'yc'})
    nl=d.loc[use&(d.board<=-300)].groupby('chooser').y.agg(['size','sum']).rename(columns={'size':'nl','sum':'yl'})
    hist=nc.join(nl,how='outer').fillna(0);hist['group_code']=groups_from_counts(hist.nc.to_numpy(),hist.nl.to_numpy(),hist.yc.to_numpy(),hist.yl.to_numpy())
    out=d.merge(hist[['group_code']],left_on='chooser',right_index=True,how='left')
    keep=(out.board>=-100)&(out.ply>10)&(out.group_code>=0)
    if spec.get('provisional'):keep=(out.board>=-100)&(out.ply>10)&np.isfinite(out.rd_c)
    if not spec.get('full'):keep &= out.year==2
    if spec.get('equal'):keep &= out.board<100
    if spec.get('exclude_flags'):
        flagged=set(load(spec['flagged_file']));keep &= ~out.chooser_name.isin(flagged)
    keep &= np.isfinite(out.rG)&np.isfinite(out.gap)&np.isfinite(out.premium)&(out.premium>0)
    out=out.loc[keep].sort_values('chooser',kind='stable').reset_index(drop=True)
    if spec.get('provisional'):out['group_code']=(out.rd_c>110).astype(int)
    return out,hist.reset_index()

def stage1(j):
    work=Path(j['out']);key=j['key']
    if completed(work,key):return str(work/'stats.npz')
    work.mkdir(parents=True,exist_ok=True);original=frame(j['path']);d,hist=sample(original,j['spec'])
    X,names,group=b_design(d,j['spec']);y=100*d.y.to_numpy(float);ng=2 if j['spec'].get('provisional') else 4;k=X.shape[1]
    if len(d):
        W=demean(X,d.chooser.to_numpy());v=demean(y,d.chooser.to_numpy());s,n=starts_counts(d.chooser.to_numpy())
    else:W=np.zeros((0,k));v=np.zeros(0);s=np.zeros(0,int);n=np.zeros(0,int)
    counts=np.bincount(group,minlength=ng);ys=np.bincount(group,weights=y,minlength=ng)
    group_accounts=np.array([d.loc[group==g,'chooser'].nunique() for g in range(ng)])
    np.savez(work/'stats.npz',xx=W.T@W,xy=W.T@v,counts=counts,ys=ys,group_accounts=group_accounts,g=len(s),n=len(d),
      varying_y=int(np.sum((np.add.reduceat(y,s)>0)&(np.add.reduceat(y,s)<100*n))) if len(d) else 0)
    save(work/'names.json',names);certify(work,key,[j['path']]+([j['spec']['flagged_file']] if j['spec'].get('exclude_flags') else []));return str(work/'stats.npz')

def stage2(j):
    work=Path(j['out']);key=j['key']
    if completed(work,key):return str(work/'meat.npy')
    work.mkdir(parents=True,exist_ok=True);d,_=sample(frame(j['path']),j['spec']);fit=j['fit']
    X,names,group=b_design(d,j['spec']);y=100*d.y.to_numpy(float);k=X.shape[1];ng=len(fit['counts'])
    M=np.zeros((k+ng,k+ng))
    if len(d):
        ids=d.chooser.to_numpy();s,n=starts_counts(ids);W=demean(X,ids);v=demean(y,ids);e=v-W@fit['beta']
        score=np.add.reduceat(W*e[:,None],s,axis=0)@fit['inverse']
        means=np.column_stack([np.add.reduceat((y-fit['means'][g])*(group==g),s)/max(fit['counts'][g],1) for g in range(ng)])
        allv=np.column_stack([score,means]);M=allv.T@allv
    np.save(work/'meat.npy',M);certify(work,key,[j['path']]+([j['spec']['flagged_file']] if j['spec'].get('exclude_flags') else []));return str(work/'meat.npy')

def fit_model(parts,work,key,spec,a):
    if completed(work/'final',key):return load(work/'final/results.json'),load(work/'final/fit.json')
    jobs=[dict(path=str(p),out=str(work/'first'/str(i)),key=digest([key,1,i]),spec=spec) for i,p in enumerate(parts)]
    paths=run_pool(stage1,jobs,min(a.workers,max(1,int(a.memory_gb//1.2))),'B '+spec['name']+' moments')
    sums={}
    for p in paths:
        with np.load(p) as f:
            for n in f.files:sums[n]=sums.get(n,0)+f[n]
    names=load(Path(paths[0]).parent/'names.json');require(sums['n']>0 and sums['g']>1,'No eligible accounts for '+spec['name'])
    fit=solve(sums['xx'],sums['xy']);fit.update(counts=sums['counts'],means=np.divide(sums['ys'],sums['counts'],out=np.zeros_like(sums['ys']),where=sums['counts']>0),g=int(sums['g']),n=int(sums['n']))
    jobs=[dict(path=str(p),out=str(work/'second'/str(i)),key=digest([key,2,i]),spec=spec,fit=fit) for i,p in enumerate(parts)]
    paths=run_pool(stage2,jobs,min(a.workers,max(1,int(a.memory_gb//1.2))),'B '+spec['name']+' clustered covariance')
    V=sum(np.load(p) for p in paths)*fit['g']/(fit['g']-1)
    k=len(names);ng=len(fit['counts']);values=np.r_[fit['beta'],fit['means']];rows=[];functionals={}
    def add(label,g,q,denom=False):
        Q=np.zeros(k+ng);Q[:k]=q
        if not estimable(fit,q) or fit['counts'][g]==0:
            rows.append(dict(model=spec['name'],group=g,term=label,status='NOT_ESTIMABLE'));return
        value=float(Q@values)
        if denom:
            m=fit['means'][g]
            if m<=0:rows.append(dict(model=spec['name'],group=g,term=label,status='ZERO_MEAN_RATE'));return
            Q/=m;Q[k+g]=-value/m**2;value/=m
        functionals[g,label]=(value,Q)
        rows.append(dict(model=spec['name'],group=g,term=label,accounts=fit['g'],opportunities=fit['n'],group_accounts=int(sums['group_accounts'][g]),group_opportunities=int(fit['counts'][g]),**infer(value,Q@V@Q)))
    for g in range(ng):
        q=np.array([float(n==f'g{g}:slope') for n in names]);add('beta',g,q);add('beta_over_mean',g,q,True)
        m=fit['means'][g];Q=np.zeros(k+ng);Q[k+g]=1
        rows.append(dict(model=spec['name'],group=g,term='mean_pp',group_opportunities=int(fit['counts'][g]),**(infer(m,Q@V@Q) if fit['counts'][g] else dict(status='NOT_ESTIMABLE'))))
        if not spec.get('equal') and not spec.get('profile'):
            for high,low in [(500,300),(300,100),(100,0)]:
                dummy=pd.DataFrame(dict(cp=[high,low],board=[high,low],mate=[False,False]));contrast=np.diff(eval_basis(dummy),axis=0)[0]*-1
                q=np.array([contrast[int(n.split('eval')[-1])] if n.startswith(f'g{g}:eval') else 0 for n in names])
                label=f'D_{high}_{low}';add(label,g,q);add(label+'_over_mean',g,q,True)
        stage=f'g{g}:stage4' if spec.get('stage_interactions') else 'stage_4'
        q=np.array([float(n==stage) for n in names]);add('stage41_80_vs11_20',g,q)
    ratios={}
    if ng in (2,4):
        for label in ('beta_over_mean','D_500_300_over_mean'):
            if (1,label) not in functionals or (0,label) not in functionals:continue
            b,q=functionals[1,label];c,r=functionals[0,label]
            contrast_label='provisional_minus_nonprovisional' if spec.get('provisional') else 'BOTH_minus_CO'
            ratio_label='provisional_over_nonprovisional' if spec.get('provisional') else 'BOTH_over_CO'
            rows.append(dict(model=spec['name'],group=contrast_label,term=label,**infer(b-c,(q-r)@V@(q-r))))
            if abs(c)>1e-12:
                deriv=q/c-b*r/c**2;ratio=b/c
                est=infer(ratio,deriv@V@deriv);den=infer(c,r@V@r)
                est['denominator_CI_includes_zero']=den['ci_low']<=0<=den['ci_high'] if den.get('ci_low') is not None else None
                rows.append(dict(model=spec['name'],group=ratio_label,term=label,**est));ratios[label]=est
    info=dict(model=spec['name'],n=fit['n'],accounts=fit['g'],varying_outcome_accounts=int(sums['varying_y']),rank=fit['rank'],columns=k,ratios=ratios,
      means_definition='Fitted group mean standardized to its own observed composition equals the raw mean under chooser FE; rate uncertainty is jointly clustered.',
      covariance='chooser CR1 G/(G-1)',stage_note='Common stage coefficient in main model; group-specific stage contrasts supplied in stage-interaction sensitivity.')
    save(work/'final/results.json',rows);save(work/'final/fit.json',info);np.savez(work/'final/model.npz',beta=fit['beta'],covariance=V,names=np.array(names),means=fit['means'],scale=fit['scale'],null=fit['null'])
    certify(work/'final',key,list(parts)+([spec['flagged_file']] if spec.get('exclude_flags') else []));return rows,info

def account_groups(accounts,work):
    d=frame(accounts);allnext=d.loc[~d.late&(d.year==2)&d.state.isin(['C','N'])].groupby('chooser').n.sum()
    d=d.loc[~d.late&d.state.isin(['C','L'])]
    n=d.pivot(index='chooser',columns=['state','year'],values='n').fillna(0);y=d.pivot(index='chooser',columns=['state','year'],values='y').fillna(0)
    out=pd.DataFrame({'chooser':n.index})
    for state in ['C','L']:
      for year in [1,2]:
        out[f'n_{state}{year}']=n.get((state,year),pd.Series(0,index=n.index)).to_numpy()
        out[f'y_{state}{year}']=y.get((state,year),pd.Series(0,index=y.index)).to_numpy()
    out['group_code']=groups_from_counts(out.n_C1.to_numpy(),out.n_L1.to_numpy(),out.y_C1.to_numpy(),out.y_L1.to_numpy())
    out['n_any_P2']=allnext.reindex(out.chooser,fill_value=0).to_numpy()
    parquet(work/'accounts_B_groups.parquet',out);rows=[]
    for g,name in enumerate(GROUPS):
        z=out.loc[out.group_code==g];rows.append(dict(group=name,accounts=len(z),P1_competitive_opportunities=int(z.n_C1.sum()),P1_lost_opportunities=int(z.n_L1.sum()),
            retained_P2_any=int((z.n_any_P2>0).sum()),P2_competitive_opportunities=int(z.n_C2.sum()),P2_competitive_grants=int(z.y_C2.sum())))
    table(work/'report','tabB1_group_sizes',rows)

def run(a,run,parts,accounts,key):
    work=run/'B';report=work/'report';report.mkdir(parents=True,exist_ok=True);account_groups(accounts,work)
    specs=[dict(name='primary',reg='rG'),dict(name='displayed_gap',reg='gap'),dict(name='normalized_payoff',reg='normalized'),
        dict(name='roughly_equal',reg='rG',equal=True),dict(name='full_panel_classification_secondary',reg='rG',full=True),
        dict(name='stage_interactions',reg='rG',stage_interactions=True)]
    flags=run/'A/flagged_chooser_names_PRIVATE.json'
    if flags.exists():specs.append(dict(name='exclude_flagged',reg='rG',exclude_flags=True,flagged_file=str(flags)))
    rows=[];infos=[]
    for spec in specs:
        rr,info=fit_model(parts,work/'fits'/spec['name'],digest([key,'B',spec]),spec,a)
        rr=[dict(r,group_label=GROUPS[r['group']] if isinstance(r.get('group'),int) else r.get('group')) for r in rr]
        rows+=rr;infos.append(info)
        table(report,'tabB2_slopes_by_group',[r for r in rows if r['model']=='primary']);table(report,'tabB3_robustness',[r for r in rows if r['model']!='primary'])
    # Primary evidence produces a transparent trigger, not an automatic theoretical rewrite.
    D=next((r for r in rows if r.get('model')=='primary' and r.get('group')==1 and r.get('term')=='D_500_300_over_mean'),{})
    uninformative=D.get('ci_low') is None or D['ci_low']<=0<=D['ci_high']
    status=dict(status='ESTIMATED_WITH_REMAINING_CHECKS',D_trigger=bool(uninformative),models=infos,
      remaining=['Conditional logit and displayed-bin figure are run by B_supplement.',*(['Flag exclusion unavailable until Test A succeeds.'] if not flags.exists() else [])],
      decisions='Report all estimates and confidence intervals; nonrejection of BOTH−CO is not evidence of equality.')
    save(report/'STATUS.json',status);return status
