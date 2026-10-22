"""Original candidate fitting procedure; original models and controls."""
from common import *
from design import *
from stats import fit_conditional

FOLDS=(("2024-10","2024-11","2025-04"),("2025-04","2025-05","2025-10"))

def fit_one(d,model,inference=True,cue=None,start=None):
    full_n=len(d);full_accounts=d.chooser.nunique()
    counts=d.groupby('chooser').y.agg(['sum','count'])
    switchers=counts.index[(counts['sum']>0)&(counts['sum']<counts['count'])]
    # Exact likelihood contribution is zero outside these groups. Filter before
    # allocating the dense design, preserving all rows within retained accounts.
    d=d[d.chooser.isin(switchers)]
    cc=controls(d);best=None
    for p in (CURVATURE if model=='curved' else (.5,)):
        X,names,bounds=design(d,model,p,cue,cc)
        r=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds,start,inference=False)
        r.update(model=model,curvature=p,names=names,cue=cue,full_n=full_n,full_accounts=full_accounts)
        if r['status']=='ESTIMATED' and (best is None or r['loglik']>best['loglik']):best=r
    if best is None:return r
    if inference:
        X,names,bounds=design(d,model,best['curvature'],cue,cc)
        rr=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),bounds,best['beta'],inference=True)
        rr.update(model=model,curvature=best['curvature'],names=names,cue=cue,full_n=full_n,full_accounts=full_accounts);best=rr
    return best

