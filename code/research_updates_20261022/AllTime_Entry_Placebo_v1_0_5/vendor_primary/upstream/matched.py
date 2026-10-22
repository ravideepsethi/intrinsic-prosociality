"""The four zero-coded matched-design rows, using the frozen receipt weights."""
import importlib.util
import pyarrow.parquet as pq
from local_common import *

def core_module():
    p=ROOT/'vendor/kac/vendor/core/receipt_core.py'
    s=importlib.util.spec_from_file_location('receipt_core_local',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def receipt_path(project,explicit=None):
    if explicit:return Path(explicit)
    rel=Path('derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet')
    choices=[project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1/project_view'/rel,project/rel]
    for p in choices:
        if p.is_file():return p
    raise FileNotFoundError('Frozen matched frame absent: '+str(choices[0]))

def fit(y,D,X,w,groups,cluster,core,two_way=False):
    if len(groups)==3:
        from matched_absorption import absorb
        z,it,last=absorb(np.column_stack([y,D,X]),w,groups)
    else:z,it,last=core.weighted_absorb(np.column_stack([y,D,X]),w,groups)
    yy=z[:,0];xx=z[:,1:];f=solve((xx*w[:,None]).T@xx,xx.T@(w*yy))
    contrast=np.eye(len(f['beta']))[0];require(estimable(contrast,f)[0],'Matched treatment contrast not identified')
    residual=yy-xx@f['beta'];score=xx*(w*residual)[:,None];S,G=cluster_sums(score,cluster);M=S.T@S
    H=None
    if two_way:
        hour=groups[-1];SH,H=cluster_sums(score,hour)
        _,pairs=np.unique(np.column_stack([cluster,hour]),axis=0,return_inverse=True)
        SP,_=cluster_sums(score,pairs);M+=SH.T@SH-SP.T@SP;correction=1.
    else:correction=G/(G-1)*(len(y)-1)/(len(y)-f['rank'])
    V=f['bread']@M@f['bread']*correction
    out=inference(f['beta'][0]*100,V[0,0]*10000)
    return dict(out,exposures=len(y),clusters=G,hour_clusters=H,
                weighted_treated_mean=100*float(np.average(y[D==1],weights=w[D==1])),
                weighted_control_mean=100*float(np.average(y[D==0],weights=w[D==0])),
                absorption_iterations=int(it),absorption_max_residual=float(last),
                absorption_solver='hour-eliminated Schur complement' if len(groups)==3 else 'frozen alternating projections',
                covariance='opponent OR absolute UTC hour CR0' if two_way else 'opponent G/(G-1)*(N-1)/(N-rank)')

def censored_outcome(reached,grant,anchor,delta,next_disconnect):
    reached=np.asarray(reached,bool);next_disconnect=np.asarray(next_disconnect,float)
    times=np.asarray(anchor,float)+np.asarray(delta,float)
    require(np.isfinite(times[reached]).all() and np.all(times[reached]>anchor[reached]),'Invalid later choice chronology')
    present=np.isfinite(next_disconnect)&(next_disconnect>0)
    require(np.all(next_disconnect[present]>anchor[present]),'Censor precedes the exposure anchor')
    # A decision exactly at the censor is outside the strictly prior risk window.
    eligible=reached&(~present|(times<next_disconnect))
    return np.where(eligible,grant,0).astype(float)

def run(a,run,k):
    p=receipt_path(a.project,a.matched_frame);expected=load(ROOT/'vendor/kac/authority/core_summary.json')['recipient_private_input_sha256']
    with heartbeat('Authenticate and load matched receipt frame'):
        require(sha(p)==expected,'Matched receipt input SHA256 differs from the frozen design')
        core=core_module();d=core.load_recipient_arrays(p);support=core.common_support_weights(d)
    complete=d['a1_90d_followup_eligible'].astype(bool)&support['eligible']
    require(int(complete.sum())==2110400,'Matched complete-window count changed')
    ix=np.flatnonzero(complete);X,names=core.model_controls(d,ix,state_conditioned=False)
    require(len(core.EXPOSURE_CONTROLS)==13,'Expected thirteen exposure-game variables (with frozen squares/missing indicators)')
    need=['cohort_row_id','exposure_game_utc_ms','exposure_anchor_utc_ms','recipient_next_disconnection_utc_ms']
    t=pq.ParquetFile(p).read(columns=need,use_threads=False)
    require(np.array_equal(t['cohort_row_id'].to_numpy(),d['cohort_row_id']),'Receipt chronology row identity changed')
    start=t['exposure_game_utc_ms'].to_numpy()[ix];anchor=t['exposure_anchor_utc_ms'].to_numpy()[ix]
    require(np.isfinite(start).all() and np.isfinite(anchor).all() and (anchor>=start).all(),'Invalid exposure times')
    reached=d['reached_fair_chooser_within_90d'][ix].astype(bool);grant=d['first_subsequent_kind_draw'][ix]
    y=np.where(reached,grant,0).astype(float)
    yc=censored_outcome(reached,grant,anchor,d['first_subsequent_delta_ms'][ix],t['recipient_next_disconnection_utc_ms'].to_numpy()[ix])
    D=d['received_mercy'][ix].astype(float);w=support['weights'][ix]
    base=[d['exposure_cell_code'][ix],d['exposure_month_code'][ix]];cluster=d['exposure_chooser_user_id'][ix]
    rows=[]
    for name,outcome,extra in [('baseline',y,[]),('start_hour',y,[start//3600000]),('last_move_hour',y,[anchor//3600000]),('censored_next_competitive_disconnection',yc,[])]:
        path=run/'PRIVATE/matched'/(name+'.json');ck=key([k,expected,name])
        if cached(path,ck):r=load(path)
        else:
            with heartbeat('Matched '+name):r=fit(outcome,D,X,w,base+extra,cluster,core,bool(extra))
            save(path,r);seal(path,ck)
        if name=='baseline':
            require(r['status']=='ESTIMATED' and abs(r['estimate']-.399)<.00051 and abs(r['se']-.058)<.00051,'Matched zero-coded baseline does not reproduce 0.399 (0.058) at published precision')
        rows.append(dict(specification=name,units='percentage points',**r))
        csv_out(run/'report/matched_zero_coded_sensitivity.csv',rows)
    save(run/'report/matched_model.json',dict(input_sha256=expected,controls=names,weight_rule='Frozen ATT cell weights; unchanged across four rows',
         sample='2110400 complete 90-day windows; original certified matched-design account convention',
         censor_rule='All baseline exposures retained. First later competitive grant counts only strictly before the next competitive disconnection; no qualifying choice is zero.',
         exposure_time='Last-move time is the frozen proxy, not an observed claim-click timestamp'))
