"""First-observed competitive grant hazard. The panel is left-censored."""
from common import *
from scipy.special import expit
from scipy.optimize import minimize

def design(d):
    cols=[np.ones(len(d['y']))];names=['intercept']
    numeric=['log_screens','had_receipt','log_days_receipt','had_claimed_winning','log_days_claimed_winning','cost','rating','log_tenure','tenure_missing']
    scaling={}
    for s in numeric:
        v=np.asarray(d[s],float)
        if not np.isfinite(v).all():raise RuntimeError('Nonfinite hazard covariate: '+s)
        mean=v.mean();sd=v.std()
        if sd<1e-12:continue
        cols.append((v-mean)/sd);names.append(s);scaling[s]=dict(mean=mean,sd=sd)
    cats=[]
    for s in ['state','stage','speed','month','cohort']:
        levels,ix=np.unique(d[s],return_inverse=True)
        for j in range(1,len(levels)):cats.append((ix,j));names.append(s+'='+str(levels[j]))
    def block(sl):return np.column_stack([a[sl] for a in cols]+[(a[sl]==j).astype(float) for a,j in cats])
    return block,names,scaling

def fit_logit(d,maxiter=500):
    block,names,scaling=design(d);n=len(d['y']);P=len(names);y=d['y'].astype(float)
    def objective(beta):
        loss=0.;gradient=np.zeros(P)
        for lo in range(0,n,100000):
            sl=slice(lo,lo+100000);x=block(sl);eta=x@beta;loss+=np.sum(np.logaddexp(0,eta)-y[sl]*eta);gradient+=x.T@(expit(eta)-y[sl])
        return loss/n,gradient/n
    init=np.zeros(P);rate=(y.sum()+.5)/(n+1);init[0]=np.log(rate/(1-rate))
    r=minimize(objective,init,jac=True,method='L-BFGS-B',options=dict(maxiter=maxiter,ftol=1e-12,gtol=1e-7))
    info=dict(status='ESTIMATED' if r.success else 'NOT_CONVERGED',message=str(r.message),rows=n,events=int(y.sum()),parameters=P,iterations=int(r.nit),gradient_max=float(abs(r.jac).max()))
    if not r.success:return info,[]
    ids,a=np.unique(d['chooser'],return_inverse=True);scores=np.zeros((len(ids),P));H=np.zeros((P,P))
    for lo in range(0,n,100000):
        sl=slice(lo,lo+100000);x=block(sl);p=expit(x@r.x);H+=x.T@(x*(p*(1-p))[:,None]);sc=x*(y[sl]-p)[:,None]
        for j in range(P):np.add.at(scores[:,j],a[sl],sc[:,j])
    info.update(accounts=len(ids),hessian_condition=float(np.linalg.cond(H)))
    if np.linalg.cond(H)>1e12:return dict(info,status='RANK_OR_SEPARATION_FAILURE'),[]
    inv=np.linalg.inv(H);V=inv@(scores.T@scores)@inv
    if len(ids)>1 and n>P:V*=len(ids)/(len(ids)-1)*(n-1)/(n-P)
    out=[]
    for j,name in enumerate(names):
        factor=scaling.get(name,{}).get('sd',1.);rr=interval(r.x[j]/factor,np.sqrt(V[j,j])/factor)
        out.append(dict(term=name,units='log odds per original unit',**rr))
    info['scaling']=scaling;return info,out

def run(c,work,folder,cfg):
    guard=cfg['history_guard_s']*1000
    base='''SELECT p.*,o.first_opportunity_ms,o.previous_max_end,o.simultaneous_starts,pr.created_ms,
      coalesce(h.screens_before,0)::BIGINT screens_before,coalesce(h.competitive_grants_before,0)::BIGINT competitive_grants_before,
      coalesce(h.receipts_before,0)::BIGINT receipts_before,coalesce(h.claimed_while_winning_before,0)::BIGINT claimed_while_winning_before,
      h.last_receipt_ms,h.last_claimed_winning_ms
      FROM panel p JOIN opportunity_order o USING(game_id) LEFT JOIN profiles pr USING(username)
      ASOF LEFT JOIN histories h ON p.chooser=h.account AND p.start_ms>h.available_ms'''
    c.execute('CREATE OR REPLACE TEMP VIEW hazard_base AS '+base)
    eligible=f'state>=2 AND competitive_grants_before=0 AND simultaneous_starts=1 AND (previous_max_end IS NULL OR previous_max_end+{guard}<start_ms)'
    flow=records(c,f'''SELECT count(*) opportunities,count(*) FILTER(WHERE state>=2) competitive,
      count(*) FILTER(WHERE state>=2 AND competitive_grants_before=0) no_prior_observed_competitive_grant,
      count(*) FILTER(WHERE {eligible}) retained,
      count(DISTINCT chooser) FILTER(WHERE {eligible}) retained_accounts,
      count(*) FILTER(WHERE {eligible} AND created_ms IS NOT NULL AND created_ms<=first_opportunity_ms) tenure_observed
      FROM hazard_base''');csvwrite(folder/'C1_sample_flow.csv',flow)
    # Tenure unknown is retained with a missing indicator, never invented as true age zero.
    query=f'''SELECT chooser,y,state,stage,speed,month,screens_before,
      strftime(to_timestamp(first_opportunity_ms/1000.),'%Y-%m') cohort,
      ln(1+screens_before) log_screens,(receipts_before>0)::INT had_receipt,
      CASE WHEN last_receipt_ms IS NOT NULL THEN ln(1+(start_ms-last_receipt_ms)/{DAY}.) ELSE 0 END log_days_receipt,
      (claimed_while_winning_before>0)::INT had_claimed_winning,
      CASE WHEN last_claimed_winning_ms IS NOT NULL THEN ln(1+(start_ms-last_claimed_winning_ms)/{DAY}.) ELSE 0 END log_days_claimed_winning,
      cost,rating/100. rating,
      CASE WHEN created_ms IS NOT NULL AND created_ms<=first_opportunity_ms THEN ln(1+(start_ms-created_ms)/{DAY}.) ELSE 0 END log_tenure,
      (created_ms IS NULL OR created_ms>first_opportunity_ms)::INT tenure_missing
      FROM hazard_base WHERE {eligible} ORDER BY chooser,start_ms,game_id'''
    copy(c,query,folder/'risk_rows_PRIVATE.parquet')
    c.execute('CREATE OR REPLACE TEMP VIEW hazard_risk AS SELECT * FROM '+scan(folder/'risk_rows_PRIVATE.parquet'))
    n,events=c.execute('SELECT count(*),sum(y) FROM hazard_risk').fetchone()
    if n<100 or events<10:raise Unavailable('Too few at-risk events for C1')
    d=arrays(c.execute('''SELECT * EXCLUDE(speed,month,cohort),
      CASE speed WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 ELSE 5 END::TINYINT speed,
      ((cast(substr(month,1,4) AS INT)-2023)*12+cast(substr(month,6,2) AS INT))::TINYINT AS "month",
      ((cast(substr(cohort,1,4) AS INT)-2023)*12+cast(substr(cohort,6,2) AS INT))::TINYINT cohort
      FROM hazard_risk''').to_arrow_table());info,est=fit_logit(d)
    write(folder/'C1_logit.json',info);csvwrite(folder/'C1_coefficients.csv',est)
    edges=np.unique(np.quantile(d['screens_before'],np.arange(.1,1,.1)));dec=np.searchsorted(edges,d['screens_before'],side='right')
    c.register('hazard_deciles',pa.table(dict(chooser=d['chooser'],y=d['y'],decile=dec)))
    from diagnostics import rate_table
    rate_table(c,folder/'C1_exposure_deciles.csv','decile',source='hazard_deciles');c.unregister('hazard_deciles')
    write(folder/'C1_method.json',dict(link='logit',exposure_decile_cutpoints=edges,
      risk='Competitive opportunities until first observed competitive grant; all-state prior screens counted',
      history='Observed pool/nonadjacent panel only; timestamps have a five-minute availability guard; ambiguous overlap rows excluded and counted',
      left_censoring=True,tenure='Known creation-date age plus missing indicator; first-opportunity-month and current-month effects',
      interpretation='Descriptive hazard association. Activity, dynamic selection and unobserved lifetime history remain; no causal construal or empathy claim.'))
    return info
