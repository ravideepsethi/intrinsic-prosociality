"""Equal-chooser state rates with rating/time-control direct standardization."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .rates import Z, ratio_summary

GROUPS=('light','medium','heavy')
METHODS=('unadjusted_common_support','rating_standardized','rating_time_control_standardized')
RATE_NAMES=('competitive','worse','overall_binary')
RATING_BREAKS=tuple(range(1000,2601,200))
MIN_CELL_CHOOSERS=2


def rating_bands(rating):
    r=np.asarray(rating,dtype=float)
    labels=['below_1000']+[f'{a}_to_lt{b}' for a,b in zip(RATING_BREAKS[:-1],RATING_BREAKS[1:])]+['2600_plus']
    out=np.array(labels,dtype=object)[np.searchsorted(RATING_BREAKS,r,side='right')]
    out[~np.isfinite(r)|(r<=0)]='missing_rating'
    return out


def activity_labels(n):
    return np.asarray(GROUPS,dtype=object)[np.searchsorted([6,16],np.asarray(n),side='left')]


def finite_correlation(x,y,rank=False):
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    mask=np.isfinite(x)&np.isfinite(y);x=x[mask];y=y[mask]
    if len(x)<2 or np.ptp(x)==0 or np.ptp(y)==0:return None
    if rank:
        x=pd.Series(x).rank(method='average').to_numpy()
        y=pd.Series(y).rank(method='average').to_numpy()
    return float(np.corrcoef(x,y)[0,1])


def descriptions(frame):
    rows=[]
    for scope in ('all',)+GROUPS:
        f=frame if scope=='all' else frame.loc[frame.activity==scope]
        r=f.mean_rating.to_numpy(float);valid=np.isfinite(r)&(r>0);rv=r[valid]
        n=f.n_binary.to_numpy(float)
        rows.append(dict(scope=scope,choosers=len(f),binary_opportunities=int(n.sum()),
            observed_nongranters=int(((f.a+f.b)==0).sum()),
            choosers_with_rating=int(valid.sum()),choosers_missing_rating=int((~valid).sum()),
            rating_mean=float(rv.mean()) if len(rv) else None,
            rating_median=float(np.median(rv)) if len(rv) else None,
            rating_p10=float(np.quantile(rv,.1)) if len(rv) else None,
            rating_p90=float(np.quantile(rv,.9)) if len(rv) else None,
            mean_binary_opportunities=float(n.mean()),median_binary_opportunities=float(np.median(n)),
            mean_modal_time_control_share=float(f.modal_opportunity_share.mean()),
            choosers_using_multiple_time_controls=int((f.distinct_time_controls>1).sum()),
            choosers_with_modal_tie=int((f.modal_ties>1).sum()),
            mean_rating_coverage_in_modal_time_control=float((f.modal_rating_n/f.modal_opportunities).mean()),
            pearson_rating_binary_count=finite_correlation(r,n),
            spearman_rating_binary_count=finite_correlation(r,n,rank=True),
            pearson_rating_log_binary_count=finite_correlation(r,np.log(n))))
    rd=frame.groupby(['activity','rating_band'],sort=True).size().rename('choosers').reset_index()
    rd['share_within_activity']=rd.choosers/rd.groupby('activity').choosers.transform('sum')
    tc=frame.groupby(['activity','modal_speed','modal_time_control'],sort=True).size().rename('choosers').reset_index()
    tc['share_within_activity']=tc.choosers/tc.groupby('activity').choosers.transform('sum')
    return pd.DataFrame(rows),rd,tc


def summarize_rates(means,covariance):
    means=np.asarray(means,dtype=float)
    row={}
    definitions=[('competitive_rate',[1,0,0]),('worse_rate',[0,1,0]),
        ('overall_binary_rate',[0,0,1]),('balanced_50_50_rate',[.5,.5,0]),('gap',[1,-1,0])]
    for name,gradient in definitions:
        d=np.array(gradient,dtype=float);value=100*float(d@means)
        se=100*math.sqrt(max(0,float(d@covariance@d))) if covariance is not None else None
        suffix='pp' if name=='gap' else 'pct'
        row[name+'_'+suffix]=value
        row[name+'_se_'+suffix]=se
        row[name+'_ci_low_'+suffix]=value-Z*se if se is not None else None
        row[name+'_ci_high_'+suffix]=value+Z*se if se is not None else None
    row.update(ratio_summary(float(means[0]),float(means[1]),covariance))
    return row


def cell_moments(frame):
    """No outcome-based cell selection; retain zeros in every sum and count."""
    v=np.column_stack((frame.a/frame.f,frame.b/frame.l,(frame.a+frame.b)/frame.n_binary))
    moments=frame[['cell','activity','n_binary','a','b']].copy()
    moments['nongranter']=((frame.a+frame.b)==0).astype('int64')
    for j in range(3):moments['v'+str(j)]=v[:,j]
    for j in range(3):
        for k in range(j,3):moments[f'v{j}{k}']=v[:,j]*v[:,k]
    grouped=moments.groupby(['cell','activity'],sort=True)
    sums=grouped.sum(numeric_only=True)
    sums['choosers']=grouped.size()
    result={}
    for (cell,group),r in sums.iterrows():
        n=int(r.choosers);mean=np.array([r['v'+str(j)] for j in range(3)])/n
        cov=None
        if n>1:
            product=np.array([[r[f'v{min(j,k)}{max(j,k)}'] for k in range(3)] for j in range(3)])
            cov=(product-n*np.outer(mean,mean))/(n*(n-1))
            cov=(cov+cov.T)/2
            if np.linalg.eigvalsh(cov).min() < -1e-12:
                raise RuntimeError('Non-positive cell covariance beyond numerical tolerance')
        result[(int(cell),group)]=dict(n=n,mean=mean,cov=cov,
            nongranters=int(r.nongranter),opportunities=int(r.n_binary),grants=int(r.a+r.b))
    return result


def group_estimators(cells,stats,cell_info):
    """Joint covariance of raw, rating-only, and rating+TC estimates.

    Cell counts and the empirical target mix are held fixed for inference.
    Each independent observation is a chooser's vector of two state rates.
    """
    total=np.array([sum(stats[(s,g)]['n'] for g in GROUPS) for s in cells],dtype=float)
    q=total/total.sum()
    ratings=[cell_info.loc[s,'rating_band'] for s in cells]
    target_rating={r:float(q[np.array(ratings)==r].sum()) for r in set(ratings)}
    rates=[];cov_rows=[];results={};weight_rows=[]
    for group in GROUPS:
        counts=np.array([stats[(s,group)]['n'] for s in cells],dtype=float)
        group_rating={r:float(counts[np.array(ratings)==r].sum()) for r in set(ratings)}
        weights=np.vstack((counts/counts.sum(),
            np.array([target_rating[r]*n/group_rating[r] for r,n in zip(ratings,counts)]),q))
        if not np.allclose(weights.sum(axis=1),1,atol=1e-12):
            raise RuntimeError('Standardization weights do not sum to one')
        means=np.array([stats[(s,group)]['mean'] for s in cells])
        covariance=np.zeros((9,9))
        for j,s in enumerate(cells):
            covariance+=np.kron(np.outer(weights[:,j],weights[:,j]),stats[(s,group)]['cov'])
        estimate=(weights@means).reshape(-1)
        results[group]=(estimate,covariance)
        for j,method in enumerate(METHODS):
            row=dict(scope=group,method=method,choosers=int(counts.sum()),
                observed_nongranters=sum(stats[(s,group)]['nongranters'] for s in cells),
                binary_opportunities=sum(stats[(s,group)]['opportunities'] for s in cells),
                common_cells=len(cells),
                effective_choosers=float(1/np.sum(weights[j]**2/counts)),
                inference='chooser-cluster; conditional on joint cell counts and target mix')
            row.update(summarize_rates(estimate[j*3:j*3+3],covariance[j*3:j*3+3,j*3:j*3+3]))
            rates.append(row)
            for k,s in enumerate(cells):
                weight_rows.append(dict(scope=group,method=method,cell=s,
                    chooser_count=int(counts[k]),cell_weight=float(weights[j,k]),
                    per_chooser_weight=float(weights[j,k]/counts[k])))
        for j in range(9):
            for k in range(9):
                cov_rows.append(dict(scope=group,row_method=METHODS[j//3],row_rate=RATE_NAMES[j%3],
                    column_method=METHODS[k//3],column_rate=RATE_NAMES[k%3],
                    covariance_pct2=10000*float(covariance[j,k])))
    targets=cell_info.loc[cells].reset_index().copy()
    targets['target_choosers']=total.astype('int64')
    targets['target_share']=q
    return pd.DataFrame(rates),pd.DataFrame(cov_rows),results,pd.DataFrame(weight_rows),targets


def contrast(hi,lo,method_index):
    h,vh=hi;l,vl=lo
    j=3*method_index
    d=np.zeros(9);d[j:j+2]=[1,-1]
    gap=float(d@(h-l));se=math.sqrt(max(0,float(d@(vh+vl)@d)))
    row=dict(absolute_gap_difference_pp=100*gap,absolute_difference_se_pp=100*se,
        absolute_difference_ci_low_pp=100*(gap-Z*se),absolute_difference_ci_high_pp=100*(gap+Z*se))
    if min(h[j],h[j+1],l[j],l[j+1])<=0:
        row.update(ratio_of_risk_ratios=None,log_ratio_of_risk_ratios=None,log_ratio_se=None,
            ratio_ci_low=None,ratio_ci_high=None,ratio_comparison_status='unavailable_zero_state_rate')
        return row,None,None
    gh=np.zeros(9);gl=np.zeros(9)
    gh[j:j+2]=[1/h[j],-1/h[j+1]];gl[j:j+2]=[-1/l[j],1/l[j+1]]
    value=math.log(h[j]/h[j+1])-math.log(l[j]/l[j+1])
    se=math.sqrt(max(0,float(gh@vh@gh+gl@vl@gl)))
    row.update(ratio_of_risk_ratios=math.exp(value),log_ratio_of_risk_ratios=value,log_ratio_se=se,
        ratio_ci_low=math.exp(value-Z*se),ratio_ci_high=math.exp(value+Z*se),ratio_comparison_status='ok')
    return row,gh,gl


def comparisons(results):
    rows=[];changes=[]
    for high,low in [('medium','light'),('heavy','light'),('heavy','medium')]:
        name=high+'_versus_'+low
        baseline,bh,bl=contrast(results[high],results[low],0)
        for j,method in enumerate(METHODS):
            r,gh,gl=contrast(results[high],results[low],j)
            rows.append(dict(method=method,comparison=name,**r))
            if j==0:continue
            h,vh=results[high];l,vl=results[low]
            d=np.zeros(9);d[j*3:j*3+2]=[1,-1];d[0:2]=[-1,1]
            gap=float(d@(h-l));se=math.sqrt(max(0,float(d@(vh+vl)@d)))
            item=dict(method=method,comparison=name,
                gap_difference_change_pp=100*gap,gap_difference_change_se_pp=100*se,
                gap_difference_change_ci_low_pp=100*(gap-Z*se),gap_difference_change_ci_high_pp=100*(gap+Z*se),
                log_ror_change=None,log_ror_change_se=None,adjusted_to_unadjusted_ror=None,
                adjusted_to_unadjusted_ror_ci_low=None,adjusted_to_unadjusted_ror_ci_high=None)
            if gh is not None and bh is not None:
                dg_h=gh-bh;dg_l=gl-bl
                change=r['log_ratio_of_risk_ratios']-baseline['log_ratio_of_risk_ratios']
                se=math.sqrt(max(0,float(dg_h@vh@dg_h+dg_l@vl@dg_l)))
                item.update(log_ror_change=change,log_ror_change_se=se,
                    adjusted_to_unadjusted_ror=math.exp(change),
                    adjusted_to_unadjusted_ror_ci_low=math.exp(change-Z*se),
                    adjusted_to_unadjusted_ror_ci_high=math.exp(change+Z*se))
            changes.append(item)
    return pd.DataFrame(rows),pd.DataFrame(changes)


def analyze_adjustment(joined):
    frame=joined.copy()
    if frame.chooser.duplicated().any() or (frame.f<=0).any() or (frame.l<=0).any():
        raise ValueError('Adjustment requires unique choosers observed in both states')
    frame['activity']=activity_labels(frame.n_binary)
    frame['rating_band']=rating_bands(frame.mean_rating)
    keys=['rating_band','modal_speed','modal_time_control']
    frame['cell']=frame.groupby(keys,sort=True,dropna=False).ngroup()
    cell_info=frame[['cell']+keys].drop_duplicates().set_index('cell').sort_index()
    if len(cell_info)!=frame.cell.nunique():raise RuntimeError('Ambiguous standardization cells')
    descr,rd,tc=descriptions(frame)
    stats=cell_moments(frame)
    support=[];within=[]
    for s,info in cell_info.iterrows():
        n={g:stats.get((s,g),{}).get('n',0) for g in GROUPS}
        supported=min(n.values())>=MIN_CELL_CHOOSERS
        support.append(dict(cell=int(s),**info.to_dict(),**{g+'_choosers':n[g] for g in GROUPS},
            supported=supported,reason='common_support' if supported else 'fewer_than_two_choosers_in_an_activity_group'))
        for g in GROUPS:
            if not n[g]:continue
            item=stats[(s,g)]
            within.append(dict(cell=int(s),**info.to_dict(),scope=g,choosers=n[g],
                observed_nongranters=item['nongranters'],supported=supported,
                **summarize_rates(item['mean'],item['cov'])))
    support=pd.DataFrame(support)
    cells=support.loc[support.supported,'cell'].tolist()
    if not cells:raise RuntimeError('No joint rating/time-control cells support all three activity groups')
    kept=frame.cell.isin(cells)
    flow=[]
    for scope in ('all',)+GROUPS:
        mask=np.ones(len(frame),dtype=bool) if scope=='all' else (frame.activity==scope).to_numpy()
        full=frame.loc[mask];common=frame.loc[mask&kept.to_numpy()]
        flow.append(dict(scope=scope,full_choosers=len(full),common_support_choosers=len(common),
            excluded_choosers=len(full)-len(common),retained_chooser_pct=100*len(common)/len(full),
            full_binary_opportunities=int(full.n_binary.sum()),common_binary_opportunities=int(common.n_binary.sum()),
            full_observed_nongranters=int(((full.a+full.b)==0).sum()),
            common_observed_nongranters=int(((common.a+common.b)==0).sum()),
            full_missing_rating_choosers=int((full.rating_band=='missing_rating').sum()),
            common_missing_rating_choosers=int((common.rating_band=='missing_rating').sum()),
            outcome_based_exclusions=0))
    rates,cov,results,weights,targets=group_estimators(cells,stats,cell_info)
    contrasts,changes=comparisons(results)
    return {
        'rating_activity_summary.csv':descr,'rating_distribution_by_activity.csv':rd,
        'time_control_composition.csv':tc,'joint_cell_support.csv':support,
        'within_rating_time_control_rates.csv':pd.DataFrame(within),
        'common_support_flow.csv':pd.DataFrame(flow),
        'standardized_state_rates.csv':rates,'standardized_rate_covariance_pct2.csv':cov,
        'standardization_weights.csv':weights,'standardization_target.csv':targets,
        'standardized_activity_comparisons.csv':contrasts,'paired_adjustment_changes.csv':changes,
    }
