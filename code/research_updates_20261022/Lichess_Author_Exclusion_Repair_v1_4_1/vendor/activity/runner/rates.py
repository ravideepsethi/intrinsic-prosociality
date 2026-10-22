"""State levels and proportional contrasts on a fixed both-state chooser sample."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

METHODS=('original_FE','inverse_count_FE','equal_chooser','pooled_opportunities')
Z=1.959963984540054


def linear_summary(means,covariance,gradient):
    gradient=np.asarray(gradient,dtype=float)
    value=float(gradient@means)
    se=math.sqrt(max(0,float(gradient@covariance@gradient))) if covariance is not None else None
    return value,se


def normal_interval(value,se,multiplier=1):
    return dict(estimate=multiplier*value,se=multiplier*se if se is not None else None,
                ci_low=multiplier*(value-Z*se) if se is not None else None,
                ci_high=multiplier*(value+Z*se) if se is not None else None)


def ratio_summary(fair,worse,covariance):
    # Ratios of group rates retain every zero-outcome account. No pseudocounts
    # and no averages of undefined individual ratios.
    if worse<=0:
        status='undefined_both_state_rates_zero' if fair<=0 else 'undefined_zero_worse_rate'
        return dict(risk_ratio=None,relative_increase_pct=None,log_risk_ratio=None,log_rr_se=None,
                    risk_ratio_ci_low=None,risk_ratio_ci_high=None,ratio_status=status)
    if fair<=0:
        return dict(risk_ratio=0.0,relative_increase_pct=-100.0,log_risk_ratio=None,log_rr_se=None,
                    risk_ratio_ci_low=None,risk_ratio_ci_high=None,ratio_status='zero_competitive_rate_log_inference_unavailable')
    value=math.log(fair)-math.log(worse)
    gradient=np.array([1/fair,-1/worse,0.0])
    se=math.sqrt(max(0,float(gradient@covariance@gradient))) if covariance is not None else None
    rr=fair/worse
    return dict(risk_ratio=float(rr),relative_increase_pct=100*float(rr-1),log_risk_ratio=value,
                log_rr_se=se,risk_ratio_ci_low=math.exp(value-Z*se) if se is not None else None,
                risk_ratio_ci_high=math.exp(value+Z*se) if se is not None else None,
                ratio_status='ok' if covariance is not None else 'point_estimate_only_one_chooser')


def group_rates(frame,scope):
    f=frame.f.to_numpy(dtype=float);l=frame.l.to_numpy(dtype=float)
    a=frame.a.to_numpy(dtype=float);b=frame.b.to_numpy(dtype=float)
    if len(f)==0 or np.any(f<=0) or np.any(l<=0):raise ValueError('Rates require the fixed both-state sample')
    n=f+l;w=f*l/n;G=len(f)
    values=np.column_stack((a/f,b/l,(a+b)/n))
    rows=[];covariances=[]
    for method in METHODS:
        if method=='pooled_opportunities':
            counts=np.column_stack((f,l,n));grants=np.column_stack((a,b,a+b))
            means=grants.sum(axis=0)/counts.sum(axis=0)
            influence=(grants-counts*means)/counts.sum(axis=0)
            note='State-specific opportunity weights; difference is pooled, not the chooser-FE slope.'
        else:
            analytic={'original_FE':w,'inverse_count_FE':w/n,'equal_chooser':np.ones(G)}[method]
            normalized=analytic/analytic.sum()
            means=normalized@values
            influence=normalized[:,None]*(values-means)
            note='Identical chooser weights in both states; state-rate difference equals the corresponding within coefficient.'
        cov=G/(G-1)*(influence.T@influence) if G>1 else None
        row=dict(scope=scope,weighting=method,choosers=G,competitive_opportunities=int(f.sum()),
                 worse_opportunities=int(l.sum()),binary_opportunities=int(n.sum()),
                 competitive_grants=int(a.sum()),worse_grants=int(b.sum()),
                 observed_nongranters_retained=int(((a+b)==0).sum()),
                 min_binary_opportunities=int(n.min()),max_binary_opportunities=int(n.max()),
                 weighting_note=note)
        definitions=[('competitive_rate',[1,0,0]),('worse_rate',[0,1,0]),
                     ('overall_binary_rate',[0,0,1]),('balanced_50_50_rate',[.5,.5,0]),('gap',[1,-1,0])]
        for label,gradient in definitions:
            point,se=linear_summary(means,cov,gradient)
            result=normal_interval(point,se,100)
            suffix='pp' if label=='gap' else 'pct'
            row[label+'_'+suffix]=result['estimate']
            row[label+'_se_'+suffix]=result['se']
            row[label+'_ci_low_'+suffix]=result['ci_low']
            row[label+'_ci_high_'+suffix]=result['ci_high']
        row.update(ratio_summary(float(means[0]),float(means[1]),cov))
        rows.append(row)
        if cov is not None:
            for j,name in enumerate(('competitive','worse','overall_binary')):
                covariances.append(dict(scope=scope,weighting=method,rate=name,
                    **{other+'_cov_pct2':float(cov[j,k]*10000) for k,other in enumerate(('competitive','worse','overall_binary'))}))
    return pd.DataFrame(rows),pd.DataFrame(covariances)


def compare_activity(table):
    rows=[]
    for method in METHODS:
        selected=table[table.weighting==method].set_index('scope')
        for high,low in (('medium','light'),('heavy','light'),('heavy','medium')):
            if high not in selected.index or low not in selected.index:continue
            h=selected.loc[high];l=selected.loc[low]
            row=dict(weighting=method,comparison=high+'_versus_'+low,
                     high_group_choosers=int(h.choosers),low_group_choosers=int(l.choosers))
            gap=float(h.gap_pp-l.gap_pp)
            if pd.notna(h.gap_se_pp) and pd.notna(l.gap_se_pp):
                se=math.hypot(float(h.gap_se_pp),float(l.gap_se_pp))
            else:se=None
            row.update(absolute_gap_difference_pp=gap,absolute_difference_se_pp=se,
                       absolute_difference_ci_low_pp=gap-Z*se if se is not None else None,
                       absolute_difference_ci_high_pp=gap+Z*se if se is not None else None)
            if h.ratio_status=='ok' and l.ratio_status=='ok':
                log_ratio=float(h.log_risk_ratio-l.log_risk_ratio)
                ratio_se=math.hypot(float(h.log_rr_se),float(l.log_rr_se))
                row.update(ratio_of_risk_ratios=math.exp(log_ratio),log_ratio_of_risk_ratios=log_ratio,
                           log_ratio_se=ratio_se,ratio_ci_low=math.exp(log_ratio-Z*ratio_se),
                           ratio_ci_high=math.exp(log_ratio+Z*ratio_se),
                           p_normal=math.erfc(abs(log_ratio/ratio_se)/math.sqrt(2)) if ratio_se>0 else (1.0 if log_ratio==0 else 0.0),
                           ratio_comparison_status='ok')
            else:
                row.update(ratio_of_risk_ratios=None,log_ratio_of_risk_ratios=None,log_ratio_se=None,
                           ratio_ci_low=None,ratio_ci_high=None,p_normal=None,
                           ratio_comparison_status='unavailable_state_rate_or_cluster_support')
            rows.append(row)
    return pd.DataFrame(rows)


def analyze(frame,cutoffs=(6,16)):
    both=(frame.f>0)&(frame.l>0)
    panel=frame.loc[both]
    n=(panel.f+panel.l).to_numpy()
    groups=np.searchsorted(np.asarray(cutoffs),n,side='left')
    rates=[];covariance=[]
    for name,mask in [('all',np.ones(len(panel),dtype=bool))]+[(name,groups==j) for j,name in enumerate(('light','medium','heavy'))]:
        if not mask.any():continue
        table,cov=group_rates(panel.loc[mask],name)
        rates.append(table);covariance.append(cov)
    combined=pd.concat(rates,ignore_index=True)
    return combined,pd.concat(covariance,ignore_index=True),compare_activity(combined)
