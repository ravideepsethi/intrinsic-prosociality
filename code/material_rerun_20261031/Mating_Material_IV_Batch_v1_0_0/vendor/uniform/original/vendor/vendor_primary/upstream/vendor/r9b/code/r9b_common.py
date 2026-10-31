"""R9b contracts. All upstream R9 files remain byte-for-byte unchanged."""
from pathlib import Path
import sys, os, json, math, hashlib, time
PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE/'frozen_R9/code'))
from r9_common import *
import r9_models, r9_inputs, r9_scores
import env_common, author_history, performance_histories as fast, performance_cache as cache
VERSION='1.0.0'
R9_CONF='4028bf3e185783a17679ed3d5fee5b376028f37141e1e5ce09b93b068a6a6e0b'
COMMON_SD=0.04979005187533171
SPECIFICATIONS=[
 ('primary90','spaced90',True,False,False),
 ('repeated_pooled','spaced90',True,True,False),
 ('repeated_recipient_FE','spaced90',True,True,True),
 ('spacing30','spaced30',True,False,False),
 ('no_spacing','all',True,False,False),
 ('first_common_controls','first',True,False,False),
 ('primary90_without_recipient_history','spaced90',False,False,False),
 ('first_without_recipient_history','first',False,False,False)]
DEFINITION_B=dict(parent=R9_CONF,common_SD=COMMON_SD,intervals='normal Wald 95%; no AR',
 exposure_rows='frozen original spacing and first flags; author-clean histories and outcomes; no replacement',
 score='A all-time donor-month leave-pair-out; >=5 pooled donors',
 history_controls='three pooled Score A donor-set controls in every specification; recipient-history removal only where named',
 competitive='partition same eligible donor set at cell//100>=2 (eval>=-100); same pooled donor-month state reference',
 competitive_comparisons='own supported samples and same-row pooled companions; both scores require >=5 each',
 covariance='shared-account-OR-date CR0; fixed generated instrument',
 hour_FE='add absolute UTC start-hour or absolute UTC last-move-hour to frozen FE',
 J8='omitted as optional; no earlier entry/ordinary frames rerun')

def check_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        sha,name=line.split('  ',1);p=(PACKAGE/name).resolve()
        u.require(p.is_relative_to(PACKAGE),'Unsafe manifest path');r.io.checked(p,sha)
    verify_package()

def clean_inference(b,var,scale=1.):
    ans=m7.inference(b,var,scale)
    return {k:v for k,v in ans.items() if not k.startswith('ci90')}

def scalar(y,z,meat,scale=1.):
    den=float(z@z)
    if den<=1e-20:return dict(supported=False,reason='NO_RESIDUAL_VARIATION')
    b=float(z@y)/den;v=float(meat(z*(y-b*z)/den)[0,0])
    ans=clean_inference(b,v,scale)
    ans['partial_R2']=float((z@y)**2/(den*(y@y))) if y@y>0 else None
    if ans.get('standard_error'):ans['wald_F']=(b/ans['standard_error'])**2
    return ans

def require_rank(a,label):
    singular=np.linalg.svd(a,compute_uv=False)
    u.require(len(singular)>0 and singular[-1]>singular[0]*1e-10,label+' rank deficient; no regularization')

def multi_iv(y,d,z,meat):
    """2SLS sandwich; optional efficient two-step Hansen test on identical moments."""
    if d.ndim==1:d=d[:,None]
    if z.ndim==1:z=z[:,None]
    n,p=d.shape;q=z.shape[1]
    G=z.T@z;require_rank(G,'Instruments');Gi=np.linalg.inv(G)
    cross=z.T@d;A=cross.T@Gi@cross;require_rank(A,'First-stage cross moments')
    bread=np.linalg.inv(A)@cross.T@Gi;b=bread@(z.T@y)
    e=y-d@b;S=meat(z*e[:,None]);V=bread@S@bread.T
    details=dict(endogenous_columns=p,instruments=q,covariance='shared_account_OR_date_CR0')
    if q>p:
        ev=np.linalg.eigvalsh((S+S.T)/2)
        if ev.min()<=max(abs(ev).max(),1e-30)*1e-10:
            details['Hansen_J']=dict(supported=False,reason='NONPOSITIVE_OR_SINGULAR_MOMENT_COVARIANCE_NOT_REPAIRED')
        else:
            W=np.linalg.inv(S);bg=np.linalg.solve(cross.T@W@cross,cross.T@W@(z.T@y))
            g=z.T@(y-d@bg);J=float(g@W@g)
            details['Hansen_J']=dict(supported=True,statistic=J,df=q-p,p_value_asymptotic=r.num.chi2_sf(J,q-p),
                method='efficient two-step GMM J; weight from 2SLS residual shared-account-OR-date CR0 moments',
                two_stage_least_squares_reported_separately=True)
    return b,V,details

def first_stage_system(d,z,meat):
    if d.ndim==1:d=d[:,None]
    G=z.T@z;require_rank(G,'FS instruments');Gi=np.linalg.inv(G)
    pi=Gi@(z.T@d);hat=z@pi;err=d-hat;p=d.shape[1];q=z.shape[1];rows=[]
    for j in range(p):
        V=Gi@meat(z*err[:,j,None])@Gi;W=m7.wald(pi[:,j],V)
        row=dict(endogenous_column=j,joint_excluded_instrument_test=W,
            first_stage_F=W.get('wald_chi2',float('nan'))/W.get('rank',q) if W.get('supported') else None,
            partial_R2=1-float(err[:,j]@err[:,j])/float(d[:,j]@d[:,j]),
            coefficients=[clean_inference(pi[k,j],V[k,k],100*COMMON_SD) for k in range(q)])
        if p==q:
            others=[k for k in range(p) if k!=j]
            if others:
                h=hat[:,others];require_rank(h.T@h,'Other fitted endogenous regressors')
                delta=np.linalg.solve(h.T@h,h.T@d[:,j]);_,_,vh=np.linalg.svd(h.T@z,full_matrices=True)
                direction=vh[-1];ce=err[:,j]-err[:,others]@delta
            else:direction=np.ones(1);ce=err[:,j]
            zz=z@direction;zz/=math.sqrt(float(zz@zz)/len(zz));den=float(zz@zz)
            slope=float(zz@d[:,j])/den;variance=float(meat(zz*ce/den)[0,0])
            row.update(conditional_F=slope*slope/variance if variance>0 else None,conditional_rank_df=1,
                conditional_residual_adjusted=True,conditional_method='SW scalar direction with u_j-U_other delta')
        elif p==1:
            row['conditional_F']=row['first_stage_F'];row['conditional_rank_df']=q
        rows.append(row)
    return rows
