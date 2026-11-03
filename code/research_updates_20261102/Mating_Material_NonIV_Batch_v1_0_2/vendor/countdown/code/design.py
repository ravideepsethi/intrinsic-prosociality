"""Specification frozen before adjusted coefficients; feasibility outcomes were already seen."""
from common import *

SPEEDS=['bullet','blitz','rapid','classical','ultraBullet']
FAMILIES=[
 dict(name='primary',clock_multiple=0,pre_end='2025-07-19',post_start='2025-08-11'),
 dict(name='clock_long',clock_multiple=1,pre_end='2025-07-19',post_start='2025-08-11'),
 dict(name='clock_twice',clock_multiple=2,pre_end='2025-07-19',post_start='2025-08-11'),
 dict(name='calendar_august',clock_multiple=0,pre_end='2025-07-01',post_start='2025-08-01'),
 dict(name='calendar_september',clock_multiple=0,pre_end='2025-07-01',post_start='2025-09-01')]
M_GRID=[0.,.01,.025,.05,.10]
SPEC=dict(version=VERSION,sample='author-excluded main; finite non-mate cp < -100; deficits 0..8',
 families=FAMILIES,stage='ply 0-10,11-20,21-40,41-80,81+',
 effects=['chooser by speed','10cp evaluation bin by stage by period by speed','calendar month by speed'],
 controls=['log1p chooser last clock','log1p disconnected last clock','rating gap / 100','chooser rating / 100'],
 control_slopes='separate by period and speed',profile='saturated deficit indicators, reference 3',
 primary_contrast='mu4 minus equal-weight OLS linear extrapolation of mu0..mu3 to 4',
 secondary_contrast='0.5*mu2 - 1.5*mu3 + 1.5*mu4 - 0.5*mu5',
 primary_inference='chooser clustered CR0; normal 95% intervals; full joint covariance',
 secondary_inference='chooser + UTC last-move date - chooser/date CR0; no PSD repair',
 curvature_grid_pp_per_deficit_squared=M_GRID,curvature_method='conservative bias-expanded normal interval; not optimized Kolesar-Rothe',
 missing='reject missing or invalid model fields',singletons='iteratively remove FE-singleton rows; report retained sample',
 monthly='separate month/speed models with chooser and eval10-by-stage FE; joint chooser covariance across months',
 exploratory=True,warning='Calendar windows do not verify deployment; adjusted contrasts do not isolate selection from behavior')

def weights():
    d=np.arange(4,dtype=float);A=np.column_stack([np.ones(4),d]);w=np.zeros(9)
    w[:4]=-np.array([1.,4.])@np.linalg.pinv(A);w[4]=1.
    out={'one_sided_linear':w}
    A=np.column_stack([np.ones(4),d,d*d]);w=np.zeros(9);w[:4]=-np.array([1.,4.,16.])@np.linalg.pinv(A);w[4]=1.
    out['one_sided_quadratic']=w
    w=np.zeros(9);w[[2,3,4,5]]=[.5,-1.5,1.5,-.5];out['symmetric']=w
    w=np.zeros(9);w[[2,3,4]]=[1.,-2.,1.];out['local_linear_2_3']=w
    # Three mass points entirely on one side of the actual threshold.
    for k in (2,3,6,7,8):
        w=np.zeros(9);w[k-2:k+1]=[1.,-2.,1.];out['placebo_local_'+str(k)]=w
    for k in range(1,9):
        w=np.zeros(9);w[k-1:k+1]=[-1.,1.];out['adjacent_'+str(k-1)+'_'+str(k)]=w
    return out

WEIGHTS=weights()
KEY_CONTRASTS=['one_sided_linear','symmetric']

def bias_multiplier(w):
    w=np.asarray(w);require(abs(w.sum())<1e-10 and abs(w@np.arange(len(w)))<1e-10,'Contrast does not cancel a linear profile')
    return float(sum(abs(sum(w[j]*(j-k) for j in range(k+1,len(w)))) for k in range(1,len(w)-1)))

def selection(spec):
    if spec.get('month'):
        period='0::TINYINT';where='cal_month='+q(spec['month']);labels=[spec['month']]
    else:
        period=f"CASE WHEN position_date < DATE {q(spec['pre_end'])} THEN 0 ELSE 1 END::TINYINT"
        where=f"(position_date < DATE {q(spec['pre_end'])} OR position_date >= DATE {q(spec['post_start'])})";labels=['pre','post']
    mult=spec.get('clock_multiple',0)
    if mult:where+=f' AND clock_d>{mult}*long_clock_cut'
    if spec.get('benchmark'):where+=' AND chooser%64=0'
    return period,where,labels

def task_id(spec,speed):return spec['name']+'__'+speed
