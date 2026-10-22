"""Predetermined-history ply-2 check and selected-snapshot Patron validation."""
from pathlib import Path
import math
import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.optimize import minimize
from scipy.stats import rankdata
from util import *
from features import design
from prepare_sequences import SPLIT,END
import hmm
from model_analysis import losses,gain_stats

SNAPSHOT_SHA='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'


def resolve_profiles(project):
    path=Path(project)/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    if not path.exists():return None
    require(sha256_file(path)==SNAPSHOT_SHA,'Certified profile snapshot has changed')
    return path


def profile_view(db,path):
    db.execute(f'CREATE OR REPLACE VIEW profiles AS SELECT * FROM read_parquet({qs(path)})')
    n,u,bad=db.execute('''SELECT count(*),count(DISTINCT username_norm),
       count(*) FILTER(WHERE (returned AND patron IS NULL) OR (NOT returned AND patron IS NOT NULL)) FROM profiles''').fetchone()
    require(n==u and bad==0,'Profile identifiers or missingness inconsistent with contract')


def ply2_regression(db,report):
    df=db.execute(f'''SELECT s.chooser_user_id AS chooser,s.y,s.board,s.ply_count AS ply,
      (c.other_g_train=0)::INTEGER AS prior_zero,s.month,s.api_speed AS speed,
      (s.disconnected_elo-s.chooser_elo)/100. AS gap,
      CASE WHEN s.chooser_draw_payoff_v2 IS NOT NULL THEN greatest(0.,-s.chooser_draw_payoff_v2)/5. END AS loss,
      s.chooser_pre_rd_v2/100. AS crd,s.disconnected_pre_rd_v2/100. AS drd,
      CASE WHEN s.chooser_clock_last_obs_s IS NOT NULL THEN ln(1+greatest(0.,s.chooser_clock_last_obs_s)) END AS cclock,
      CASE WHEN s.disconnected_clock_last_obs_s IS NOT NULL THEN ln(1+greatest(0.,s.disconnected_clock_last_obs_s)) END AS dclock
      FROM source s JOIN cohort c ON s.chooser_user_id=c.chooser
      WHERE c.cohort='evaluation' AND s.api_last_move_at_ms>={SPLIT} AND s.api_last_move_at_ms<{END} AND s.ply_count IN (2,20)
        AND s.board>=2 AND c.other_n_train>=5''').fetchdf()
    if len(df):
        coverage=df.groupby('chooser').ply.nunique();df=df[df.chooser.isin(coverage[coverage==2].index)].copy()
    base=dict(rows=len(df),accounts=int(df.chooser.nunique()),competitive_only=True,
       prior_history='At least five first-year opportunities outside ply 2; prior-zero label fixed before evaluation year',
       specification='Account FE; ply2 and ply2 x no prior non-ply2 grant; board bins, costs, RDs, clocks, speed, season',
       interpretation='Conditional descriptive interaction; cannot separate salience from warrant or prove gate crossings')
    if len(df)<200 or df.chooser.nunique()<50 or df.prior_zero.nunique()<2:
        result=dict(base,status='INSUFFICIENT_WITHIN_ACCOUNT_SUPPORT')
        atomic_json(report/'PLY2_INTERACTION.json',result);return result
    ids=np.unique(df.chooser,return_inverse=True)[1];N=ids.max()+1;n=np.bincount(ids)
    p2=(df.ply.to_numpy()==2).astype(float)
    columns=[p2,p2*df.prior_zero.to_numpy(),(df.board.to_numpy()==3).astype(float),(df.board.to_numpy()==4).astype(float)]
    names=['ply2','ply2_x_prior_zero','board3','board4']
    for name in ['gap','loss','crd','drd','cclock','dclock']:
        v=df[name].to_numpy(float);bad=~np.isfinite(v)
        columns.append(np.where(bad,0,v));names.append(name)
        if bad.any():columns.append(bad.astype(float));names.append(name+'_missing')
    for feature in ('speed','month'):
        vals=sorted(df[feature].fillna('__MISSING__').unique())
        for value in vals[1:]:columns.append((df[feature].fillna('__MISSING__').to_numpy()==value).astype(float));names.append(feature+'_'+value)
    X=np.column_stack(columns);y=df.y.to_numpy(float)
    X-=np.column_stack([np.bincount(ids,weights=X[:,k])/n for k in range(X.shape[1])])[ids]
    y-=np.bincount(ids,weights=y)[ids]/n[ids]
    gram=X.T@X;inv=np.linalg.pinv(gram,rcond=1e-10);beta=inv@(X.T@y)
    identifiable=np.max(abs((inv@gram)[1]-np.eye(X.shape[1])[1]))<1e-6
    if not identifiable:
        result=dict(base,status='TARGET_NOT_IDENTIFIED');atomic_json(report/'PLY2_INTERACTION.json',result);return result
    residual=y-X@beta;score=np.column_stack([np.bincount(ids,weights=X[:,j]*residual) for j in range(X.shape[1])])
    V=inv@(score.T@score)@inv*N/(N-1);v=float(V[1,1]);delta=float(beta[1])
    result=dict(base,status='DESCRIPTIVE_FE_INTERACTION_COMPLETE',coefficient_pp=100*delta,
      SE_pp=100*math.sqrt(v) if v>0 else None,p_value=math.erfc(abs(delta)/math.sqrt(2*v)) if v>0 else None,
      first_year_zero_accounts=int(df[df.prior_zero==1].chooser.nunique()),
      first_year_other_grant_accounts=int(df[df.prior_zero==0].chooser.nunique()),
      covariance='chooser-clustered CR1; conditional on fixed first-year classification')
    atomic_json(report/'PLY2_INTERACTION.json',result);return result


def fit_logit(X,y,ridge=1.):
    start=np.zeros(X.shape[1]);start[0]=np.log((y.sum()+.5)/(len(y)-y.sum()+.5))
    def fun(b):
        eta=X@b;pen=b.copy();pen[0]=0
        return float(np.logaddexp(0,eta).sum()-y@eta+.5*ridge*(pen@pen)),X.T@(expit(eta)-y)+ridge*pen
    return minimize(fun,start,jac=True,method='L-BFGS-B',options=dict(maxiter=600,ftol=1e-11,gtol=1e-6))


def patron(db,path,df,fits,private,report):
    if path is None:
        status=dict(status='NOT_RUN_MISSING_CERTIFIED_PROFILE_SNAPSHOT');atomic_json(report/'PATRON_STATUS.json',status);return status
    profile_view(db,path)
    # Refuse to guess a numeric-account / username bridge.
    bad=db.execute('''SELECT count(*) FROM (SELECT s.chooser_user_id,count(DISTINCT s.chooser_username_norm) n
      FROM source s SEMI JOIN cohort c ON s.chooser_user_id=c.chooser GROUP BY s.chooser_user_id HAVING n<>1)''').fetchone()[0]
    require(bad==0,'Account-to-normalized-name mapping is not unique')
    known=db.execute('''SELECT c.chooser,c.cohort,c.n_train,c.g_train,c.f_train,c.l_train,c.fg_train,c.lg_train,c.rating_train,
      p.returned,p.patron,p.created_at_ms
      FROM cohort c LEFT JOIN profiles p ON c.username_norm=p.username_norm''').fetchdf()
    cover=known.groupby('cohort').agg(accounts=('chooser','size'),returned=('returned',lambda x:int(x.fillna(False).sum())),patrons=('patron',lambda x:int(x.fillna(False).sum()))).reset_index()
    cover.to_csv(report/'patron_coverage.csv',index=False)
    first=df[df.period==0].copy();d=design(first)
    latent=pd.DataFrame({'chooser':d['accounts']})
    for family in ['gate','willingness','unrestricted']:
        fit=fits[family];_,extra=hmm.predict(fit,d)
        layout=hmm.Layout(d['X'].shape[1],d['H'].shape[1],fit['J'],family,d['cost_indices'])
        z=layout.decode(np.array(fit['parameters']));q=extra['train_posterior'];t=q.sum(axis=2)
        for name,value in [('ell',t@z['ell']),('gamma',t@z['gamma']),('state1',q[:,:,1].sum(axis=1))]:latent[family+'_'+name]=value
    frame=known.merge(latent,on='chooser',how='inner')
    frame=frame[frame.returned.fillna(False)&frame.patron.notna()].copy()
    train=frame.cohort.to_numpy()=='development';test=~train;y=frame.patron.to_numpy(float)
    if train.sum()<200 or test.sum()<200 or y[train].sum()<30 or y[test].sum()<10:
        status=dict(status='INSUFFICIENT_PATRON_PREDICTION_SUPPORT',training_accounts=int(train.sum()),evaluation_accounts=int(test.sum()),training_patrons=int(y[train].sum()),evaluation_patrons=int(y[test].sum()))
        atomic_json(report/'PATRON_STATUS.json',status);return status
    features={k:np.log1p(frame[k].to_numpy(float)) for k in ['n_train','g_train','f_train','l_train','fg_train','lg_train']}
    features['rating']=frame.rating_train.fillna(1600).to_numpy(float)
    preds={};results=[]
    for model in ['observed_history','history_plus_gate','history_plus_willingness','history_plus_unrestricted']:
        cols=list(features.values())
        if model!='observed_history':
            family=model.removeprefix('history_plus_')
            cols += [frame[family+'_'+k].to_numpy(float) for k in ('ell','gamma','state1')]
        X=np.column_stack(cols);mean=X[train].mean(axis=0);sd=X[train].std(axis=0);sd[sd<1e-8]=1
        X=np.c_[np.ones(len(X)),(X-mean)/sd]
        fit=fit_logit(X[train],y[train]);p=np.clip(expit(X[test]@fit.x),1e-12,1-1e-12);preds[model]=p
        positive=y[test].sum();negative=test.sum()-positive
        auc=float((rankdata(p)[y[test]==1].sum()-positive*(positive+1)/2)/(positive*negative))
        results.append(dict(model=model,accounts=int(test.sum()),patrons=int(positive),converged=bool(fit.success),
          log_loss=float(losses(y[test],p).mean()),brier=float(np.mean((y[test]-p)**2)),AUC=auc))
    gains=[]
    for model,p in preds.items():
        if model=='observed_history':continue
        delta=losses(y[test],preds['observed_history'])-losses(y[test],p)
        gains.append(dict(model=model,log_score_gain=float(delta.mean()),conditional_SE=float(delta.std(ddof=1)/np.sqrt(len(delta))),
          inference='Conditional on population/model fits and selected returned-profile sample; no acquisition weights or causal adoption interpretation'))
    csv_write(report/'patron_prediction.csv',results);csv_write(report/'patron_incremental_gains.csv',gains)
    status=dict(status='SELECTED_SNAPSHOT_PREDICTION_COMPLETE',
      snapshot='Certified current profile snapshot; status at each game is unknown',
      scope='Returned profiles in the selected acquisition sample, conditional on usable first-year histories',
      labels='Same-platform external prediction, not an identified moral trait',population_weighting=False)
    atomic_json(report/'PATRON_STATUS.json',status);return status
