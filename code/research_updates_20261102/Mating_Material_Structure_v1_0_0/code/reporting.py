"""Named linear contrasts with full covariance and explicit identification gates."""
from util import *
from sources import producers
import numpy as np
import pandas as pd
from scipy.special import ndtr
from scipy.stats import chi2

Z=1.959963984540054
def vector(f,terms):
    result=np.zeros(len(f['names']))
    for name,weight in terms.items():result[f['names'].index(name)]+=weight
    return result

def estimable(f,L):
    v=np.asarray(L)/f['scale']
    return np.linalg.norm(f['null'].T@v)<=1e-7*max(np.linalg.norm(v),1e-10)

def row(model,f,label,L,group='',panel='',unit='percentage_points'):
    r=dict(model=model,panel=panel,group=group,contrast=label,unit=unit,opportunities=f['n'],choosers=f['g'])
    if not estimable(f,L):return dict(r,status='NOT_ESTIMABLE',estimate=None,se=None,ci_low=None,ci_high=None,p_value=None)
    e=float(L@f['beta']);v=float(L@f['covariance']@L)
    require(v>=-1e-10,'Negative contrast variance')
    se=float(np.sqrt(max(0,v)));p=float(2*ndtr(-abs(e/se))) if se>1e-14 else (1. if abs(e)<1e-12 else 0.)
    return dict(r,status='ESTIMATED',estimate=e,se=se,ci_low=e-Z*se,ci_high=e+Z*se,p_value=p)

def stage_vector(f,speed,k):
    _,r10,_,_,_=producers()
    if k==0:return np.zeros(len(f['names']))
    name='stage_'+r10.STAGES[k]
    return vector(f,{name:1,**({name+':'+speed:1} if speed!='ultrabullet' else {})})

def baseline_check(f,out,reference=None):
    reference=Path(reference) if reference else ROOT/'evidence/core_review/covariance_column1.npz'
    with np.load(reference,allow_pickle=False) as z:
        old_names=z['names'].tolist();beta=z['beta'];cov=z['covariance']
    rows=[]
    for j,name in enumerate(f['names']):
        L=np.eye(len(f['names']))[j]
        if not estimable(f,L):continue
        k=old_names.index(name);old_se=np.sqrt(max(0,cov[k,k]));new_se=np.sqrt(max(0,f['covariance'][j,j]))
        ok=bool(np.isclose(f['beta'][j],beta[k],rtol=1e-5,atol=1e-6) and np.isclose(new_se,old_se,rtol=1e-5,atol=1e-7))
        rows.append(dict(term=name,reviewed_estimate=beta[k],new_estimate=f['beta'][j],reviewed_se=old_se,new_se=new_se,passed=ok))
    table(out/'CORE_REPRODUCTION.csv',rows)
    require(rows and all(r['passed'] for r in rows),'Pooled-clock model fails to reproduce the reviewed material R11 fit; completion withheld')
    return dict(terms=len(rows),all_passed=True,max_abs_estimate_difference=max(abs(r['new_estimate']-r['reviewed_estimate']) for r in rows),
                max_abs_se_difference=max(abs(r['new_se']-r['reviewed_se']) for r in rows))

def joint(f,matrix,label):
    if not all(estimable(f,L) for L in matrix):return dict(test=label,status='NOT_ESTIMABLE')
    L=np.array(matrix);b=L@f['beta'];v=L@f['covariance']@L.T
    values,U=np.linalg.eigh((v+v.T)/2);tol=max(1e-12,float(values.max())*1e-9);good=values>tol
    if not good.any():return dict(test=label,status='NO_VARIANCE')
    statistic=float(np.sum((U[:,good].T@b)**2/values[good]));df=int(good.sum())
    return dict(test=label,status='ESTIMATED',wald_chi2=statistic,df=df,p_value=float(chi2.sf(statistic,df)))

def write_reports(fits,out,reference=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    reproduce=baseline_check(fits['clock_pooled'],out,reference)
    clock=[]
    for side in ('d','c'):
        name='log1p_clock_'+side;f=fits['clock_region'];base=vector(f,{name:1});difference=vector(f,{name+':competitive':1})
        for group,L in [('competitive',base+difference),('noncompetitive',base),('competitive_minus_noncompetitive',difference)]:
            clock.append(row('clock_region',f,'opponent_clock' if side=='d' else 'chooser_clock',L,group,'region_clocks',unit='pp_per_log1p_second'))
        fp=fits['clock_pooled'];clock.append(row('clock_pooled',fp,'opponent_clock' if side=='d' else 'chooser_clock',vector(fp,{name:1}),'pooled','pooled_clocks',unit='pp_per_log1p_second'))
    table(out/'tab_app_clocks.csv',clock)
    f=fits['stage_speed'];_,r10,_,_,_=producers();speed_rows=[]
    observed=pd.read_csv(out/'speed_composition.csv');speeds=[s for s in r10.SPEEDS if s in set(observed.speed)]
    for speed in speeds:
        for k in range(1,8):speed_rows.append(row('stage_speed',f,r10.STAGES[k]+' minus 0_4',stage_vector(f,speed,k),speed,'A_stage'))
        speed_rows.append(row('stage_speed',f,'81_plus minus 41_80',stage_vector(f,speed,7)-stage_vector(f,speed,6),speed,'B_rebound'))
        speed_rows.append(row('stage_speed',f,'decline_0_4_to_41_80',-stage_vector(f,speed,6),speed,'B_decline'))
    for fast,slow in zip(speeds,speeds[1:]):
        speed_rows.append(row('stage_speed',f,'decline_minus_next_faster',stage_vector(f,fast,6)-stage_vector(f,slow,6),slow+' minus '+fast,'B_between_speed'))
    table(out/'tab_app_stage_speed.csv',speed_rows)
    require(all(r['status']=='ESTIMATED' for r in speed_rows),'A requested observed-speed contrast is not identified')
    require(all(r['status']=='ESTIMATED' for r in clock),'A requested clock contrast is not identified')
    tests=[joint(f,[stage_vector(f,s,k)-stage_vector(f,speeds[0],k) for s in speeds[1:] for k in range(1,8)],'seven_stage_profiles_equal_across_observed_speeds'),
           joint(f,[stage_vector(f,s,6)-stage_vector(f,speeds[0],6) for s in speeds[1:]],'decline_0_4_to_41_80_equal_across_observed_speeds')]
    table(out/'stage_speed_joint_tests.csv',tests)
    coefs=[];metadata=[]
    for model,f in fits.items():
        save(out/'models'/(model+'.json'),{k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in f.items()})
        for j,name in enumerate(f['names']):coefs.append(row(model,f,name,np.eye(len(f['names']))[j],panel='coefficients'))
        metadata.append(dict(model=model,opportunities=f['n'],choosers=f['g'],grants=f['grants'],rank=f['rank'],columns=len(f['names']),
             normal_equation_error=f['normal_equation_error'],within_opportunities=f['within_n'],within_choosers=f['within_g'],cluster_correction=f['g']/(f['g']-1)))
    table(out/'all_coefficients.csv',coefs);table(out/'MODEL_METADATA.csv',metadata)
    old=pd.read_csv(ROOT/'evidence/r10_reference/stage_profiles.csv')
    old=old[(old.column=='column4')&(old.panel=='stage_profile')]
    old=old[['group','contrast','estimate','se']].rename(columns={'estimate':'old_estimate','se':'old_se'})
    comparisons=pd.DataFrame(speed_rows).query("panel=='A_stage'").merge(old,on=['group','contrast'],how='left',validate='one_to_one')
    require(comparisons.old_estimate.notna().all(),'Archived stage profile comparison missing')
    comparisons['estimate_change']=comparisons.estimate-comparisons.old_estimate
    comparisons['comparison_note']='Old R10 includes author accounts and old material rule; descriptive change, not a paired statistical test.'
    table(out/'STAGE_BEFORE_AFTER.csv',comparisons)
    save(out/'SPECIFICATION.json',dict(
        clock_pooled='Exact R11 column1, reproduces the reviewed corrected-material core fit.',
        clock_region='Same R11 column1 plus C*log1p(clock_c) and C*log1p(clock_d); original missing indicators remain pooled. No invalid clocks in the reviewed frame.',
        stage_speed='Exact recovered R10 column4: single pooled five-knot gap; stage x speed; position, month, speed, clock and original rating controls.',
        regions='Competitive >= -100; noncompetitive < -100 includes modestly worse. Clock second column is NOT restricted to <= -300.',
        equalweight='Exact original three-weight binary FE contrast; competitive >= -100 versus clearly worse <= -300; middle excluded only from this contrast.',
        stage_covariance='Chooser sandwich G/(G-1); all chooser clusters including singletons; no (N-1)/(N-K) factor.',
        speed_tests='Supplementary Wald tests use the four observed formats only. Absent ultrabullet is not treated as an estimated zero profile.',
        rating_layer='Original reconstructed premium and RD, no new rating replay.',core_reproduction=reproduce,
        raw_stage='Ply 2, 3–10, by ply 4, by ply 10, after ply 10, and all eight roughly-equal bands rebuilt on new author-excluded material frame.'))
    return dict(models=len(fits),clock_rows=len(clock),speed_contrasts=len(speed_rows),core_reproduction=reproduce)
