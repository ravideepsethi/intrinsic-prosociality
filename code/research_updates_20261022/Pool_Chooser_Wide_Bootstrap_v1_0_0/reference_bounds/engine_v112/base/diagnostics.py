"""Aggregate scoring; no account identifiers leave PRIVATE/."""
import numpy as np
from scipy.special import expit
from scipy.stats import norm
from io_utils import csv_write,json_write
from model import Model,predict,parameters,normal_weights


def paired(d,candidate,baseline,mask,weights=None):
    ids=d['ids'][mask];delta=(candidate-baseline)[mask]
    N=len(d['ptr'])-1
    n=np.bincount(ids,minlength=N);s=np.bincount(ids,weights=delta,minlength=N)
    w=np.ones(N) if weights is None else weights
    active=(n>0)&(w>0);M=int(active.sum())
    if M==0:return dict(accounts=0,opportunities=0,gain=None,conditional_se=None,conditional_p=None,equal_account_gain=None)
    den=float(w@n);gain=float(w@s/den)
    se=float(np.sqrt(M/max(M-1,1)*np.sum((w*(s-gain*n))**2))/den) if M>1 else None
    p=float(2*norm.sf(abs(gain/se))) if se is not None and se>0 else None
    return dict(accounts=M,opportunities=int(den),gain=gain,conditional_se=se,conditional_p=p,
      equal_account_gain=float(np.average(s[active]/n[active],weights=w[active])))


def holm(rows,key='conditional_p'):
    order=sorted([i for i,r in enumerate(rows) if r.get(key) is not None],key=lambda i:rows[i][key])
    last=0.
    for j,i in enumerate(order):
        last=max(last,min(1.,(len(order)-j)*rows[i][key]));rows[i]['conditional_holm_p']=last
    return rows


CORE_PAIRS=[('desert','level'),('cost','level'),('both','level'),('desert','cost'),
  ('both','desert'),('both','cost'),('free_index','both'),('type_cells','free_index'),
  ('both','no_cost'),('both','premium_only'),('separate_costs','both'),('signed_costs','separate_costs')]
NOISE_PAIRS=[('noisy_tiers','accurate_tiers'),('noisy_common','accurate_common'),
             ('noisy_tiers','noisy_common')]


def summaries(fits,d,meta,report,prefix=''):
    forecasts={};scores={};totals=[];calibration=[];parameter_rows=[];surface=[];singular=[]
    mask=d['period']==2
    groups=[('all',np.ones(len(mask),bool))]
    groups += [('board_'+str(b),d['board']==b) for b in range(5)]
    groups += [('tier_'+str(h),d['tier']==h) for h in range(4)]
    groups += [('loss_positive',d['loss']>0),('loss_zero',d['loss']==0),('ply2',d['stage']==0)]
    groups += [('boundary',d['boundary']),('not_boundary',~d['boundary'])]
    for name,res in fits.items():
        p,ll=predict(res,d,meta);forecasts[name]=p;scores[name]=ll
        pr,dec=parameters(res,meta,meta.get('reference_group_weights'))
        parameter_rows.extend(pr)
        for c in meta['support']:
            for k in range(res['J']):surface.append(dict(model=name,type=k,cell=c,
              board=c//20,stage=(c//5)%4,expected_score_bin=c%5,
              index=float(dec['A'][c]) if dec['A'] is not None else None,
              utility_effect=float(dec['effect'][k,c])))
        sv=np.linalg.svd(dec['effect'][:,meta['support']],compute_uv=False)
        singular.extend(dict(model=name,component=i+1,singular_value=float(x)) for i,x in enumerate(sv))
        for label,g in groups:
            m=mask&g;n=int(m.sum())
            if n==0:continue
            ids=d['ids'][m];count=np.bincount(ids,minlength=len(d['ptr'])-1)
            ss=np.bincount(ids,weights=ll[m],minlength=len(count));active=count>0
            totals.append(dict(model=name,group=label,opportunities=n,accounts=int(active.sum()),
              grants=int(d['y'][m].sum()),mean_log_score=float(ll[m].mean()),
              equal_account_log_score=float(np.mean(ss[active]/count[active])),
              brier=float(np.mean((d['y'][m]-p[m])**2)),observed_rate=float(d['y'][m].mean()),
              predicted_rate=float(p[m].mean())))
            calibration.append(dict(model=name,group=label,opportunities=n,
              observed_grants=float(d['y'][m].sum()),predicted_grants=float(p[m].sum())))
        # Fixed probability bins, not cutpoints chosen using evaluation outcomes.
        edges=np.array([0,.001,.0025,.005,.01,.025,.05,.1,.25,.5,1.00001])
        bucket=np.searchsorted(edges[1:-1],p,side='right')
        for j in range(len(edges)-1):
            m=mask&(bucket==j)
            if m.any():calibration.append(dict(model=name,group='predicted_bin_'+str(j),opportunities=int(m.sum()),
              observed_grants=float(d['y'][m].sum()),predicted_grants=float(p[m].sum())))
    pairs=NOISE_PAIRS if prefix else CORE_PAIRS
    if 'calibrated' in fits:pairs=pairs+[('both','calibrated')]
    primary=[];bygroup=[]
    for a,b in pairs:
        if a not in fits or b not in fits:continue
        primary.append(dict(candidate=a,baseline=b,**paired(d,scores[a],scores[b],mask)))
        for label,g in groups[1:]:bygroup.append(dict(candidate=a,baseline=b,group=label,**paired(d,scores[a],scores[b],mask&g)))
    csv_write(report/(prefix+'comparisons.csv'),holm(primary))
    csv_write(report/(prefix+'comparisons_by_state.csv'),bygroup)
    csv_write(report/(prefix+'scores.csv'),totals)
    csv_write(report/(prefix+'calibration.csv'),calibration)
    csv_write(report/(prefix+'types.csv'),parameter_rows)
    csv_write(report/(prefix+'state_surfaces.csv'),surface)
    csv_write(report/(prefix+'surface_singular_values.csv'),singular)
    return scores,primary


def support_diagnostics(d,meta,report):
    mask=d['period']<2
    X=np.column_stack([np.ones(mask.sum()),d['Z'][mask],d['kappa'][mask],d['loss'][mask]])
    residual=X[:,-2:]-X[:,:-2]@np.linalg.lstsq(X[:,:-2],X[:,-2:],rcond=1e-10)[0]
    sv=np.linalg.svd(residual,compute_uv=False)
    rates=[]
    for c in meta['support']:
        m=mask&(d['cell']==c)
        rates.append(dict(cell=c,board=c//20,stage=(c//5)%4,expected_score_bin=c%5,
          opportunities=int(m.sum()),accounts=int(np.unique(d['ids'][m]).size),grants=int(d['y'][m].sum()),
          premium_sd=float(d['kappa'][m].std()),loss_sd=float(d['loss'][m].std())))
    csv_write(report/'training_cell_support.csv',rates)
    json_write(report/'COST_SUPPORT.json',dict(residual_cost_singular_values=sv.tolist(),
      residual_cost_condition_number=float(sv[0]/sv[-1]) if sv[-1]>1e-12 else None,
      warning='Descriptive linear support conditional on controls, not proof of identification or an exogenous price design. E also enters the state index.'))
    from prepare import subset
    tr=subset(d,mask);ptr=tr['ptr'];n=np.diff(ptr);ids=tr['ids']
    premium_range=np.maximum.reduceat(tr['kappa'],ptr[:-1])-np.minimum.reduceat(tr['kappa'],ptr[:-1])
    fair=np.add.reduceat((tr['board']>=2).astype(int),ptr[:-1])
    lost=np.add.reduceat((tr['board']==0).astype(int),ptr[:-1])
    cells=np.bincount(np.unique(ids*100+tr['cell'])//100,minlength=len(n))
    centered=np.column_stack([tr[k]-np.add.reduceat(tr[k],ptr[:-1])[ids]/n[ids] for k in ['kappa','loss']])
    within_sv=np.linalg.svd(centered,compute_uv=False)
    json_write(report/'WITHIN_ACCOUNT_SUPPORT.json',dict(accounts=len(n),
      at_least_two_opportunities=int((n>=2).sum()),multiple_state_cells=int((cells>=2).sum()),
      both_competitive_and_clearly_worse=int(((fair>0)&(lost>0)).sum()),
      varying_premium=int((premium_range>1e-6).sum()),
      within_account_cost_singular_values=within_sv.tolist(),
      opportunity_quantiles={str(q):float(np.quantile(n,q)) for q in [0,.25,.5,.75,.9,.99,1]},
      note='Variation audit, not a sufficient identification condition. No account-level slope estimates are treated as observed types.'))


def perception_decomposition(result,d,meta,report):
    m=Model(result['spec'],result['J'],meta,result['bound']);dec=m.decode(np.array(result['parameters']))
    wprior=np.asarray(meta['reference_group_weights'])@np.exp(dec['lp']) if m.groups==4 else np.exp(dec['lp'][0])
    # Reference covariate distribution is evaluation opportunities, identical for every hypothetical tier.
    mask=d['period']==2
    rows=[]
    state=(dec['alpha'][None,:]+(d['Z'][:,m.cols]@dec['eta'])[:,None]
       -d['kappa'][:,None]*dec['B'][None,:,0]-d['loss'][:,None]*dec['B'][None,:,1])
    cells=(np.arange(5)[None,:]*4+d['stage'][:,None])*5+d['q'][:,None]
    A=dec['A'][cells]
    p0=expit(state+dec['effect'][:,d['cell']].T)
    for h,sd in enumerate(dec['sigma']):
        weights,_=normal_weights(d['b'],np.full(len(d['y']),sd))
        p=(weights[:,None,:]*expit(state[:,:,None]+dec['theta'][None,:,None]*A[:,None,:])).sum(axis=2)
        meanA=(weights*A).sum(axis=1)
        pm=expit(state+dec['theta'][None,:]*meanA[:,None])
        for label,g in [('all',np.ones(len(mask),bool))]+[('board_'+str(b),d['board']==b) for b in range(5)]+[('stage_'+str(s),d['stage']==s) for s in range(4)]:
            use=mask&g
            if use.any():rows.append(dict(model=m.spec.name,hypothetical_sigma_tier=h,sigma_cp=float(sd),group=label,
              opportunities=int(use.sum()),accurate_rate=float(np.mean(p0[use]@wprior)),
              noisy_rate=float(np.mean(p[use]@wprior)),curvature_component=float(np.mean((p-pm)[use]@wprior)),
              mean_index_component=float(np.mean((pm-p0)[use]@wprior))))
    csv_write(report/('perception_decomposition_'+m.spec.name+'.csv'),rows)
