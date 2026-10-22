"""Reconstruct the explicitly specified current manuscript state-persistence tables.

The included pass must reproduce the printed sample sizes and correlations.
Regression reconstruction is separately checked; a mismatch remains a blocker.
"""
from remaining_common import *

def correlation(x,y,w=None):
    x=np.asarray(x,float);y=np.asarray(y,float)
    w=np.ones(len(x)) if w is None else np.asarray(w,float)
    w=w/w.sum();a=x-np.sum(w*x);b=y-np.sum(w*y)
    return float(np.sum(w*a*b)/np.sqrt(np.sum(w*a*a)*np.sum(w*b*b)))

def hc1(X,Y):
    n,k=X.shape
    require(np.linalg.matrix_rank(X)==k,'Persistence regression design is rank deficient')
    bread=np.linalg.inv(X.T@X);beta=bread@X.T@Y;err=Y-X@beta
    # Joint covariance, retaining the covariance of the two outcomes.
    score=np.concatenate([X*err[:,j,None] for j in range(Y.shape[1])],axis=1)
    B=np.kron(np.eye(Y.shape[1]),bread)
    return beta,B@(score.T@score)@B*(n/(n-k))

def weighted_hc1(X,Y,W):
    """Outcome-specific analytical weights; joint account-level HC1 covariance.

    This is a single, declared reconstruction candidate, not a search across
    specifications. Its weighted outcome means are pooled opportunity rates.
    Publication remains blocked unless every printed regression check passes.
    """
    n,k=X.shape
    require(W.shape==Y.shape and np.isfinite(W).all() and (W>0).all(),'Invalid persistence weights')
    beta=np.empty((k,Y.shape[1]));influence=[]
    for j in range(Y.shape[1]):
        bread=np.linalg.inv(X.T@(W[:,j,None]*X))
        beta[:,j]=bread@X.T@(W[:,j]*Y[:,j])
        residual=Y[:,j]-X@beta[:,j]
        influence.append((X*(W[:,j]*residual)[:,None])@bread)
    influence=np.concatenate(influence,axis=1)
    return beta,influence.T@influence*(n/(n-k))

def run_stage(args,auth,out):
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        c.execute('CREATE VIEW p AS SELECT *,CASE WHEN month<\'2024-11\' THEN 1 ELSE 2 END yr FROM '+scan([r['path'] for r in auth['month_records']]))
        parts=[]
        for y in (1,2):
            for s,condition in [('C','fair_competitive'),('L','clearly_worse'),('N','NOT fair_competitive')]:
                for suffix,late in [('', 'TRUE'),('_late','ply_count>10')]:
                    wh=f'yr={y} AND ({condition}) AND ({late})'
                    parts += [f'count(*) FILTER(WHERE {wh})::DOUBLE n{s}{y}{suffix}',f'coalesce(sum(kind_draw::INTEGER) FILTER(WHERE {wh}),0)::DOUBLE k{s}{y}{suffix}']
        for speed in ['ultrabullet','bullet','blitz','rapid','classical']:
            parts.append(f'count(*) FILTER(WHERE yr=2 AND api_speed={q(speed)})::DOUBLE/nullif(count(*) FILTER(WHERE yr=2),0) speed_{speed}')
        p=out/'PRIVATE/account_years.parquet'
        copy(c,'SELECT chooser_username_norm account,'+','.join(parts)+' FROM p GROUP BY 1',p)
    finally:c.close()
    d=pd.read_parquet(p);cors=[];trans=[];retention=[];composites=[];balanced=None
    samples=[('min1',1,'L',''),('min4',4,'L',''),('min10',10,'L',''),('min4_after_ply10',4,'L','_late'),('min4_noncompetitive',4,'N','')]
    for label,m,s,late in samples:
        elig1=(d.nC1>=m)&(d['n'+s+'1']>=m)
        elig2=(d.nC2>=m)&(d['n'+s+'2']>=m)
        mask=elig1&elig2
        if late:mask &= (d.nC1_late>0)&(d.nC2_late>0)&(d['n'+s+'1_late']>0)&(d['n'+s+'2_late']>0)
        a=d.loc[mask].copy()
        if label=='min4':balanced=a
        counts=[a['n'+state+str(y)+late].to_numpy() for state,y in [('C',1),('C',2),(s,1),(s,2)]]
        rates=[a['k'+state+str(y)+late].to_numpy()/n for (state,y),n in zip([('C',1),('C',2),(s,1),(s,2)],counts)]
        pairs=[(0,1,'C1_C2'),(2,3,'L1_L2'),(0,3,'C1_L2'),(2,1,'L1_C2')]
        vals={}
        for i,j,name in pairs:
            r=correlation(rates[i],rates[j]);vals[name]=r
            w=2*counts[i]*counts[j]/(counts[i]+counts[j])
            cors.append(dict(sample=label,contrast=name,accounts=len(a),correlation=r,harmonic_correlation=correlation(rates[i],rates[j],w)))
        product=vals['C1_C2']*vals['L1_L2'];scale=np.sqrt(product) if product>0 else np.nan
        for name in ('C1_L2','L1_C2'):cors.append(dict(sample=label,contrast='implied_'+name,accounts=len(a),correlation=vals[name]/scale))
        for name,x,y in [('selectivity',rates[0]-rates[2],rates[1]-rates[3]),('mean_rate',(rates[0]+rates[2])/2,(rates[1]+rates[3])/2)]:
            composites.append(dict(sample=label,contrast=name,accounts=len(a),correlation=correlation(x,y)))
        g1=(rates[0]>0).astype(int)+2*(rates[2]>0).astype(int);g2=(rates[1]>0).astype(int)+2*(rates[3]>0).astype(int)
        names=['neither','competitive_only','lost_only','both']
        for i in range(4):
            n=int((g1==i).sum())
            for j in range(4):trans.append(dict(sample=label,first_group=names[i],second_group=names[j],first_accounts=n,accounts=int(((g1==i)&(g2==j)).sum()),row_pct=100*float(((g1==i)&(g2==j)).sum())/n if n else None))
        g=(d.kC1>0).astype(int)+2*(d['k'+s+'1']>0).astype(int)
        for i in range(4):
            n=int((elig1&(g==i)).sum());k=int((elig1&elig2&(g==i)).sum())
            retention.append(dict(sample=label,first_group=names[i],eligible_year1=n,eligible_both=k,return_pct=100*k/n if n else None))
    table(out/'report/correlations',cors);table(out/'report/transitions',trans);table(out/'report/retention',retention);table(out/'report/composite_correlations',composites)
    # The equal-account reconstruction did not reproduce the printed models.
    # Evaluate one explicit alternative: second-year opportunity weights for
    # each outcome, suggested by the manuscript's pooled outcome means.
    a=balanced;Y=np.column_stack([100*a.kC2/a.nC2,100*a.kL2/a.nL2])
    speeds=a[['speed_ultrabullet','speed_bullet','speed_blitz','speed_rapid']].to_numpy(float)
    sd=speeds.std(axis=0);speeds=(speeds-speeds.mean(axis=0))/np.where(sd>0,sd,1)
    speeds=speeds[:,sd>0];rows=[];contrasts=[];unweighted=[]
    weights=np.column_stack([a.nC2,a.nL2]);means=(weights*Y).sum(axis=0)/weights.sum(axis=0)
    write(out/'report/RECONSTRUCTION_METHOD.json',dict(status='CANDIDATE_PENDING_REPRODUCTION',original_producer_recovered=False,
        weights='Each outcome weighted by its second-year opportunity count; covariance clusters the joint scores by account, HC1',
        rationale='Printed outcome means differ from equal-account means; test the corresponding opportunity-weighted specification without searching additional specifications',
        means_pp=means,second_year_opportunities=weights.sum(axis=0),equal_account_means_pp=Y.mean(axis=0)))
    for model in ['indicators','rates']:
        if model=='indicators':
            u=(a.kC1.to_numpy()>0).astype(float);v=(a.kL1.to_numpy()>0).astype(float)
            focal=np.column_stack([u,v,u*v]);names=['competitive','losing','both']
        else:focal=np.column_stack([100*a.kC1/a.nC1,100*a.kL1/a.nL1]);names=['competitive','losing']
        X=np.column_stack([np.ones(len(a)),focal,speeds]);beta,V=weighted_hc1(X,Y,weights);k=X.shape[1]
        ub,uV=hc1(X,Y)
        for j,state in enumerate(['competitive','losing']):
            for i,name in enumerate(names,1):
                rows.append(dict(model=model,outcome=state,term=name,coefficient_pp=beta[i,j],se_pp=np.sqrt(max(0,V[j*k+i,j*k+i])),accounts=len(a),mean_pp=means[j]))
                unweighted.append(dict(model=model,outcome=state,term=name,coefficient_pp=ub[i,j],se_pp=np.sqrt(max(0,uV[j*k+i,j*k+i])),accounts=len(a),mean_pp=Y[:,j].mean()))
        if model=='indicators':
            # Means are sample normalizations, held fixed as stated in the table.
            for i,name,sgn in [(1,'competitive_own_minus_cross',1),(2,'losing_own_minus_cross',-1)]:
                z=np.zeros(2*k);z[i]=sgn/means[0];z[k+i]=-sgn/means[1]
                contrasts.append(dict(contrast=name,estimate=float(z@beta.T.ravel()),se=float(np.sqrt(max(0,z@V@z))),accounts=len(a)))
    table(out/'report/regressions',rows);table(out/'report/normalized_contrasts',contrasts)
    table(out/'report/equal_account_diagnostic',unweighted)
    gates=[]
    if args.variant=='included':
        gates.append(dict(sample='outcome_means_and_exposure',status='REPRODUCED' if np.all(np.abs(means-[1.935,.293])<.0005001) and np.array_equal(weights.sum(axis=0),[3285484,4616581]) else 'MISMATCH',actual_means=means,actual_opportunities=weights.sum(axis=0)))
        expected={'min1':(670481,.522,.300,.164,.181),'min4':(266399,.727,.494,.239,.271),'min10':(82311,.793,.616,.295,.321),'min4_after_ply10':(265901,.661,.493,.236,.265),'min4_noncompetitive':(278774,.725,.514,.349,.376)}
        for label,ex in expected.items():
            r=[x for x in cors if x['sample']==label and not x['contrast'].startswith('implied')]
            ok=all(x['accounts']==ex[0] for x in r) and all(abs(x['correlation']-v)<.0005001 for x,v in zip(r,ex[1:]))
            gates.append(dict(sample=label,status='REPRODUCED' if ok else 'MISMATCH',expected_accounts=ex[0],actual_accounts=r[0]['accounts']))
        for model,state,term,b,se in [('indicators','competitive','competitive',10.953,.134),('indicators','losing','competitive',.351,.015),('indicators','competitive','losing',.918,.067),('indicators','losing','losing',.508,.041),('indicators','competitive','both',12.329,.634),('indicators','losing','both',4.549,.345),('rates','competitive','competitive',.702,.006),('rates','losing','competitive',.024,.002),('rates','competitive','losing',.138,.021),('rates','losing','losing',.485,.028)]:
            row=next(x for x in rows if (x['model'],x['outcome'],x['term'])==(model,state,term))
            gates.append(dict(sample='/'.join([model,state,term]),status='REPRODUCED' if abs(row['coefficient_pp']-b)<.0005001 and abs(row['se_pp']-se)<.0005001 else 'MISMATCH',actual=row))
        for r,(b,se) in zip(contrasts,[(4.462,.077),(1.262,.132)]):
            gates.append(dict(sample=r['contrast'],status='REPRODUCED' if abs(r['estimate']-b)<.0005001 and abs(r['se']-se)<.0005001 else 'MISMATCH',actual=r))
        for label,want in [('min1',(.458,.533)),('min4',(.689,.727)),('min10',(.766,.790))]:
            vals=[r['correlation'] for r in composites if r['sample']==label]
            gates.append(dict(sample=label+'/composite',status='REPRODUCED' if all(abs(x-y)<.0005001 for x,y in zip(vals,want)) else 'MISMATCH',actual=vals))
        for term,want in [('neither',231905),('competitive_only',24896),('lost_only',5848),('both',3750)]:
            got=next(x['first_accounts'] for x in trans if x['sample']=='min4' and x['first_group']==term)
            gates.append(dict(sample='min4/'+term,status='REPRODUCED' if got==want else 'MISMATCH',actual=got))
    write(out/'report/REPRODUCTION.json',gates)
    require(not any(g['status']=='MISMATCH' for g in gates),'State-persistence reconstruction does not reproduce all printed checks; inspect REPRODUCTION.json')
    return dict(status='PAIRED_REFIT_RECONSTRUCTED_SPECIFICATION_REQUIRES_REVIEW',source='Explicit opportunity-weighted reconstruction; strict included reproduction gate; original producer unavailable',accounts=len(balanced),standard_errors='HC1, joint across two outcomes',weighting='outcome-specific second-year opportunities')

