"""Specified A2 follow-up. No outcome-driven model, cutoff or knot selection."""
from common import *
import a1_design as a1
from features import MATE_LABELS

BLOCKS={'own':['own_loss100'],'net2':['net2_loss100'],'net4':['net4_loss100'],
        'clock':['log_rival_clock','clock_ratio','time_trouble'],
        'clock_log':['log_rival_clock'],'clock_ratio':['clock_ratio'],'clock_trouble':['time_trouble'],
        'material':['material_swing4'],'history90':['prior90_rate'],
        'historypre':['prepanel_rate']}
PRIMARY=['own','net2','net4','clock','material']
SINGLES=['own','net2','net4','clock_log','clock_ratio','clock_trouble','material']
def specifications(history=False):
    specs=[];blocks=PRIMARY+(['history90'] if history else [])
    def add(name,kind='profile',stage='late',region='competitive',support='all',proxies=(),**kw):
        specs.append(dict(name=name,kind=kind,stage=stage,region=region,support=support,
                          proxies=list(proxies),controls='base',history=history,**kw))
    for stage in ['late','all']:
        add('curve_'+stage+'_all_rows',stage=stage)
        add('curve_'+stage+'_common_baseline',stage=stage,support='trajectory')
        add('curve_'+stage+'_common_proxies',stage=stage,support='trajectory',proxies=PRIMARY)
        for region in ['competitive','losing']:
            for block in SINGLES+(['history90'] if history else []):
                add('proxy_'+stage+'_'+region+'_'+block,kind='proxy',stage=stage,region=region,proxies=[block],
                    support='history90' if block=='history90' else 'all')
            add('joint_'+stage+'_'+region,kind='proxy',stage=stage,region=region,
                support='trajectory_history' if history else 'trajectory',proxies=blocks)
        add('asymmetry_'+stage,kind='asymmetry',stage=stage,region='binary',
            support='trajectory_history' if history else 'trajectory',proxies=blocks)
    for threshold in [100,200,300]:
        for region in ['competitive','losing']:
            add(f'blunder{threshold}_{region}',kind='blunder_proxy',region=region,support='own_finite',threshold=threshold)
        add(f'gap_predicts_blunder{threshold}',kind='blunder_outcome',support='own_finite',threshold=threshold)
    add('curve_late_common_proxies_rating',support='trajectory',proxies=PRIMARY)
    specs[-1]['controls']='rating'
    for proxies in [[],PRIMARY]:
        add('cross_region_'+('baseline' if not proxies else 'proxies'),kind='region',region='binary',support='trajectory',proxies=proxies)
    add('curve_low_loss_ample_clock',support='low_loss_clock')
    if history:
        for proxies in [[],blocks]:
            add('curve_history_common_'+('baseline' if not proxies else 'proxies'),support='trajectory_history',proxies=proxies)
        add('curve_low_loss_ample_clock_no_prior_disconnect',support='clean')
        for region in ['competitive','losing']:
            add('proxy_late_'+region+'_historypre',kind='proxy',region=region,support='historypre',proxies=['historypre'])
    return specs

def select(d,s):
    m=np.ones(len(d),bool)
    if s['region']=='competitive':m &= d.board.to_numpy()>=-100
    if s['region']=='losing':m &= d.board.to_numpy()<=-300
    if s['region']=='binary':m &= (d.board.to_numpy()>=-100)|(d.board.to_numpy()<=-300)
    if s['stage']=='late':m &= d.ply.to_numpy()>10
    support=s['support']
    if support in ['trajectory','trajectory_history']:m &= d.trajectory_ok.to_numpy(bool)
    if support in ['history90','trajectory_history','clean']:m &= d.prior90_complete.to_numpy(bool)
    if support=='historypre':m &= d.prepanel_complete.to_numpy(bool)
    if support in ['own_finite','low_loss_clock','clean']:m &= d.own_kind.to_numpy()=='finite'
    if support in ['low_loss_clock','clean']:m &= (d.own_loss100.to_numpy()<1)&(d.clock_fraction.to_numpy()>.1)
    if support=='clean':m &= d.prior90_disconnections.to_numpy()==0
    a=d.loc[m].reset_index(drop=True)
    if s['kind']=='blunder_outcome':a['y']=(a.own_loss100>=s['threshold']/100).astype(int)
    return a

def proxy_matrix(d,blocks):
    cols=[];names=[]
    for block in blocks:
        for n in BLOCKS[block]:
            x=d[n].to_numpy(float);ok=np.isfinite(x)
            cols.append(np.where(ok,x,0));names.append(n)
            if block in ['own','net2','net4']:
                # Separate exact-mate transitions and unavailable endpoints. Never +/-10000 CP.
                for label in MATE_LABELS[1:]:
                    names.append(block+'_'+label);cols.append((d[block+'_kind'].to_numpy()==label).astype(float))
            else:
                names.append(n+'_missing');cols.append((~ok).astype(float))
        if block in ['history90','historypre']:
            n='prior90_starts' if block=='history90' else 'prepanel_starts'
            names.append(n+'_zero');cols.append((d[n].to_numpy()==0).astype(float))
    return np.column_stack(cols) if cols else np.empty((len(d),0)),names

def profile_basis(d):return a1.eval_base(d,dict(kind='spline',sample='competitive_late'))
def eval_controls(d,region):
    if region=='competitive':
        b=a1.bins_code(d);return np.column_stack([b==j for j in range(1,8)]).astype(float),['eval_bin_'+str(j) for j in range(1,8)]
    return a1.eval_base(d,dict(kind='spline',sample='full_late'))
def design(d,s):
    kind=s['kind'];cols=[];names=[];ng=1;groups=np.zeros(len(d),int)
    P,pnames=proxy_matrix(d,s['proxies'])
    comp=(d.board.to_numpy()>=-100).astype(float)
    if kind=='profile':f,fn=profile_basis(d)
    elif kind=='region':f=comp[:,None];fn=['competitive']
    elif kind=='blunder_outcome':f=d.gap.to_numpy(float)[:,None]/100.;fn=['gap_per100']
    elif kind=='blunder_proxy':f=(d.own_loss100.to_numpy()>=s['threshold']/100.).astype(float)[:,None];fn=['blunder']
    elif kind=='asymmetry':
        f=np.column_stack([comp,P,P*comp[:,None]])
        fn=['competitive']+pnames+[n+':competitive' for n in pnames]
    else:f=P;fn=pnames
    cols.append(f);names.extend(fn);p=f.shape[1]
    if kind in ['profile','region'] and P.shape[1]:cols.append(P);names.extend(pnames)
    if kind not in ['profile','region']:
        if kind=='asymmetry':
            ec,nc=eval_controls(d,'competitive');el,nl=eval_controls(d,'losing')
            cols.extend([ec*comp[:,None],el*(1-comp[:,None])]);names.extend(['comp_'+n for n in nc]+['lost_'+n for n in nl])
        else:
            E,en=eval_controls(d,s['region']);cols.append(E);names.extend(en)
    # Reuse A1's month/speed/stage and rating design. Empty focal block is discarded.
    stub=dict(kind='bins',sample='competitive_'+s['stage'],controls=s['controls'])
    X,ns,fp,_,_=a1.design(d,stub);N=X[:,fp:];nn=ns[fp:]
    if s['controls']=='rating' and 'clock' in s['proxies']:
        # The rival's log clock is already a proxy; retain the chooser's log clock.
        keep=[i for i,n in enumerate(nn) if n not in ['log_clock_d','missing_clock_d']]
        N=N[:,keep];nn=[nn[i] for i in keep]
    cols.append(N);names.extend(nn)
    if kind=='asymmetry':cols.append(N*comp[:,None]);names.extend([n+':competitive' for n in nn])
    return np.column_stack(cols).astype(float),names,p,groups,ng

def dummy():
    d=dict(chooser=[1],y=[0],cp=[0],board=[0],mate=[False],ply=[20],rating=[1700],gap=[0],
           clock_c=[100],clock_d=[100],premium=[6],rd_c=[60],rd_d=[60],month_code=[0],speed_code=[1],stage=[6],
           trajectory_ok=[True],clock_fraction=[.5],log_rival_clock=[np.log(101)],clock_ratio=[1],time_trouble=[0],
           material_swing4=[0],prior90_rate=[0],prepanel_rate=[0],prior90_starts=[10],prepanel_starts=[10],
           prior90_complete=[True],prepanel_complete=[True],prior90_disconnections=[0])
    for p in ['own','net2','net4']:d[p+'_loss100']=[0];d[p+'_kind']=['finite']
    return pd.DataFrame(d)
def point_vector(fit,cp=0,mate=False):
    d=dummy();d['cp']=np.nan if mate else cp;d['board']=10000 if mate else cp;d['mate']=mate
    f,_=profile_basis(d);out=np.zeros(len(fit['beta']));out[:fit['p']]=f[0];return out
