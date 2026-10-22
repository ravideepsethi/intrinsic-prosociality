"""FWL, multivariate CR0 and generated-index delta method.

No eigenvalue clipping, ridge or implicit complete-case deletion. Reuse the
frozen dyadic shared-account OR date inclusion-exclusion covariance exactly.
"""
from r7_common import *
from r7_memory import absorb_owned, shared_meat

def residualize(a,x):
    if not x.shape[1]:return a.copy(),0
    gram=x.T@x
    inv=np.linalg.pinv(gram,rcond=1e-12)
    return a-x@(inv@(x.T@a)),int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))

def absorb(a,groups,names=None):
    return env_numerics.absorb(a,groups,column_names=names)[0]

def project(x, a, groups, selection=None):
    """FWL in one owned buffer; row selection never copies whole input matrices."""
    xcolumns=list(x) if isinstance(x,(list,tuple)) else [x[:,j] for j in range(x.shape[1])]
    k=len(xcolumns);n=(len(xcolumns[0]) if k else len(groups[0])) if selection is None else int(np.count_nonzero(selection))
    columns=list(a) if isinstance(a,(list,tuple)) else [a[:,j] for j in range(a.shape[1])]
    width=len(columns)
    # Outcomes first, controls last: shrink the owned Fortran allocation after
    # FWL instead of copying an n-by-width result out of an n-by-(width+k) buffer.
    v=np.empty((n,width+k),dtype=float,order='F')
    for j,column in enumerate(columns):v[:,j]=column if selection is None else column[selection]
    for j,column in enumerate(xcolumns):v[:,width+j]=column if selection is None else column[selection]
    gg=groups if selection is None else [g[selection] for g in groups]
    v=absorb_owned(v,gg)[0]
    if k:
        gram=v[:,width:].T@v[:,width:]
        inv=np.linalg.pinv(gram,rcond=1e-12)
        rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
        beta=inv@(v[:,width:].T@v[:,:width])
        for start in range(0,n,32768):
            stop=min(n,start+32768)
            v[start:stop,:width]-=v[start:stop,width:]@beta
    else:rank=0
    # No view of v escapes this function; all input columns belong to x/a.
    v.resize((n,width),refcheck=False)
    return v,rank

def covariance(d):
    codes=stats.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],d['archive_start_ms']//DAY)
    return lambda s:shared_meat(s,codes,True)

def inference(beta,var,scale=1.):
    out=dict(coefficient=float(beta),coefficient_pp=float(beta)*scale)
    if not np.isfinite(var) or var<=0:return dict(out,supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se=math.sqrt(var);out.update(supported=True,standard_error=se,standard_error_pp=se*scale,
       ci_low=float(beta)-stats.stats.CRIT*se,ci_high=float(beta)+stats.stats.CRIT*se,
       ci_low_pp=(float(beta)-stats.stats.CRIT*se)*scale,ci_high_pp=(float(beta)+stats.stats.CRIT*se)*scale,
       ci90_low_pp=(float(beta)-1.6448536269514722*se)*scale,ci90_high_pp=(float(beta)+1.6448536269514722*se)*scale,
       p_value_asymptotic=math.erfc(abs(float(beta)/se)/math.sqrt(2)))
    return out

def wald(b,V):
    ev,u=np.linalg.eigh((V+V.T)/2);cut=max(float(abs(ev).max()),1e-30)*1e-9
    if ev.min() < -cut:return dict(supported=False,reason='NON_PSD_COVARIANCE_NOT_REPAIRED')
    use=ev>cut
    if not use.any():return dict(supported=False,reason='ZERO_RANK')
    if np.linalg.norm(u[:,~use].T@b)>1e-7*max(1.,np.linalg.norm(b)):
        return dict(supported=False,reason='RESTRICTION_OUTSIDE_COVARIANCE_RANGE')
    val=float(np.sum((u[:,use].T@b)**2/ev[use]));df=int(use.sum())
    return dict(supported=True,wald_chi2=val,rank=df,p_value_asymptotic=num.chi2_sf(val,df))

def multi(y,t,meat):
    G=t.T@t;bread=np.linalg.pinv(G,rcond=1e-12);rank=np.linalg.matrix_rank(G,tol=max(float(np.linalg.norm(G,2)),1)*1e-12)
    if rank!=t.shape[1]: raise RuntimeError('Joint trait design is rank deficient; no traits silently removed')
    b=bread@(t.T@y);e=y-t@b;score=t*e[:,None];V=bread@meat(score)@bread
    return b,V,e,bread

def scalar(y,z,meat,scale=1.):
    zz=float(z@z)
    if zz<=1e-20: return dict(supported=False,reason='NO_RESIDUAL_SCORE_VARIATION'),None
    b=float(z@y)/zz;influence=z*(y-b*z)/zz
    return inference(b,float(meat(influence)[0,0]),scale),influence

def generated_index(t, y, xtrain, xouter, zraw, groups, meat, mode='in_sample',
                    recipients=None,opponents=None,folds=4):
    """Full first-order sandwich for g = slope_z(T beta), scores fixed.

    Each out-of-fold prediction is trained after excluding BOTH roles of all
    accounts hashed to its recipient fold. Refit FE and continuous nuisance
    controls within each training set. Shared opponent/date dependence remains
    in inference; no independence or causal-bias claim is attached to this index.
    """
    n=len(y);p=t.shape[1]
    z=project(xouter,zraw[:,None],groups)[0][:,0];zz=float(z@z)
    if zz<=1e-20:raise RuntimeError('Calibration has no score variation')
    training_influence=np.zeros(n);pred=np.zeros(n);fold=np.zeros(n,dtype=int)
    if mode=='crossfit':
        fold=(num.user_hash(recipients)%np.uint64(folds)).astype(int)
        ofold=(num.user_hash(opponents)%np.uint64(folds)).astype(int)
        pairs=[((fold!=f)&(ofold!=f),fold==f) for f in range(folds)]
    else:pairs=[(np.ones(n,bool),np.ones(n,bool))]
    for k,(train,test) in enumerate(pairs):
        if train.sum()<p+20 or not test.any():raise RuntimeError('Calibration fold lacks support')
        tr=project(xtrain,np.column_stack([t,y]),groups,selection=None if mode=='in_sample' else train)[0]
        T=tr[:,:p];Y=tr[:,p]
        G=T.T@T
        if np.linalg.matrix_rank(G,tol=max(float(np.linalg.norm(G,2)),1)*1e-12)!=p:
            raise RuntimeError('Calibration training traits rank deficient')
        bread=np.linalg.inv(G);b=bread@(T.T@Y);e=Y-T@b
        pred[test]=t[test]@b
        # d g / d beta_k, full outer projection automatically via z residual.
        derivative=(z[test]@t[test])/zz
        training_influence[train]+=e*(T@(bread@derivative))
    pres=project(xouter,pred[:,None],groups)[0][:,0]
    b=float(z@pres)/zz
    influence=z*(pres-b*z)/zz
    fixed=influence.copy()
    influence+=training_influence
    result=inference(b,float(meat(influence)[0,0]))
    result.update(prediction_rule_uncertainty_included=True,method=mode,
       conditional_fixed_rule_SE=math.sqrt(max(0.,float(meat(fixed)[0,0]))),
       folds=folds if mode=='crossfit' else 1,
       training_rule='exclude both roles hashed to held-out recipient fold' if mode=='crossfit' else 'same estimation rows',
       interpretation='observed-history calibration; not identified selection bias')
    return result


def generated_indices(t, ys, xtrain, outers, zraw, groups, meat, recipients, opponents, folds=4):
    """Joint execution of A3; identical separate regressions, reused projections.

    One training projection per fold includes all requested outcome columns.
    Each outcome retains its own coefficients/residuals/delta influence. Outer
    residual scores and derivatives are computed separately for NH/full controls.
    """
    n,p=t.shape;q=ys.shape[1]
    zs={name:project(x,zraw[:,None],groups)[0][:,0] for name,x in outers.items()}
    zz={name:float(z@z) for name,z in zs.items()}
    if min(zz.values())<=1e-20:raise RuntimeError('Calibration has no score variation')
    fold=(num.user_hash(recipients)%np.uint64(folds)).astype(np.int8)
    ofold=(num.user_hash(opponents)%np.uint64(folds)).astype(np.int8)
    result=[]
    for mode in ('in_sample','crossfit'):
        pred=np.zeros((n,q),order='F')
        training={name:np.zeros((n,q),order='F') for name in outers}
        for f in range(1 if mode=='in_sample' else folds):
            train=None if mode=='in_sample' else (fold!=f)&(ofold!=f)
            test=None if mode=='in_sample' else fold==f
            if train is not None and (train.sum()<p+20 or not test.any()):
                raise RuntimeError('Calibration fold lacks support')
            # One transient t/ys matrix; projection fills its buffer by column.
            raw=[t[:,j] for j in range(p)]+[ys[:,j] for j in range(q)]
            tr=project(xtrain,raw,groups,selection=train)[0]
            del raw
            T=tr[:,:p];Y=tr[:,p:];G=T.T@T
            if np.linalg.matrix_rank(G,tol=max(float(np.linalg.norm(G,2)),1)*1e-12)!=p:
                raise RuntimeError('Calibration training traits rank deficient')
            bread=np.linalg.inv(G);b=bread@(T.T@Y);e=Y-T@b
            # Bounded row batches for predictions and derivative reductions.
            derivatives={name:np.zeros(p) for name in outers}
            for start in range(0,n,32768):
                stop=min(n,start+32768);ix=slice(start,stop)
                use=np.ones(stop-start,bool) if test is None else test[ix]
                tt=t[ix][use]
                block=pred[ix];block[use]=tt@b
                for name,z in zs.items():derivatives[name]+=z[ix][use]@tt/zz[name]
            for name in outers:
                effect=e*(T@(bread@derivatives[name]))[:,None]
                if train is None:training[name]+=effect
                else:training[name][train]+=effect
                del effect
            del T,Y,tr,e
            io.log(f'A3 {mode}: training fit {f+1}/{1 if mode=="in_sample" else folds} finished')
        for name,x in outers.items():
            pres=project(x,pred,groups)[0];z=zs[name]
            for j in range(q):
                b=float(z@pres[:,j])/zz[name]
                fixed=z*(pres[:,j]-b*z)/zz[name]
                influence=fixed+training[name][:,j]
                fit=inference(b,float(meat(influence)[0,0]))
                fit.update(prediction_rule_uncertainty_included=True,method=mode,
                    conditional_fixed_rule_SE=math.sqrt(max(0.,float(meat(fixed)[0,0]))),
                    folds=folds if mode=='crossfit' else 1,
                    training_rule='exclude both roles hashed to held-out recipient fold' if mode=='crossfit' else 'same estimation rows',
                    interpretation='observed-history calibration; not identified selection bias')
                result.append((j,name,float(np.sqrt(zz[name]/n)),fit))
            del pres
        del pred,training
    return result
