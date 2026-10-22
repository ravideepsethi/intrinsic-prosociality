"""Support first; cost association and descriptive surface follow the gates."""
from common import *
from design import controls,descriptive_design
from stats import demean,residualize,lpm,lpm_stream

def corr(a,b):
    return float(np.corrcoef(a,b)[0,1]) if np.std(a)>1e-12 and np.std(b)>1e-12 else np.nan

def cost_support(d):
    if not len(d):return dict(status='EMPTY',two_stakes=False)
    ct=d.groupby('chooser').chooser.transform('size');d=d[ct>=2].copy()
    if not len(d):return dict(status='NO_REPEATED_CHOOSERS',two_stakes=False)
    Z,_=controls(d);ids=d.chooser.to_numpy();K=d[['ki','kj']].to_numpy()
    R=residualize(K,Z,ids);raw=corr(K[:,0],K[:,1]);within=corr(*demean(K,ids).T);partial=corr(*R.T)
    x=(d.opp_rd.to_numpy()-45)/100
    ZZ=np.column_stack([Z,x,x*x,x*x*x]);RR=residualize(K,ZZ,ids)
    own=residualize(K[:,0],np.column_stack([ZZ,K[:,1]]),ids)
    opp=residualize(K[:,1],np.column_stack([ZZ,K[:,0]]),ids)
    rdwithin=float(np.std(demean(d.rd.to_numpy(),ids)))
    adequate=d.chooser.nunique()>=100 and d.y.sum()>=100
    two=bool(adequate and np.isfinite(partial) and max(abs(raw),abs(within),abs(partial))<=.9
             and np.std(own)>=.01 and np.std(opp)>=.01 and rdwithin>.01)
    w=demean(K[:,0],ids)**2;gr=d.groupby('chooser').y.transform('sum').to_numpy()
    sd=np.std(R,axis=0)
    return dict(status='TWO_CONDITIONAL_COEFFICIENTS_SUPPORTED' if two else 'OPPONENT_RD_BUNDLE_ONLY',
      two_stakes=two,n=len(d),grants=int(d.y.sum()),accounts=d.chooser.nunique(),raw_correlation=raw,
      within_chooser_correlation=within,controlled_correlation=partial,own_rd_within_sd=rdwithin,
      ki_within_sd=float(np.std(demean(K[:,0],ids))),ki_controlled_sd=sd[0],kj_controlled_sd=sd[1],
      ki_sd_after_other_stake_controls_and_opp_rd_cubic=float(np.std(own)),
      kj_sd_after_other_stake_controls_and_opp_rd_cubic=float(np.std(opp)),
      ki_q25=float(d.ki.quantile(.25)),ki_median=float(d.ki.median()),ki_q75=float(d.ki.quantile(.75)),
      own_rd_floor_share=float((d.rd<45.01).mean()),
      opponent_rd_cubic_partial_variance_share=float(1-np.var(RR[:,0])/np.var(R[:,0])) if np.var(R[:,0])>1e-20 else None,
      variance_share_label='Partial projection onto an opponent-RD cubic, not an assigned/randomized variance share',
      never_granter_simple_within_weight_share=float(w[gr==0].sum()/w.sum()) if w.sum()>0 else None,
      weight_label='Diagnostic simple within-chooser premium weight, not adjusted-model decomposition',
      interpretation='Support gate only. Separate coefficients remain conditional associations, not exogenous cost effects.')

def make_support(d,report,label):
    rows=[]
    for month,p in d.groupby('month'):
        rows.append(dict(sample=label,month=month,n=len(p),grants=int(p.y.sum()),choosers=p.chooser.nunique(),
          base_rate_pp=100*p.y.mean(),own_rd_floor_share=(p.rd<45.01).mean(),
          ki_p10=p.ki.quantile(.1),ki_median=p.ki.median(),ki_p90=p.ki.quantile(.9),
          opponent_RD_above_110_share=(p.opp_rd>110).mean(),opponent_RD_at_least_200_share=(p.opp_rd>=200).mean()))
    table(rows,Path(report)/(label+'_monthly_counts.parquet'))
    c=[]
    for name,mask in [('exact_tie',d.g.eq(0)),('near_tie_25',d.g.abs()<=25)]:
        r=cost_support(d[mask]);r.update(sample=label,window=name);c.append(r)
    write(Path(report)/(label+'_support.json'),c)
    table(c,Path(report)/(label+'_support.parquet'));return c

def estimate_cost(d,support,report,label):
    results=[]
    for gate in support:
        mask=d.g.eq(0) if gate['window']=='exact_tie' else d.g.abs()<=25
        x=d[mask].copy()
        if not len(x) or x.chooser.nunique()<100 or x.y.sum()<100:
            results.append(dict(sample=label,window=gate['window'],status='INSUFFICIENT_COST_SUPPORT'));continue
        Z,zn=controls(x)
        if gate['window']!='exact_tie':Z=np.column_stack([Z,x.g/100,(x.g/100)**2])
        if gate['two_stakes']:
            X=np.column_stack([x.ki,x.kj,Z]);names=['own_premium','opponent_stake'];spans=[x.ki.quantile(.75)-x.ki.quantile(.25),x.kj.quantile(.75)-x.kj.quantile(.25)]
        else:
            X=np.column_stack([(x.opp_rd-45)/100,Z]);names=['opponent_RD_bundle_per_100_RD'];spans=[(x.opp_rd.quantile(.75)-x.opp_rd.quantile(.25))/100]
        fit=lpm(X,100*x.y.to_numpy(float),x.chooser.to_numpy())
        for j,name in enumerate(names):
            if fit['status']!='ESTIMATED':continue
            identified=fit['identified'][j];se=np.sqrt(max(0,fit['cov'][j,j])) if identified else np.nan
            b=fit['beta'][j]
            results.append(dict(sample=label,window=gate['window'],status='CONDITIONAL_ASSOCIATION' if identified else 'NOT_IDENTIFIED',
              term=name,beta_pp=b,se_pp=se,lo_pp=b-1.96*se,hi_pp=b+1.96*se,
              observed_iqr=spans[j],iqr_effect_pp=b*spans[j],iqr_lo_pp=(b-1.96*se)*spans[j],iqr_hi_pp=(b+1.96*se)*spans[j],
              local_elasticity_at_median=(b*x.ki.median()/(100*x.y.mean())) if name=='own_premium' and x.y.mean()>0 else None,
              n=fit['n'],grants=fit['grants'],choosers=fit['accounts'],
              own_cost_bound=False,interpretation='Bundle coefficient cannot bound own-cost sensitivity without restrictions on other channels' if not gate['two_stakes'] else 'Conditional slope on observed premium range; no doubling extrapolation'))
    table(results,Path(report)/(label+'_cost_or_bundle.parquet'))

def surface(d,kcuts,report,label):
    def builder(x):
        X,n,_=descriptive_design(x,kcuts);return X,n
    fit,names=lpm_stream(d,builder)
    if fit['status']!='ESTIMATED':write(Path(report)/(label+'_surface_status.json'),fit);return
    _,_,kg=descriptive_design(d.iloc[:1],kcuts)
    k=2*d.ki.to_numpy();groups=np.where(d.rd.to_numpy()<45.01,0,1+np.searchsorted(kcuts,k,side='right'))
    support=[];rows=[]
    for group in range(5):
        part=d[groups==group];sides=part.assign(side=np.where(part.g<-25,-1,np.where(part.g>=25,1,0)))
        both=sides[sides.side!=0].groupby('chooser').side.nunique().eq(2).sum()
        support.append(dict(sample=label,kgroup=group,n=len(part),grants=int(part.y.sum()),choosers=part.chooser.nunique(),
             both_sides_choosers=int(both),mean_abs_rg_near_100=part.loc[part.g.between(-125,-75,inclusive='left')|part.g.between(75,125,inclusive='left'),'rg'].abs().mean(),
             mean_ki=part.ki.mean(),mean_K=(2*part.ki).mean(),group_label='Own-RD floor' if group==0 else 'Non-floor K quartile '+str(group)))
        for gap in range(-550,551,50):
            if gap==0:continue
            name=f'gap_{gap}_k{group}';j=names.index(name);b=fit['beta'][j]
            se=np.sqrt(max(0,fit['cov'][j,j])) if fit['identified'][j] else np.nan
            rows.append(dict(sample=label,kgroup=group,gap=gap,coefficient_pp=b if fit['identified'][j] else np.nan,
                             se_pp=se,lo_pp=b-1.96*se,hi_pp=b+1.96*se,identified=bool(fit['identified'][j])))
    contrasts=[]
    for group in range(5):
        a=names.index(f'gap_-100_k{group}');b=names.index(f'gap_100_k{group}')
        valid=fit['identified'][a] and fit['identified'][b]
        var=fit['cov'][a,a]+fit['cov'][b,b]-2*fit['cov'][a,b]
        contrasts.append(dict(sample=label,kgroup=group,n=fit['n'],grants=fit['grants'],choosers=fit['accounts'],L_pp=fit['beta'][a] if valid else None,S_pp=fit['beta'][b] if valid else None,
          G_pp=fit['beta'][b]-fit['beta'][a] if valid else None,G_se_pp=np.sqrt(max(0,var)) if valid else None,
          base_rate_pp=100*d.y.mean(),G_share_of_base=(fit['beta'][b]-fit['beta'][a])/(100*d.y.mean()) if valid and d.y.mean()>0 else None))
    per=d.assign(kg=groups).groupby('chooser').kg.nunique()
    write(Path(report)/(label+'_surface_status.json'),dict(status='DESCRIPTIVE_WITHIN_CHOOSER_SURFACE',
          n=fit['n'],grants=fit['grants'],choosers=fit['accounts'],choosers_in_multiple_K_groups=int((per>=2).sum()),
          warning='K-group composition and chooser-specific slope heterogeneity remain; pp scaling is not an index-scale mechanism test.'))
    table(rows,Path(report)/(label+'_surface.parquet'));table(support,Path(report)/(label+'_K_groups.parquet'))
    table(contrasts,Path(report)/(label+'_L_S_G.parquet'))

def mechanical_curves(d,kcuts,report):
    """All primary rows standardized to the same displayed gaps; y is unused."""
    if not len(d):return
    k=2*d.ki.to_numpy();kg=np.where(d.rd.to_numpy()<45.01,0,1+np.searchsorted(kcuts,k,side='right'))
    rows=[];states=(d.rating.to_numpy(),d.rd.to_numpy(),d.opp_rd.to_numpy())
    for gap in (-550,-300,-200,-100,-50,0,50,100,200,300,550):
        r,rd,oprd=states;_,K,rg,_=payoff(r,r+gap,rd,oprd);_,Ko,_,_=payoff(r+gap,r,oprd,rd)
        for group in range(5):
            m=kg==group
            if not m.any():continue
            rows.append(dict(gap=gap,kgroup=group,n=int(m.sum()),mean_ki=float(np.mean(K[m]/2)),
                 ki_p10=np.quantile(K[m]/2,.1),ki_median=np.median(K[m]/2),ki_p90=np.quantile(K[m]/2,.9),
                 mean_kj=float(np.mean(Ko[m]/2)),mean_rg=float(np.mean(rg[m])),mean_abs_rg=float(np.mean(abs(rg[m]))),
                 scope='All primary regular roughly-equal rows, fixed actual RDs, counterfactual displayed gap'))
    table(rows,Path(report)/'mechanical_premium_gap_curves.parquet')
