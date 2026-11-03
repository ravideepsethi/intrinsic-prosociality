"""Original equal-chooser estimator on fresh material-restricted sufficient statistics."""
from util import *
from sources import producers
import numpy as np
import pandas as pd

def analyze(count_file,out):
    _,_,_,_,s=producers();frame=pd.read_parquet(count_file)
    n,both,w,balanced,d=s.inputs(frame)
    require(int(both.sum())>1,'Too few state-varying choosers')
    weights=np.column_stack((w[both],balanced[both],np.ones(int(both.sum()))))
    models,pairs,V=s.estimate(d,weights)
    require(np.isclose(models.iloc[2].estimate_pp,100*d.mean(),atol=1e-10,rtol=0),'Equal-chooser mean identity failed')
    require(np.isclose(models.iloc[2].se_pp,100*d.std(ddof=1)/np.sqrt(len(d)),atol=1e-10,rtol=0),'Equal-chooser SE identity failed')
    cross=frame.a.to_numpy(float)*frame.l.to_numpy()-frame.b.to_numpy(float)*frame.f.to_numpy()
    cross=np.divide(cross,n,out=np.zeros(len(n)),where=n>0)[both]
    for j,aw in enumerate((np.ones(len(d)),1/n[both],1/w[both])):
        require(abs(100*(aw@cross)/(aw@w[both])-models.iloc[j].estimate_pp)<1e-9,'Weighted within-chooser identity failed')
    table(out/'tab_app_equalweights.csv',models);table(out/'equalweight_paired_differences.csv',pairs)
    cov=pd.DataFrame(V*10000,columns=s.LABELS);cov.insert(0,'estimator',s.LABELS);table(out/'equalweight_covariance_pp2.csv',cov)
    table(out/'granting_rates.csv',s.granting_rates(frame))
    all_weights=np.column_stack((w,balanced,both.astype(float)))
    deciles=[];tops=[]
    for label,mask,counts in [('all_pool_choosers',np.ones(len(n),bool),frame.n.to_numpy()),('all_binary_comparison_choosers',n>0,n),('state_varying_choosers',both,n)]:
        dec,top=s.activity_distribution(counts[mask],all_weights[mask],label);deciles.append(dec);tops.append(top)
    table(out/'activity_decile_weight_shares.csv',pd.concat(deciles,ignore_index=True))
    table(out/'activity_top_shares.csv',pd.concat(tops,ignore_index=True))
    est,pair,support,definition=s.activity_terciles(n[both],d,weights)
    table(out/'activity_tercile_estimates.csv',est);table(out/'activity_tercile_differences.csv',pair);table(out/'activity_tercile_support.csv',support)
    save(out/'ACTIVITY_TERCILES.json',definition)
    summary=dict(choosers=len(frame),state_varying_choosers=int(both.sum()),nongranters_retained=int(((frame.a+frame.b).to_numpy()[both]==0).sum()),
          state_varying_opportunities=int(n[both].sum()),weighting=['F*L/(F+L)','F*L/(F+L)^2','1'],
          covariance='Original joint chooser sandwich G/(G-1), G=state-varying accounts. Paired comparisons use the joint covariance; no outcome-based selection.')
    save(out/'EQUALWEIGHT_METHOD.json',summary)
    return summary
