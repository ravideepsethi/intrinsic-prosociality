"""A2 aggregate-only report, planned contrasts and declared Holm families."""
from common import *
from design import point_vector,BLOCKS,PRIMARY
from estimate import estimable,coefficient_cov,level
from scipy.stats import norm

def summary(fit,cov,v):
    if not estimable(fit,v):return dict(status='NOT_ESTIMABLE',estimate=None,se=None,low=None,high=None,p=None)
    e=float(v@fit['beta']);se=float(np.sqrt(max(0,v@cov@v)))
    p=float(2*norm.sf(abs(e/se))) if se>0 else (0. if e else 1.)
    return dict(status='ESTIMATED',estimate=e,se=se,low=e-1.96*se,high=e+1.96*se,p=p)
def holm(rows):
    families={}
    for r in rows:families.setdefault(r['family'],[]).append(r)
    for family,rs in families.items():
        order=sorted(rs,key=lambda r:1. if r['p'] is None else r['p']);last=0
        for j,r in enumerate(order):
            last=max(last,min(1.,(len(order)-j)*(1. if r['p'] is None else r['p'])))
            r['holm_p']=last if r['p'] is not None else None;r['family_tests']=len(order)
    return rows
def render(out,specs,fits,meats,history_status):
    coefficients=[];contrasts=[];profiles=[];samples=[];covs={};orders={};warnings=[]
    finite_names={n for b in BLOCKS.values() for n in b}|{'competitive','blunder','gap_per100'}
    for s,f,M in zip(specs,fits,meats):
        require(f['g']>1,'Too few chooser clusters: '+s['name']);V=coefficient_cov(f,M)
        covs[s['name']]=V;orders[s['name']]=f['names']
        samples.append(dict(model=s['name'],N=f['n'],choosers=f['g'],grant_or_blunder_rate=f['mean_y'],
                            singletons_retained=f['singletons'],never_outcome_accounts=f['never'],rank=f['rank'],columns=len(f['names']),**{k:s[k] for k in ['kind','stage','region','support']}))
        for j,name in enumerate(f['names']):
            v=np.eye(1,len(f['names']),j)[0];r=summary(f,V,v)
            coefficients.append(dict(model=s['name'],term=name,role='focal' if j<f['p'] else 'adjustment',**r))
            key=name.removesuffix(':competitive')
            if j<f['p'] and key in finite_names:
                if s['kind']=='profile':continue
                if s['kind']=='asymmetry' and not name.endswith(':competitive'):continue
                family=('asymmetry_'+s['stage'] if s['kind']=='asymmetry' else
                        'rating_gap_blunder_thresholds' if s['kind']=='blunder_outcome' else
                        'blunder_thresholds_both_regions' if s['kind']=='blunder_proxy' else
                        'cross_region_ladder' if s['kind']=='region' else
                        ('joint_' if s['name'].startswith('joint_') else 'single_')+s['stage']+'_both_regions')
                contrasts.append(dict(model=s['name'],contrast=name,family=family,**r))
        if s['kind']=='profile':
            for lo,hi in [(0,100),(100,300),(300,500)]:
                r=summary(f,V,point_vector(f,hi)-point_vector(f,lo))
                contrasts.append(dict(model=s['name'],contrast=f'{lo}_to_{hi}_cp',family=s['name']+'_three_steps',**r))
            for cp,mate,label in [(x,False,str(x)) for x in range(-100,600,10)]+[(599,False,'599'),(700,False,'finite_ge600'),(10000,True,'positive_mate')]:
                v=point_vector(f,cp,mate)[:f['p']][None,:]
                est,se,ok=level(f,M,v)
                profiles.append(dict(model=s['name'],point=label,cp=None if cp>=600 else cp,estimate=est if ok else None,
                                     se=se if ok else None,low=est-1.96*se if ok else None,high=est+1.96*se if ok else None,status='ESTIMATED' if ok else 'NOT_ESTIMABLE'))
        if f['rank']<len(f['names']):warnings.append(dict(model=s['name'],nuisance_or_focal_aliases=len(f['names'])-f['rank'],action='Only estimable contrasts receive estimates; inspect focal statuses.'))
    table(out/'model_samples',samples);table(out/'coefficients',coefficients);table(out/'planned_contrasts',holm(contrasts));table(out/'adjusted_profiles',profiles)
    npz(out/'model_covariances.npz',**covs);dump(out/'coefficient_order.json',orders);dump(out/'warnings.json',warnings)
    lines=['# A2 responsibility diagnostics','',
           'Specified follow-up using the frozen 20,000-chooser sample. All effects are conditional associations. Outcomes are 100 × grant, except explicitly named blunder-outcome models.',
           '',f"History status: **{history_status['status']}**.",'',
           'A null proxy coefficient does not establish that blame is absent. A nonzero coefficient does not by itself establish blame. The pooled asymmetry rows directly test slope differences; significance in only one separate sample is not that test.',
           '', '| Model / contrast | Estimate (pp) | 95% interval | Holm p |','|---|---:|---:|---:|']
    for r in contrasts:
        if r['model'] not in ['curve_late_common_baseline','curve_late_common_proxies','cross_region_baseline','cross_region_proxies','asymmetry_late']:continue
        val='Not estimable' if r['estimate'] is None else f"{r['estimate']:.3f}"
        ci='' if r['low'] is None else f"[{r['low']:.3f}, {r['high']:.3f}]"
        hp='' if r['holm_p'] is None else f"{r['holm_p']:.3g}"
        lines.append(f"| {r['model']} / {r['contrast']} | {val} | {ci} | {hp} |")
    lines+=['','Read coverage.csv and model_samples.csv before interpreting the estimates. Baseline/proxy curve comparisons use identical trajectory-supported rows. Canonical final evaluations determine all board-state memberships; re-evaluations are diagnostics only.',
            '', 'The low-loss/ample-clock profile is a selected-subset sensitivity. It is not the requested no-prior-disconnection profile unless the history input is supplied. Net swings share the final evaluation mechanically; own-last-move loss is the more direct move proxy.',
            '', 'The report contains aggregate statistics only. Game/account identifiers, replays and raw scores remain in PRIVATE folders.']
    (out/'READ_ME_FIRST.md').write_text('\n'.join(lines)+'\n')
    try:
        import matplotlib;matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(7.5,4.6))
        for name,label in [('curve_late_common_baseline','Same rows, baseline'),('curve_late_common_proxies','Same rows, trajectory/clock/material proxies')]:
            d=pd.DataFrame(profiles);d=d[(d.model==name)&d.cp.notna()];x=d.cp.to_numpy(float)
            ax.plot(x,d.estimate,label=label);ax.fill_between(x,d.low.to_numpy(float),d.high.to_numpy(float),alpha=.12)
        ax.set(xlabel="Rival's evaluation (centipawns)",ylabel='Adjusted grant rate (%)');ax.legend(frameon=False,fontsize=8)
        ax.spines[['top','right']].set_visible(False);fig.tight_layout();fig.savefig(out/'a2_profile.png',dpi=180);plt.close(fig)
    except ImportError:pass
