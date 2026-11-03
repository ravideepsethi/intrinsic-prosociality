"""Fixed definitions and numerical checks for full-frame comparison diagnostics."""
from __future__ import annotations
import math
import numpy as np
import preliminary_core as old
import iv_numerics as num

DAY=old.DAY
PANEL_START=int(old.STARTS[0])
PANEL_END=old.PANEL_END
PILOT_SD=old.PILOT_Z_SD
PILOT_RF_PP=100*old.PILOT_RF
NARROW=old.NARROW
BROAD=old.BROAD
SPECS=(
    dict(name='primary_7d_floor5',lag=7,floor=5,broad=False,history=False,history_common=False),
    dict(name='draws_7d_floor5',lag=7,floor=5,broad=True,history=False,history_common=False),
    dict(name='floor1_7d',lag=7,floor=1,broad=False,history=False,history_common=False),
    dict(name='floor10_7d',lag=7,floor=10,broad=False,history=False,history_common=False),
    dict(name='lag30_floor5',lag=30,floor=5,broad=False,history=False,history_common=False),
    dict(name='recipient_history_common_baseline',lag=7,floor=5,broad=False,history=False,history_common=True),
    dict(name='recipient_history_added',lag=7,floor=5,broad=False,history=True,history_common=True),
)


def history_supported(d,lag,floor):
    return (d[f'n_{lag}d']>=floor)&np.isfinite(d[f'expected_{lag}d'])&np.isfinite(d[f'adjusted_{lag}d'])


def classify_identity(required_ids,required_names,found_pairs):
    """Check both encodings. Absence in both is distinct from a verified mapping."""
    byid={};byname={};conflict_ids=set();conflict_names=set()
    def add(ident,name):
        if ident is None:
            if isinstance(name,str):conflict_names.add(name)
            return
        ident=int(ident)
        if ident in byid and byid[ident]!=name:conflict_ids.add(ident)
        else:byid[ident]=name
        if isinstance(name,str):
            if name in byname and byname[name]!=ident:conflict_names.add(name)
            else:byname[name]=ident
    # Requirements may themselves reveal inconsistent observed ID/name assignments.
    qid={};qname={}
    for ident,name in zip(required_ids,required_names):
        ident=int(ident)
        if ident in qid and qid[ident]!=name:conflict_ids.add(ident)
        if name in qname and qname[name]!=ident:conflict_names.add(name)
        qid[ident]=name;qname[name]=ident
    for pairs in found_pairs:
        for ident,name in pairs:add(ident,name)
    result=[]
    for ident,name in zip(required_ids,required_names):
        ident=int(ident)
        if (ident in conflict_ids or name in conflict_names or
            (ident in byid and byid[ident]!=name) or (name in byname and byname[name]!=ident)):
            result.append('CONFLICT')
        elif ident in byid and name in byname:result.append('MATCHED')
        elif ident not in byid and name not in byname:result.append('ABSENT_BOTH')
        else:result.append('INCOMPLETE')
    return np.asarray(result)


def later_outcomes(h,q,panel_start=PANEL_START,panel_end=PANEL_END):
    """Same first-other-opponent definition as the pilot, plus completeness/event keys."""
    n=len(q['sample_row'])
    result=dict(sample_row=q['sample_row'].copy(),complete90=q['anchor_ms']+90*DAY<panel_end,
        own_history_complete=q['archive_start_ms']-97*DAY>=panel_start,
        reached=np.zeros(n,bool),y=np.zeros(n,bool),outcome_t=np.full(n,-1,np.int64),
        outcome_start=np.full(n,-1,np.int64),outcome_opponent=np.full(n,-1,np.int64),
        outcome_gid=np.full(n,'',dtype='U8'),own_fair90=np.zeros(n,np.int64),own_kind90=np.zeros(n,np.int64),
        lead_present=np.zeros(n,bool),lead_y=np.zeros(n,bool),projection_person_present=np.zeros(n,bool))
    if np.any(q['anchor_ms']<q['archive_start_ms']):raise RuntimeError('Focal anchor precedes game start')
    if not len(h['j']):return result
    # A game archived near month end can have its last move after the archive boundary.
    # Such observed rows do not extend the certified follow-up window.
    if np.any((h['t']<panel_start)|(h['start']>h['t'])):
        raise RuntimeError('Projection timestamps precede the panel or are inconsistent')
    result['projection_person_present']=np.isin(q['recipient_id'],np.unique(h['j']))
    fair=np.flatnonzero(h['fair'])
    order=np.lexsort((h['gid'][fair],h['ord'][fair],h['t'][fair],h['j'][fair]));ix=fair[order]
    people=h['j'][ix]
    lo=np.searchsorted(people,q['recipient_id'],'left');hi=np.searchsorted(people,q['recipient_id'],'right')
    for k in range(n):
        if lo[k]==hi[k]:continue
        rows=ix[lo[k]:hi[k]];tt=h['t'][rows];anchor=q['anchor_ms'][k]
        a=np.searchsorted(tt,anchor,'right');b=np.searchsorted(tt,anchor+90*DAY,'right')
        for pos in range(a,b):
            e=rows[pos]
            if h['i'][e]==q['opponent_id'][k] or h['start'][e]<=anchor or h['gid'][e]==q['game_id'][k]:continue
            result['reached'][k]=True;result['y'][k]=h['y'][e]
            for output,input in [('outcome_t','t'),('outcome_start','start'),('outcome_opponent','i'),('outcome_gid','gid')]:
                result[output][k]=h[input][e]
            break
        end=q['archive_start_ms'][k]-7*DAY
        a=np.searchsorted(tt,end-90*DAY,'left');b=np.searchsorted(tt,end,'left')
        prior=rows[a:b]
        result['own_fair90'][k]=len(prior);result['own_kind90'][k]=int(h['y'][prior].sum())
        for e in prior[::-1]:
            if h['i'][e]!=q['opponent_id'][k]:
                result['lead_present'][k]=True;result['lead_y'][k]=h['y'][e];break
    return result


def verify_shared_events(d,mask):
    keep=mask&d['reached']
    gids=d['outcome_gid'][keep];recipient=d['recipient_id'][keep]
    if not len(gids):return dict(unique_future_events=0,maximum_event_reuse=0,shared_events_nested_in_recipient=True)
    if np.any(gids==''):raise RuntimeError('Reached outcome lacks game ID')
    order=np.argsort(gids);g=gids[order];i=recipient[order]
    if np.any((g[1:]==g[:-1])&(i[1:]!=i[:-1])):raise RuntimeError('One future choice was assigned to different recipients')
    _,counts=np.unique(g,return_counts=True)
    return dict(unique_future_events=len(counts),maximum_event_reuse=int(counts.max()),shared_events_nested_in_recipient=True)


def residualize(d,mask,lag,outcomes,with_history=False):
    take={k:np.asarray(d[k])[mask] for k in ('recipient_rating','opponent_rating','month_code','tc_base_s','tc_inc_s',
        'archive_start_ms',f'n_{lag}d',f'counterparts_{lag}d',f'expected_{lag}d',f'adjusted_{lag}d')}
    controls=[];names=[]
    def add(name,v):
        v=np.asarray(v,float)
        if not np.isfinite(v).all():raise RuntimeError('Unavailable model control: '+name)
        sd=float(v.std());controls.append((v-v.mean())/(sd if sd>1e-12 else 1));names.append(name)
    ir=take['recipient_rating'];jr=take['opponent_rating'];gap=(jr-ir)/100
    add('recipient_rating',ir);add('rating_gap',gap);add('rating_gap_square',gap*gap);add('abs_rating_gap',abs(gap))
    add('log_opponent_prior_decisions',np.log1p(take[f'n_{lag}d']))
    add('log_opponent_prior_counterparts',np.log1p(take[f'counterparts_{lag}d']))
    add('opponent_history_expected_rate',take[f'expected_{lag}d'])
    if with_history:
        if not np.all(d['own_history_complete'][mask]):raise RuntimeError('Recipient history is truncated')
        add('log_recipient_prior_fair',np.log1p(d['own_fair90'][mask]))
        add('recipient_prior_kind_indicator',d['own_kind90'][mask]>0)
    _,cell=num.factor(take['month_code'],take['tc_base_s'],take['tc_inc_s'],np.floor((ir+jr)/200).astype(np.int64))
    day=take['archive_start_ms']//DAY;hour=(take['archive_start_ms']//3600000)%168
    matrix=np.column_stack(controls+[take[f'adjusted_{lag}d']]+[np.asarray(d[y])[mask].astype(float) for y in outcomes])
    res,info=num.partial_out(matrix,[cell,day,hour],len(controls))
    return res,dict(assignment_cells=len(np.unique(cell)),continuous_controls=names,
        controls='pregame_export_W_common',unavailable_controls=['pregame_RD','all_game_prior_30d_volume','internal_conduct_category'],**info)


def covariance_codes(i,j,date):
    i=np.asarray(i,np.int64);j=np.asarray(j,np.int64);date=np.asarray(date,np.int64)
    if np.any(i==j):raise RuntimeError('Self pair in covariance calculation')
    low,high=np.minimum(i,j),np.maximum(i,j)
    return dict(accounts=np.unique(np.r_[i,j],return_inverse=True)[1],
        pairs=num.factor(low,high)[1],dates=np.unique(date,return_inverse=True)[1],
        account_dates=num.factor(np.r_[i,j],np.r_[date,date])[1],pair_dates=num.factor(low,high,date)[1])


def covariance_meat(score,codes,withdate):
    def sq(s,key):
        sums=np.bincount(codes[key],weights=s);return float(sums@sums)
    ss=np.r_[score,score]
    meat=sq(ss,'accounts')-sq(score,'pairs')
    if withdate:meat+=sq(score,'dates')-sq(ss,'account_dates')+sq(score,'pair_dates')
    return meat


def fit(y,z,codes,withdate,outcome_mean,equivalence=False):
    if not np.isfinite(y).all() or not np.isfinite(z).all():raise RuntimeError('Nonfinite regression residuals')
    den=float(z@z);native=math.sqrt(den/len(z))
    if native<1e-8:return dict(supported=False,reason='NO_RESIDUAL_SCORE_VARIATION',native_residual_score_sd=native)
    beta=float(z@y)/den;residual=y-beta*z;v=covariance_meat(z*residual,codes,withdate)/den**2
    ans=dict(coefficient_per_unit_score=beta,coefficient_pp_per_pilot_SD=100*beta*PILOT_SD,
        coefficient_pp_per_native_SD=100*beta*native,native_residual_score_sd=native,
        pilot_score_sd=PILOT_SD,reference_IV_RF_pp=PILOT_RF_PP,exclusion_certified=False,
        historical_scores_treated_as_fixed=True)
    if not math.isfinite(v) or v<=0:return dict(ans,supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
    se=math.sqrt(v);scale=100*PILOT_SD;crit95=1.959963984540054;crit90=1.6448536269514722
    ans.update(supported=True,standard_error_pp_per_pilot_SD=scale*se,
        ci95_low_pp_per_pilot_SD=scale*(beta-crit95*se),ci95_high_pp_per_pilot_SD=scale*(beta+crit95*se),
        ci90_low_pp_per_pilot_SD=scale*(beta-crit90*se),ci90_high_pp_per_pilot_SD=scale*(beta+crit90*se),
        p_value_asymptotic=math.erfc(abs(beta/se)/math.sqrt(2)),
        MDE80_pp_per_pilot_SD=scale*(crit95+.8416212335729143)*se,
        variance_correction='CR0',inference='normal_approximation_conditional_on_recorded_history')
    ans['MDE80_percent_of_outcome_mean']=ans['MDE80_pp_per_pilot_SD']/outcome_mean if outcome_mean>0 else None
    if equivalence:
        for margin in (.015,.0075):
            native_margin=margin/scale
            p=max(.5*math.erfc((beta+native_margin)/se/math.sqrt(2)),.5*math.erfc((native_margin-beta)/se/math.sqrt(2)))
            ans[f'descriptive_equivalence_margin_{margin}_pp_p']=p
            ans[f'descriptive_ci90_inside_{margin}_pp']=(ans['ci90_low_pp_per_pilot_SD']>-margin and ans['ci90_high_pp_per_pilot_SD']<margin)
    return ans


def primary_holm(rows):
    """Two designated primary null tests; unsupported tests stay in the family."""
    selected=[r for r in rows if r.get('primary_test')]
    if len(selected)!=2:raise RuntimeError('Expected exactly two designated primary tests')
    ps=np.array([r.get('p_value_asymptotic',1.) if r.get('supported') else 1. for r in selected])
    order=np.argsort(ps);running=0.
    for rank,ix in enumerate(order):
        running=max(running,(2-rank)*ps[ix])
        selected[ix]['p_value_Holm_two_primary_tests']=min(1.,running) if selected[ix].get('supported') else None
        selected[ix]['primary_multiplicity_family_size']=2
