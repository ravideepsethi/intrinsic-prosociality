from common import *
from design import *
from numerics import covariance_join
from scipy.stats import norm,chi2

def stats(b,v,ok=True):
    if not ok:return dict(estimate_pp=None,se_pp=None,ci95_low_pp=None,ci95_high_pp=None,p_value=None,inference_status='NOT_ESTIMABLE')
    if not math.isfinite(v) or v< -1e-12:return dict(estimate_pp=b,se_pp=None,ci95_low_pp=None,ci95_high_pp=None,p_value=None,inference_status='NEGATIVE_OR_INVALID_VARIANCE')
    se=math.sqrt(max(0.,v));p=2*float(norm.sf(abs(b/se))) if se else (1. if b==0 else 0.)
    return dict(estimate_pp=float(b),se_pp=se,ci95_low_pp=float(b-1.959963984540054*se),
                ci95_high_pp=float(b+1.959963984540054*se),p_value=p,inference_status='ESTIMABLE')

def load_influence(folder,kind):
    with np.load(Path(folder)/(kind+'.npz'),allow_pickle=False) as z:return z['ids'],z['influence']

def joint(models,kind,dimension):
    V=np.zeros((len(models)*dimension,)*2)
    for i,m in enumerate(models):
        a=load_influence(m['out'],kind)
        V[i*dimension:(i+1)*dimension,i*dimension:(i+1)*dimension]=a[1].T@a[1]
        for j in range(i):
            b=load_influence(models[j]['out'],kind);cross=covariance_join(a,b)
            V[i*dimension:(i+1)*dimension,j*dimension:(j+1)*dimension]=cross
            V[j*dimension:(j+1)*dimension,i*dimension:(i+1)*dimension]=cross.T
    return (V+V.T)/2

def family_report(run,name,results):
    folder=Path(run)/'report'/name;folder.mkdir(parents=True,exist_ok=True)
    chosen=[r for r in results if r['spec']['name']==name]
    table(folder/'model_status.csv',[dict(speed=r['speed'],status=r['status'],**r.get('counts',{})) for r in chosen])
    models=[dict(**read(Path(r['out'])/'MODEL.json'),out=r['out']) for r in chosen if r['status']=='COMPLETE']
    if not models:return
    V=joint(models,'chooser_profiles',18);mu=np.concatenate([m['profile_values'] for m in models]);ok=np.concatenate([m['profile_estimable'] for m in models])
    profiles=[];labels=[]
    for i,m in enumerate(models):
        for j,row in enumerate(m['profile']):
            ix=i*18+j;labels.append(f"{m['speed']}:{row['period']}:d{row['deficit']}")
            profiles.append(dict(family=name,speed=m['speed'])|row|stats(mu[ix],V[ix,ix],ok[ix]))
    table(folder/'adjusted_profiles.csv',profiles)
    npz(folder/'joint_profile_covariance.npz',covariance=V,estimate=mu,estimable=ok,labels=np.array(labels))
    table(folder/'coefficients_and_support.csv',[dict(speed=m['speed'],**r) for m in models for r in m['coefficients']])
    write(folder/'numerical_checks.json',[{k:m[k] for k in ['speed','rank','columns','counts','chooser_clusters','date_clusters','fe_diagnostics']} for m in models])
    contrasts=[]
    for m in models:
        for r in m['contrasts']:
            contrasts.append(dict(family=name,speed=m['speed'])|r|
                stats(r['estimate_pp'] or 0.,(r['se_pp'] or 0.)**2,r['estimable']))
    table(folder/'all_profile_contrasts.csv',contrasts)
    K=np.zeros((4*len(models),len(mu)))
    for i in range(len(models)):
        for g in range(2):
            for j,n in enumerate(KEY_CONTRASTS):K[i*4+g*2+j,i*18+g*9:i*18+g*9+9]=WEIGHTS[n]
    point=K@mu;Vc=K@V@K.T;Vd=joint(models,'date',4);Vcd=joint(models,'chooser_date',4);Vtwo=Vc+Vd-Vcd
    keyok=np.concatenate([m['key_estimable'] for m in models]);kl=[f"{m['speed']}:{p}:{n}" for m in models for p in ['pre','post'] for n in KEY_CONTRASTS]
    npz(folder/'joint_contrast_covariance.npz',estimate=point,chooser=Vc,date=Vd,chooser_date=Vcd,
        chooser_plus_date=Vtwo,estimable=keyok,labels=np.array(kl))
    queries=[]
    for i,m in enumerate(models):
        for j,n in enumerate(KEY_CONTRASTS):
            for g,p in enumerate(['pre','post']):
                qv=np.zeros(len(point));qv[i*4+g*2+j]=1;queries.append((m['speed'],p,n,qv,1))
            qv=np.zeros(len(point));qv[i*4+j]=-1;qv[i*4+2+j]=1
            queries.append((m['speed'],'post_minus_pre',n,qv,2))
            bullet=next((b for b,z in enumerate(models) if z['speed']=='bullet'),None)
            if bullet is not None and i!=bullet:
                v=qv.copy();v[bullet*4+j]+=1;v[bullet*4+2+j]-=1
                queries.append((m['speed']+'_minus_bullet','change_difference',n,v,4))
    # Fixed speed weights, formed from counts across both periods, used for both periods.
    shares=np.array([m['counts']['retained_rows'] for m in models],float);shares/=shares.sum()
    table(folder/'pooled_speed_weights.csv',[dict(speed=m['speed'],weight=float(w)) for m,w in zip(models,shares)])
    for j,n in enumerate(KEY_CONTRASTS):
        vectors=[]
        for g,p in enumerate(['pre','post']):
            v=np.zeros(len(point))
            for i,w in enumerate(shares):v[i*4+g*2+j]=w
            queries.append(('pooled_fixed_speed_weights',p,n,v,1));vectors.append(v)
        queries.append(('pooled_fixed_speed_weights','post_minus_pre',n,vectors[1]-vectors[0],2))
    policy=[];sensitivity=[]
    for speed,period,n,w,mult in queries:
        identified=bool(keyok[np.abs(w)>1e-14].all())
        for method,cov in [('chooser_CR0',Vc),('date_CR0',Vd),('chooser_plus_date_CR0',Vtwo)]:
            s=stats(float(w@point),float(w@cov@w),identified)
            prediction='not specified'
            if period=='post_minus_pre' and speed in ('bullet','ultraBullet'):prediction='positive under proposed mechanism'
            if period=='post_minus_pre' and speed in ('blitz','rapid','classical'):prediction='negative under proposed mechanism'
            if period=='change_difference' and speed.endswith('_minus_bullet'):prediction='negative under proposed mechanism'
            policy.append(dict(family=name,speed=speed,period=period,contrast=n,inference=method,predicted_direction=prediction,**s))
            if n=='one_sided_linear' and method=='chooser_CR0' and s['se_pp'] is not None:
                for M in M_GRID:
                    bias=bias_multiplier(WEIGHTS[n])*M*mult
                    sensitivity.append(dict(speed=speed,period=period,curvature_bound_pp=M,
                        worst_case_bias_pp=bias,estimate_pp=s['estimate_pp'],
                        interval_low_pp=s['ci95_low_pp']-bias,interval_high_pp=s['ci95_high_pp']+bias,
                        method='conservative normal CI plus worst-case discrete-curvature bias'))
    table(folder/'threshold_and_policy_tests.csv',policy);table(folder/'curvature_sensitivity.csv',sensitivity)
    plot_profiles(folder,profiles)

def plot_profiles(folder,rows):
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    speeds=[s for s in SPEEDS if any(r['speed']==s for r in rows)]
    fig,axes=plt.subplots(len(speeds),2,figsize=(10,3*len(speeds)),squeeze=False)
    for i,s in enumerate(speeds):
        for j,p in enumerate(['pre','post']):
            ax=axes[i,j];r=[x for x in rows if x['speed']==s and x['period']==p and x['inference_status']=='ESTIMABLE']
            if r:
                ax.errorbar([x['deficit'] for x in r],[x['estimate_pp'] for x in r],
                    yerr=[1.95996398454*x['se_pp'] for x in r],fmt='o',ms=4,color='#126e82',capsize=2)
                for x in r:ax.annotate(f"{x['n']/1000:.0f}k",(x['deficit'],x['estimate_pp']),xytext=(0,8),
                    textcoords='offset points',ha='center',fontsize=6,color='#444444')
            ax.axvline(3.5,color='#b04637',linestyle='--',lw=1);ax.set_xticks(range(9));ax.set_title(s+' / '+p)
            ax.set_xlabel('Disconnected player material deficit');ax.set_ylabel('Adjusted grant rate (%)')
            ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Adjusted material profiles: chooser-clustered 95% intervals',fontsize=12)
    fig.text(.5,.01,'Labels: retained observations (thousands). No smoothing. Period-specific standardization; calendar windows are exploratory.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.03,1,.97));fig.savefig(Path(folder)/'adjusted_profiles.pdf');fig.savefig(Path(folder)/'adjusted_profiles.png',dpi=160);plt.close(fig)

def monthly_report(run,results):
    folder=Path(run)/'report/monthly';folder.mkdir(parents=True,exist_ok=True);rows=[];tests=[];allprofiles=[]
    for speed in SPEEDS:
        recs=sorted([r for r in results if r['spec'].get('month') and r['speed']==speed and r['status']=='COMPLETE'],key=lambda r:r['spec']['month'])
        if not recs:continue
        models=[dict(**read(Path(r['out'])/'MODEL.json'),out=r['out']) for r in recs]
        V=joint(models,'monthly_keys',2);point=np.concatenate([m['key_values'] for m in models]);ok=np.concatenate([m['key_estimable'] for m in models])
        for i,m in enumerate(models):
            for j,n in enumerate(KEY_CONTRASTS):rows.append(dict(speed=speed,month=m['spec']['month'],contrast=n,
                n=m['counts']['retained_rows'],**stats(point[i*2+j],V[i*2+j,i*2+j],ok[i*2+j])))
            allprofiles.extend([dict(speed=speed,month=m['spec']['month'],**p) for p in m['profile']])
        npz(folder/(speed+'_joint_covariance.npz'),estimate=point,covariance=V,estimable=ok,
            labels=np.array([m['spec']['month']+':'+n for m in models for n in KEY_CONTRASTS]))
        # Pre-July months, no deployment-contaminated July. Equality is a diagnostic, not proof of parallel trends.
        for j,n in enumerate(KEY_CONTRASTS):
            ix=[i*2+j for i,m in enumerate(models) if m['spec']['month']<'2025-07' and ok[i*2+j]]
            if len(ix)<3:continue
            D=np.zeros((len(ix)-1,len(point)))
            for a,b in enumerate(ix[1:]):D[a,b]=1;D[a,ix[0]]=-1
            cov=D@V@D.T;v=D@point;rank=int(np.linalg.matrix_rank(cov,tol=1e-12))
            stat=float(v@np.linalg.pinv(cov,rcond=1e-10)@v)
            tests.append(dict(speed=speed,contrast=n,test='equal monthly contrasts before July 2025',
                months=len(ix),wald=stat,df=rank,p_value=float(chi2.sf(stat,rank)) if rank else None))
    table(folder/'monthly_thresholds.csv',rows);table(folder/'monthly_profiles.csv',allprofiles);table(folder/'preperiod_stability_tests.csv',tests)
    plot_monthly(folder,rows)

def plot_monthly(folder,rows):
    if not rows:return
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    speeds=[s for s in SPEEDS if any(r['speed']==s for r in rows)]
    fig,axes=plt.subplots(len(speeds),1,figsize=(11,2.5*len(speeds)),squeeze=False)
    for i,speed in enumerate(speeds):
        ax=axes[i,0];r=[x for x in rows if x['speed']==speed and x['contrast']=='one_sided_linear' and x['se_pp'] is not None]
        ax.errorbar([MONTHS.index(x['month']) for x in r],[x['estimate_pp'] for x in r],
            yerr=[1.95996398454*x['se_pp'] for x in r],fmt='o',color='#126e82',ms=3,capsize=2)
        ax.axhline(0,color='#888888',lw=.7);ax.axvspan(19.5,20.5,color='#b04637',alpha=.1)
        ax.set_title(speed);ax.set_xticks(range(0,24,3),MONTHS[::3]);ax.set_ylabel('Threshold gap (pp)')
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Monthly one-sided threshold contrasts; chooser-clustered 95% intervals')
    fig.tight_layout(rect=(0,0,1,.97));fig.savefig(Path(folder)/'monthly_thresholds.pdf');fig.savefig(Path(folder)/'monthly_thresholds.png',dpi=150);plt.close(fig)
