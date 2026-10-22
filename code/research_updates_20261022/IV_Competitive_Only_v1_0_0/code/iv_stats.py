"""Frozen absorption and CR0 covariance; scalar IV and two-moment extensions."""
from common import *
from numpy.polynomial import Polynomial as Poly

CRIT=1.959963984540054

def effect(beta,variance,scale=100.):
    r=dict(estimate=float(beta*scale),supported=False)
    if not np.isfinite(variance) or variance<=0:return dict(r,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se=math.sqrt(variance)*abs(scale)
    return dict(r,supported=True,se=se,p=math.erfc(abs(beta)/math.sqrt(variance)/math.sqrt(2)),
                ci_low=r['estimate']-CRIT*se,ci_high=r['estimate']+CRIT*se)

def from_ols(r,scale=100.):
    out=dict(supported=r.get('supported',False))
    for key,new in [('coefficient','estimate'),('standard_error','se'),('p_value_asymptotic','p'),('ci_low','ci_low'),('ci_high','ci_high')]:
        if key in r:out[new]=r[key]*(scale if key!='p_value_asymptotic' else 1.)
    if 'reason' in r:out['reason']=r['reason']
    return out

def psd(v,strict=False):
    ev=np.linalg.eigvalsh((v+v.T)/2);scale=max(float(abs(ev).max()),1e-30)
    return bool(ev.min()>(1e-11*scale) if strict else ev.min()>=-1e-10*scale),ev.tolist()

def scalar_panel(z,D,Y,R,meat,reference_sd):
    native=math.sqrt(float(z@z)/len(z));iv=oldstats.iv_result(Y,D,z,meat)
    rows=[]
    for label,r in [('First stage: receipt',iv.get('first_stage',{})),('Reduced form: later grant',iv.get('reduced_form',{})),
                    ('Reduced form: reach',fs.ols(R,z,meat))]:
        for scale,unit in [(100.,'pp per raw score unit'),(100*reference_sd,'pp per reference residual SD')]:
            rows.append(dict(estimator=label,units=unit,reference_sd=reference_sd,**from_ols(r,scale)))
    ivrow=dict(estimator='2SLS',units='pp per draw received',supported=iv.get('supported',False))
    for k,v in [('iv_coefficient','estimate'),('iv_standard_error','se'),('iv_ci_low','ci_low'),('iv_ci_high','ci_high')]:
        if k in iv:ivrow[v]=100*iv[k]
    if 'iv_p_value_asymptotic' in iv:ivrow['p']=iv['iv_p_value_asymptotic']
    if 'reason' in iv:ivrow['reason']=iv['reason']
    rows.append(ivrow)
    ols=fs.ols(Y,D,meat);rows.append(dict(estimator='Same-row OLS',units='pp per draw received',**from_ols(ols)))
    first=iv.get('first_stage',{});foot=dict(native_residual_sd=native,reference_sd=reference_sd,
        first_stage_F=first.get('wald_F_one_df'),partial_R2=iv.get('partial_first_stage_R2'),
        **{k:v for k,v in iv.items() if k.startswith('AR')})
    if 'coefficient' in first and 'coefficient' in ols:
        for scale,unit in [(100.,'pp per raw score unit'),(100*reference_sd,'pp per reference residual SD')]:
            rows.append(dict(estimator='OLS-implied reduced form (descriptive)',units=unit,
                estimate=scale*first['coefficient']*ols['coefficient'],supported=True,uncertainty='not estimated'))
    return dict(rows=rows,footer=foot)

def real_roots(poly):
    c=np.asarray(poly.coef,float);scale=max(float(abs(c).max()),1e-300)
    while len(c)>1 and c[-1]==0:c=c[:-1]
    if len(c)<=1:return []
    roots=Poly(c/scale).roots()
    return sorted(float(z.real) for z in roots if abs(z.imag)<=1e-7*(1+abs(z.real)))

def ar_two(Z,Y,D,meat):
    """Full-real-line inversion via quartic roots, not a bounded beta grid."""
    a=Z.T@Y;t=Z.T@D
    # Columns [z1*y,z2*y,z1*d,z2*d]; null covariance is A-b(B+B')+b²C.
    V=meat(np.column_stack([Z*Y[:,None],Z*D[:,None]]));ok,ev=psd(V)
    meta=dict(method='two-instrument null-moment CR0 AR; quartic full-real-line inversion',df=2,
              critical_value=-2*math.log(.05),null_moment_covariance_eigenvalues=ev)
    if not ok:return dict(meta,supported=False,reason='NON_PSD_NULL_MOMENT_COVARIANCE_NOT_REPAIRED')
    A=V[:2,:2];B=V[:2,2:]+V[2:,:2];C=V[2:,2:]
    v=[[Poly([A[i,j],-B[i,j],C[i,j]]) for j in range(2)] for i in range(2)]
    g=[Poly([a[i],-t[i]]) for i in range(2)]
    det=v[0][0]*v[1][1]-v[0][1]*v[1][0]
    numerator=g[0]*g[0]*v[1][1]-2*g[0]*g[1]*v[0][1]+g[1]*g[1]*v[0][0]
    boundary=numerator-meta['critical_value']*det
    roots=sorted(real_roots(boundary)+real_roots(det)+real_roots(v[0][0]))
    points=[]
    for b in roots:
        if not points or abs(b-points[-1])>1e-7*(1+abs(b)):points.append(b)
    def accepts(b):
        cov=A-b*B+b*b*C;valid,_=psd(cov,True)
        if not valid:return False
        g0=a-b*t;return float(g0@np.linalg.solve(cov,g0))<=meta['critical_value']*(1+1e-9)
    spans=[];cuts=[-math.inf]+points+[math.inf]
    for lo,hi in zip(cuts[:-1],cuts[1:]):
        mid=0. if math.isinf(lo) and math.isinf(hi) else (hi-max(1.,abs(hi)+1.) if math.isinf(lo) else lo+max(1.,abs(lo)+1.) if math.isinf(hi) else (lo+hi)/2)
        if accepts(mid):spans.append([lo,hi])
    for b in points:
        if accepts(b) and not any(lo<=b<=hi for lo,hi in spans):spans.append([b,b])
    spans.sort();merged=[]
    for lo,hi in spans:
        if merged and lo==merged[-1][1] and accepts(lo):merged[-1][1]=hi
        else:merged.append([lo,hi])
    intervals=[]
    for lo,hi in merged:
        intervals.append(dict(low_pp='-inf' if math.isinf(lo) else lo*100,high_pp='+inf' if math.isinf(hi) else hi*100,
            low_included=False if math.isinf(lo) else accepts(lo),high_included=False if math.isinf(hi) else accepts(hi)))
    return dict(meta,supported=True,intervals=intervals,unbounded=any(math.isinf(v) for x in merged for v in x),
                numerical_root_method='numpy polynomial roots; only exactly zero leading terms trimmed; real tolerance 1e-7')

def joint_iv(Z,D,Y,R,meat):
    Q=Z.T@Z;t=Z.T@D;a=Z.T@Y;ok,ev=psd(Q,True)
    base=dict(score_gram_eigenvalues=ev)
    if not ok:return dict(base,supported=False,reason='COLLINEAR_INSTRUMENTS',rows=[])
    inv=np.linalg.inv(Q);w=inv@t;den=float(t@w)
    if den<=1e-15:return dict(base,supported=False,reason='ZERO_JOINT_FIRST_STAGE',rows=[])
    beta=float(w@a)/den;u=Y-beta*D
    vv=meat(Z*u[:,None]);var=float(w@vv@w)/den**2
    rows=[dict(estimator='Two-instrument 2SLS',units='pp per draw received',**effect(beta,var))]
    pi=inv@t;fsV=inv@meat(Z*(D-Z@pi)[:,None])@inv
    fsok,fsev=psd(fsV,True);wald=float(pi@np.linalg.solve(fsV,pi)) if fsok else None
    footer=dict(first_stage_joint_chi2=wald,first_stage_df=2,first_stage_F_style=wald/2 if wald is not None else None,
                partial_R2=den/float(D@D) if D@D>0 else None,first_stage_covariance_eigenvalues=fsev)
    conditional=[]
    for o,y in [('receipt',D),('later_grant',Y),('reach',R)]:
        b=inv@(Z.T@y);V=inv@meat(Z*(y-Z@b)[:,None])@inv
        for k,name in enumerate(('comp','non')):
            other=Z[:,1-k];z=Z[:,k]-other*(other@Z[:,k])/(other@other);dy=D-other*(other@D)/(other@other)
            pr=float(z@dy)**2/(float(z@z)*float(dy@dy)) if z@z>0 and dy@dy>0 else None
            conditional.append(dict(instrument=name,outcome=o,units='pp per raw score unit, conditional on other component',
                partial_R2=pr if o=='receipt' else None,**effect(b[k],V[k,k])))
    gok,gev=psd(vv,True);gmm=dict(supported=False,moment_covariance_eigenvalues=gev)
    if gok:
        W=np.linalg.inv(vv);denG=float(t@W@t);bg=float(t@W@a)/denG;moment=a-bg*t
        J=float(moment@W@moment);vg=float(t@W@meat(Z*(Y-bg*D)[:,None])@W@t)/denG**2
        gmm.update(supported=True,estimate=100*bg,J=J,df=1,p=num.chi2_sf(J,1),
            weighting='two-step efficient GMM, covariance evaluated at preliminary 2SLS',fit=effect(bg,vg))
        rows.append(dict(estimator='Two-step efficient GMM',units='pp per draw received',**effect(bg,vg)))
    else:gmm['reason']='NON_POSITIVE_DEFINITE_MOMENT_COVARIANCE_NOT_REPAIRED'
    ratios=[];influence=[]
    for k in range(2):
        if abs(t[k])<=1e-15:break
        b=float(a[k]/t[k]);ratios.append(b);influence.append(Z[:,k]*(Y-b*D)/t[k])
    contrast=dict(supported=False,reason='ZERO_COMPONENT_FIRST_STAGE')
    if len(ratios)==2:
        V=meat(np.column_stack(influence));variance=float(np.array([1.,-1.])@V@np.array([1.,-1.]))
        contrast=dict(comp_iv_pp=100*ratios[0],non_iv_pp=100*ratios[1],joint_covariance_pp2=(V*10000).tolist(),
                      **effect(ratios[0]-ratios[1],variance))
        rows.append(dict(estimator='Competitive minus non-competitive IV',units='pp per draw received',**contrast))
    ar=ar_two(Z,Y,D,meat)
    return dict(base,supported=True,rows=rows,footer=footer,GMM_J=gmm,component_difference=contrast,AR95=ar,
                conditional_firststage_and_RF=conditional)

def design(d,family='XC',rich=True,z_names=('pooled','comp'),with_traits=False):
    xs,names,traits,tnames,groups,missing=oldstats.controls(d,rich)
    if any(missing.values()):raise RuntimeError('Missing frozen control; no new imputation permitted')
    if family=='XC':
        for name,v in [('competitive_expected_rate',d['comp_expected']),('log_competitive_decisions',np.log1p(d['comp_n'])),('log_competitive_counterparts',np.log1p(d['comp_counterparts']))]:
            if not np.isfinite(v).all():raise RuntimeError('Missing competitive history control')
            v=np.asarray(v,float);xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    outs=(['received'] if 'received' in d else [])+['y','reached']
    selected=[i for i,n in enumerate(tnames) if n in RECENT] if with_traits else []
    a=np.column_stack(xs+[d[ZCOLS[z]] for z in z_names]+[np.asarray(d[o],float) for o in outs]+[traits[i] for i in selected])
    res,info=num.partial_out(a,groups,len(xs));del a,xs
    zz={z:res[:,k] for k,z in enumerate(z_names)}
    yy={o:res[:,len(z_names)+k] for k,o in enumerate(outs)}
    tt={tnames[i]:res[:,len(z_names)+len(outs)+k] for k,i in enumerate(selected)}
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda score:fs.shared_meat(score,codes,True)
    meta=dict(n=len(d['row_id']),recipients=len(np.unique(d['recipient_id'])),opponents=len(np.unique(d['opponent_id'])),
        cells=len(np.unique(groups[0])),dates=len(np.unique(groups[1])),row_set_sha256=logic.row_digest(d['row_id']),
        controls=names,control_family=family,recipient_history_controls=rich,**info)
    return zz,yy,tt,meat,meta

def bins(z,D,meat,instrument):
    edges=np.unique(np.quantile(z,np.linspace(0,1,21)));groups=np.searchsorted(edges[1:-1],z,side='right')
    _,groups=np.unique(groups,return_inverse=True)
    counts=np.bincount(groups);means=np.bincount(groups,weights=D)/counts;scoremeans=np.bincount(groups,weights=z)/counts
    # Conditional on fitted residuals and bin assignments. This is a shape diagnostic.
    rows=[]
    for k in range(len(counts)):
        use=groups==k;influence=np.zeros(len(z));influence[use]=(D[use]-means[k])/counts[k]
        variance=float(meat(influence)[0,0]);fit=effect(means[k],variance)
        rows.append(dict(instrument=instrument,bin=k+1,n=int(counts[k]),mean_residual_score=float(scoremeans[k]),
            units='pp residual receipt',interval_conditions='fitted residuals and quantile boundaries fixed',**fit))
    return rows

def balances(zs,traits,meat,meta):
    rows=[];joints=[];values=np.column_stack([traits[k] for k in RECENT])
    for tag,z in zs.items():
        sd=math.sqrt(float(z@z)/len(z))
        if sd<=1e-10:
            joints.append(dict(instrument=tag,supported=False,reason='NO_RESIDUAL_SCORE_VARIATION'));continue
        z=z/sd;local=[]
        for k,name in enumerate(RECENT):
            local.append(dict(instrument=tag,trait=name,units='trait SD per native residual score SD',native_residual_sd=sd,
                **from_ols(fs.ols(values[:,k],z,meat),1.)))
        ps=[r.get('p',1.) if r.get('supported') else 1. for r in local];order=np.argsort(ps);running=0.
        for rank,k in enumerate(order):
            running=max(running,(len(local)-rank)*ps[k]);local[k]['p_Holm']=min(1.,running) if local[k].get('supported') else None
            local[k]['multiplicity_family']='seven recent traits within instrument/sample/controls'
        rows+=local;joints.append(dict(instrument=tag,traits=RECENT,**fs.joint(values,z,meat)))
    return rows,joints

def run_model(d,sample,family,reference_sds=None,rich=True,balance_only=False):
    z_names=('pooled','comp','non') if sample=='S2' else ('pooled','comp')
    if len(d['row_id'])<2000:return dict(sample=sample,control_family=family,status='INSUFFICIENT_ROWS',rows=[],n=len(d['row_id']))
    if 'received' in d and min(int(d['received'].sum()),len(d['row_id'])-int(d['received'].sum()))<20:
        return dict(sample=sample,control_family=family,status='INSUFFICIENT_RECEIPTS_OR_CONTROLS',rows=[],n=len(d['row_id']))
    zs,ys,traits,meat,meta=design(d,family,rich,z_names,with_traits=sample in ('S1','S2'))
    meta.update(sample=sample,scores_treated_as_fixed=True,author_included=True,clustering='shared_account_OR_date_CR0')
    sds={k:math.sqrt(float(z@z)/len(z)) for k,z in zs.items()};refs=dict(reference_sds or sds)
    if 'non' in sds:refs['non']=sds['non']
    result=dict(meta,status='ESTIMATED',native_sds=sds,reference_sds=refs,rows=[],footers={},binned=[],balance=[],joint_balance=[])
    if len(zs)>1:
        result['score_correlations_raw']=np.corrcoef(np.column_stack([d[ZCOLS[k]] for k in zs]),rowvar=False).tolist()
        result['score_correlations_residualized']=np.corrcoef(np.column_stack(list(zs.values())),rowvar=False).tolist()
        result['correlation_order']=list(zs)
    if traits:result['balance'],result['joint_balance']=balances(zs,traits,meat,meta)
    if balance_only:return result
    iv='received' in ys
    for tag,z in zs.items():
        if sds[tag]<=1e-10:
            result['rows'].append(dict(instrument=tag,estimator='Not estimated',supported=False,reason='NO_RESIDUAL_SCORE_VARIATION'));continue
        if iv:
            panel=scalar_panel(z,ys['received'],ys['y'],ys['reached'],meat,refs[tag])
            result['rows'] += [dict(instrument=tag,**r) for r in panel['rows']];result['footers'][tag]=panel['footer']
            if sample=='S1':result['binned']+=bins(z,ys['received'],meat,tag)
        else:
            for name,key in [('later grant','y'),('reach','reached')]:
                fit=fs.ols(ys[key],z,meat)
                for scale,units in [(100.,'pp per raw score unit'),(100*refs[tag],'pp per S1 reference residual SD')]:
                    result['rows'].append(dict(instrument=tag,estimator='Placebo: '+name,units=units,reference_sd=refs[tag],**from_ols(fit,scale)))
    if sample=='S2' and iv:
        joint=joint_iv(np.column_stack([zs['comp'],zs['non']]),ys['received'],ys['y'],ys['reached'],meat)
        result['joint']=joint;result['rows'] += [dict(instrument='both',**r) for r in joint['rows']]
        for r in joint.get('conditional_firststage_and_RF',[]):
            r['reference_sd']=refs[r['instrument']]
            for k in ('estimate','se','ci_low','ci_high'):
                if k in r:r[k+'_per_reference_sd']=r[k]*refs[r['instrument']]
        result['rows'].append(dict(instrument='both',estimator='Same-row OLS',units='pp per draw received',**from_ols(fs.ols(ys['y'],ys['received'],meat))))
    return result

def model_job(job):
    def build(tmp):
        c=io.conn(tmp/'spill',job.get('memory',2),1)
        try:d=arrays(c.execute('SELECT * FROM '+io.parq([job['input']])+' WHERE '+job['where']).to_arrow_table())
        finally:c.close()
        out=run_model(d,job['sample'],job['family'],job.get('reference_sds'),job.get('rich',True),job.get('balance_only',False))
        io.js(tmp/'result.json',out);return dict(n=len(d['row_id']))
    root,_=stable(job['output'],job['conf'],build,[job['input']])
    return io.load(root/'result.json')

def subgroup_specs():
    out=[dict(dimension='speed',label=s,where='speed='+io.lit(s)) for s in SPEEDS]
    for name,lo,hi in [('under_1200',None,1200),('1200_1599',1200,1600),('1600_1999',1600,2000),('2000_plus',2000,None)]:
        out.append(dict(dimension='rating',label=name,where=' AND '.join(([f'recipient_rating>={lo}'] if lo is not None else [])+([f'recipient_rating<{hi}'] if hi is not None else []))))
    out += [dict(dimension='month',label=m,where=f'month_code={k}') for k,m in enumerate(MONTHS)]
    out += [dict(dimension='prior_granting',label=k,where=w) for k,w in [('no_fair_decision','fair_90=0'),('fair_but_never_granted','fair_90>0 AND kind_90=0'),('ever_granted','kind_90>0')]]
    return out

def subgroup_job(job):
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:d=arrays(c.execute('SELECT * FROM '+io.parq([job['input']])+' WHERE comp_n>=5 AND isfinite(comp_z) AND ('+job['spec']['where']+')').to_arrow_table())
        finally:c.close()
        n=len(d['row_id']);receipts=int(d['received'].sum());base=dict(**job['spec'],n=n,receipts=receipts,
            reference_sd=job['reference_sd'],units='pp per S1 XC reference residual SD')
        if n<2000 or min(receipts,n-receipts)<20:rows=[dict(base,supported=False,reason='INSUFFICIENT_SUBGROUP_SUPPORT')]
        else:
            zs,ys,_,meat,meta=design(d,'XC',True,('comp',))
            rawz=d['comp_z']-d['comp_z'].mean();rawD=d['received']-d['received'].mean()
            rows=[dict(base,adjustment='raw',**from_ols(fs.ols(rawD,rawz,meat),100*job['reference_sd'])),
                  dict(base,adjustment='adjusted',**from_ols(fs.ols(ys['received'],zs['comp'],meat),100*job['reference_sd']))]
            z=zs['comp'];D=ys['received'];rows[1]['partial_R2']=float(z@D)**2/(float(z@z)*float(D@D)) if z@z>0 and D@D>0 else None
            rows[1]['native_residual_sd']=math.sqrt(float(z@z)/n)
            rows[1]['raw_adjusted_sign_reversal']=rows[0].get('estimate',0)*rows[1].get('estimate',0)<0
        io.js(tmp/'result.json',rows);return dict(n=n)
    root,_=stable(job['output'],job['conf'],build,[job['input']]);return io.load(root/'result.json')
