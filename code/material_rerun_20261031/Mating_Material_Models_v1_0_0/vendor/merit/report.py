from common import *
from design import points,counterfocal,BIN_LABELS,MATERIAL_LABELS
from estimate import level,estimable,coefficient_cov
from scipy.stats import norm,chi2

def holm(p):
    p=np.asarray(p,float);out=np.full(len(p),np.nan);idx=np.flatnonzero(np.isfinite(p));order=idx[np.argsort(p[idx])]
    if len(order):out[order]=np.minimum(1,np.maximum.accumulate(p[order]*np.arange(len(order),0,-1)))
    return out

def contrast_vector(s,fit,a,b,group=None):
    ca=counterfocal(s,a,fit['ng']);cb=counterfocal(s,b,fit['ng']);d=np.zeros(len(fit['beta']))
    d[:fit['p']]=fit['group_share']@(cb-ca) if group is None else cb[group]-ca[group]
    return d

def comparison(d,fit,V):
    ok=estimable(fit,d)
    if not ok:return dict(estimate_pp=np.nan,se=np.nan,lo=np.nan,hi=np.nan,p_value=np.nan,estimable=False)
    b=float(d@fit['beta']);se=float(np.sqrt(max(0,d@V@d)));pv=2*norm.sf(abs(b/se)) if se>0 else np.nan
    return dict(estimate_pp=b,se=se,lo=b-1.96*se,hi=b+1.96*se,p_value=pv,estimable=True)

def write_report(run,specs,fits,meats,validation):
    run=Path(run);report=run/'report';coeff=[];curves=[];contrasts=[];flows=[];tests=[];matrices={};warnings=[]
    for j,(s,fit,M) in enumerate(zip(specs,fits,meats)):
        require(fit['g']>1,'Insufficient chooser clusters')
        V=coefficient_cov(fit,M);name=s['name'];k=len(fit['beta'])
        flows.append(dict(model=name,N=fit['n'],grants_mean_percent=fit['mean_y'],choosers=fit['g'],
          singletons_retained=fit['singletons'],never_grant_accounts_retained=fit['never'],
          accounts_with_focal_within_variation=fit['vary_g'],rows_in_those_accounts=fit['vary_n'],rank=fit['rank'],columns=k,
          sample=s['sample'],controls=s['controls']))
        matrices[name+'__covariance']=V;matrices[name+'__beta']=fit['beta'];matrices[name+'__augmented_meat']=M
        matrices[name+'__focal_mean']=fit['mean_f'];matrices[name+'__group_share']=fit['group_share']
        for ix,n in enumerate(fit['names']):
            v=np.eye(k)[ix];r=comparison(v,fit,V);coeff.append(dict(model=name,term=n,**r))
        model_points=points(s)
        for pt in model_points:
            m,se,ok=level(fit,M,counterfocal(s,pt,fit['ng']))
            curves.append(dict(model=name,label=pt['label'],cp=pt.get('cp',np.nan),material=pt.get('material',np.nan),
               mate=pt.get('mate',False),adjusted_percent=m,se=se,lo=m-1.96*se,hi=m+1.96*se,estimable=ok))
            if ok and (m<0 or m>100):warnings.append(name+': adjusted rate outside [0,100] at '+pt['label'])
        if s['kind']=='material':pairs=list(zip(model_points[:-1],model_points[1:]));family='adjacent_material_7'
        elif s['kind']=='bins':pairs=list(zip(model_points[:-1],model_points[1:]));family='adjacent_bins_7'
        else:pairs=[(dict(cp=0),dict(cp=100)),(dict(cp=100),dict(cp=300)),(dict(cp=300),dict(cp=500))];family='planned_evaluation_3'
        contrast_mat=[]
        for group in [None]+(list(range(fit['ng'])) if fit['ng']>1 else []):
            rows=[];D=[];influences=[]
            for a,b in pairs:
                delta=contrast_vector(s,fit,a,b,group);D.append(delta)
                al=a.get('label',str(a.get('cp')));bl=b.get('label',str(b.get('cp')))
                result=comparison(delta,fit,V)
                h=np.zeros(1+fit['p']+fit['ng']+k);h[-k:]=fit['inverse']@delta
                if group is None:
                    diff=counterfocal(s,b,fit['ng'])-counterfocal(s,a,fit['ng'])
                    h[1+fit['p']:1+fit['p']+fit['ng']]=diff@fit['beta'][:fit['p']]/fit['n']
                influences.append(h)
                if result['estimable']:
                    se=float(np.sqrt(max(0,fit['g']/(fit['g']-1)*h@M@h)));est=result['estimate_pp']
                    result.update(se=se,lo=est-1.96*se,hi=est+1.96*se,p_value=float(2*norm.sf(abs(est/se))) if se>0 else np.nan)
                rows.append(dict(model=name,group='population_average' if group is None else str(group),family=family,
                     contrast=bl+' minus '+al,**result))
            for row,pv in zip(rows,holm([r['p_value'] for r in rows])):row['holm_p']=pv
            contrasts+=rows;D=np.asarray(D)
            H=np.asarray(influences)
            matrices[name+f'__contrast_cov_g{group}']=fit['g']/(fit['g']-1)*H@M@H.T
            if group is not None:contrast_mat.append(D)
        if len(contrast_mat)>1:
            R=np.vstack([D-contrast_mat[0] for D in contrast_mat[1:]])
            if all(estimable(fit,r) for r in R):
                vr=R@V@R.T;rank=int(np.linalg.matrix_rank(vr,tol=max(np.linalg.norm(vr,2)*1e-9,1e-12)))
                w=float((R@fit['beta'])@np.linalg.pinv(vr,rcond=1e-9)@(R@fit['beta']))
                tests.append(dict(model=name,test='joint equality of specified contrasts across groups',chi_square=w,df=rank,p_value=float(chi2.sf(w,rank)) if rank else np.nan))
    primary_contrasts=[r for r in contrasts if r['model']=='primary_competitive_late']
    require(len(primary_contrasts)==3 and all(r['estimable'] for r in primary_contrasts),'Primary contrasts lack sufficient within-chooser support; no completed-result receipt issued.')
    for name,rows in [('coefficients',coeff),('adjusted_profiles',curves),('planned_contrasts',contrasts),('model_samples',flows),('interaction_tests',tests)]:
        table(report/name,rows)
    npz(report/'model_covariances.npz',**matrices)
    dump(report/'model_definitions.json',specs)
    dump(report/'coefficient_order.json',{s['name']:f['names'] for s,f in zip(specs,fits)})
    dump(report/'warnings.json',dict(warnings=warnings))
    plot(report,pd.DataFrame(curves))
    primary=[r for r in contrasts if r['model']=='primary_competitive_late']
    lines=['# Continuous merit follow-up — completed estimates','',
      'Population: certified 24-month pool / observed-nonadjacent sample. No new engine searches or API calls.',
      'These are conditional within-chooser associations, not a separation of merit from blame or a causal effect.',
      '',f"Input census: {validation['n']:,} opportunities, {validation['grants']:,} grants, {validation['choosers']:,} choosers.",
      f"Primary sample: {fits[0]['n']:,} competitive opportunities after ply 10; {fits[0]['g']:,} choosers.",'',
      '| Primary contrast | Difference (pp) | 95% interval | Holm p (3 tests) |',
      '| --- | ---: | --- | ---: |']
    for r in primary:lines.append(f"| {r['contrast']} | {r['estimate_pp']:.4f} | [{r['lo']:.4f}, {r['hi']:.4f}] | {r['holm_p']:.4g} |")
    lines += ['',
      'The curve is unconstrained. Positive selected contrasts do not establish monotonicity everywhere; nonsignificant contrasts do not establish a flat curve.',
      'Each profile standardizes to the opportunity-weighted population of its own model sample. Clock/rating sensitivities retain the same rows through explicit missingness indicators.',
      'Continuous profiles use raw non-mate scores. Finite upper tails and positive forced mates have separate coefficients. The full-range model also separates lower finite tails and negative mates.',
      'The eight-bin diagnostic deliberately combines positive mates and finite >=600 positions in its last bin, following the original diagnostic specification.',
      'Standard errors use chooser-cluster scores summed over all months, with G/(G-1) correction. Reported 95% intervals are pointwise normal intervals.',
      'Level bands use joint cluster influence for the outcome mean, standardization composition, and slope. They allow the empirical target population to vary when chooser clusters are resampled; they are not conditional fixed-account uncertainty.',
      'Singleton and never-grant accounts remain. Singletons contribute zero within-account slope information. Nonestimable contrasts/levels are blank; no silent clipping or coefficient interpretation from a rank-deficient direction.',
      'Tier/early-late interactions report group-specific slope contrasts and their joint equality tests. Group indices: tiers 0:<1600, 1:1600–1999, 2:2000–2399, 3:2400+; early/late 0:<=10 plies, 1:>10 plies.',
      '',f'Out-of-range fitted-level warnings: {len(warnings)}. See warnings.json.','',
      'Primary table: planned_contrasts.csv. Full samples: model_samples.csv. Figures: merit_continuous.pdf/png and material_profile.pdf/png.',
      'Row-level data, identifiers, and partitions stay in PRIVATE/. The transfer ZIP contains aggregate outputs and code only.']
    (report/'SUMMARY.md').write_text('\n'.join(lines)+'\n')
    latex=['% Generated estimates; selected contrasts are not a global monotonicity test.',r'\begin{tabular}{lrr}',r'\hline',r'Contrast & Difference (pp) & Standard error \\',r'\hline']
    for r in primary:latex.append(f"{r['contrast']} & {r['estimate_pp']:.4f} & {r['se']:.4f} \\\\")
    latex += [r'\hline',r'\end{tabular}'];(report/'primary_contrasts.tex').write_text('\n'.join(latex)+'\n')

def plot(report,c):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig=plt.figure(figsize=(9.5,5.6),layout='constrained');gs=fig.add_gridspec(2,2,width_ratios=[3.5,1.2],height_ratios=[3,1])
    ax=fig.add_subplot(gs[0,0]);tail=fig.add_subplot(gs[0,1]);support=fig.add_subplot(gs[1,0]);note=fig.add_subplot(gs[1,1]);note.axis('off')
    for model,label,color in [('primary_competitive_late','Primary','#183a54'),('competitive_late_clocks','Plus clocks','#bb6b34'),('competitive_late_rating','Plus rating controls','#328672')]:
        d=c[(c.model==model)&(c.cp>=-100)&(c.cp<600)&(~c.mate)].sort_values('cp')
        ax.plot(d.cp,d.adjusted_percent,label=label,color=color,lw=1.5)
        if model=='primary_competitive_late':ax.fill_between(d.cp,d.lo,d.hi,color=color,alpha=.2)
    ax.set(ylabel='Adjusted grant rate (%)',xlabel='Rival’s evaluation (centipawns)',title='Competitive positions after ply 10');ax.legend(frameon=False,fontsize=9)
    d=c[(c.model=='primary_competitive_late')&(c.cp>=600)]
    tail.errorbar(np.arange(len(d)),d.adjusted_percent,yerr=1.96*d.se,fmt='o',color='#183a54',capsize=3)
    tail.set_xticks(np.arange(len(d)),['Finite\n≥600','Positive\nmate']);tail.set(title='Separate categories',ylabel='Adjusted grant rate (%)')
    raw=pd.read_parquet(report/'raw_continuous_support.parquet');raw['cp']=pd.to_numeric(raw.eval50,errors='coerce')
    raw=raw[(raw.cp>=-100)&(raw.cp<600)&(raw.stage>=6)].groupby('cp',as_index=False).n.sum()
    support.bar(raw.cp+25,raw.n/1e6,width=48,color='#a9b4be');support.set(xlim=(-100,600),xlabel='Rival’s evaluation (centipawns)',ylabel='Opportunities\n(millions)')
    note.text(0,1,'Pointwise 95% intervals.\nChooser fixed effects.\nUnconstrained spline.\nNo estimates of motives.',va='top',fontsize=9)
    fig.savefig(report/'merit_continuous.pdf');fig.savefig(report/'merit_continuous.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4.5),layout='constrained')
    for model,label,color in [('material_competitive_late_base','Competitive','#183a54'),('material_full_late_base','All board positions','#bb6b34')]:
        d=c[c.model==model];ax.errorbar(np.arange(len(d)),d.adjusted_percent,yerr=1.96*d.se,fmt='o-',label=label,color=color,capsize=3)
    ax.set_xticks(np.arange(8),MATERIAL_LABELS);ax.set(xlabel='Rival minus chooser material (pawn equivalents)',ylabel='Adjusted grant rate (%)',title='Material profile after ply 10');ax.legend(frameon=False)
    fig.savefig(report/'material_profile.pdf');fig.savefig(report/'material_profile.png',dpi=180);plt.close(fig)
