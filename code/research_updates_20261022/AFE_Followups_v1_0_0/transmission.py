"""Cumulative recipient responses on the reviewed, nonoverlapping IV cohort."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from common import *
sys.path.insert(0,str(PKG/'vendor'))
import expanded_stats as es
import followup_stats as fs
import iv_numerics as num
import comparison_core as cmp

def arrays(t):return {name:t[name].combine_chunks().to_numpy(zero_copy_only=False) for name in t.column_names}

def outcome_sql():
    terms=[]
    for h in (7,30,90):
        within=f'p.api_last_move_at_ms<=q.anchor_ms+{h*DAY}'
        for state,condition in [('competitive','p.fair_competitive'),('clearly_worse','p.clearly_worse')]:
            terms += [f'count(*) FILTER(WHERE {within} AND {condition})::BIGINT AS opportunities_{state}_{h}',
                      f'count(*) FILTER(WHERE {within} AND {condition} AND p.kind_draw)::BIGINT AS grants_{state}_{h}']
    terms.append('''arg_min(struct_pack(gid:=p.game_id,t:=p.api_last_move_at_ms,y:=p.kind_draw),
         struct_pack(t:=p.api_last_move_at_ms,ord:=p.archive_ordinal,gid:=p.game_id)) FILTER(WHERE p.fair_competitive) AS first_competitive''')
    return '''SELECT q.row_id,'''+','.join(terms)+''' FROM q LEFT JOIN panel p
      ON p.chooser_user_id=q.recipient_id
      AND p.api_last_move_at_ms>q.anchor_ms AND p.api_last_move_at_ms<=q.anchor_ms+7776000000
      AND p.utc_ms>q.anchor_ms AND p.disconnected_user_id<>q.opponent_id AND p.game_id<>q.game_id
      GROUP BY q.row_id'''

def build_followup(c,inputs,root):
    c.execute('CREATE OR REPLACE VIEW q AS SELECT * FROM '+parq([inputs['iv']]))
    require(c,'q',['row_id','recipient_id','opponent_id','game_id','anchor_ms','archive_start_ms','received','y','reached','outcome_gid','outcome_t'])
    n,uniq,bad=c.execute(f'''SELECT count(*),count(DISTINCT row_id),count(*) FILTER(WHERE NOT complete90 OR anchor_ms+{90*DAY}>={PANEL_END}) FROM q''').fetchone()
    if n!=uniq or bad:raise RuntimeError('Invalid complete-window IV cohort')
    log('Joining later opportunities to the 90-day-spaced exposure cohort')
    copy(c,outcome_sql(),root/'future.parquet')
    c.execute('CREATE OR REPLACE VIEW future AS SELECT * FROM '+parq([root/'future.parquet']))
    bridge=c.execute('''SELECT count(*) n,
      count(*) FILTER(WHERE q.reached IS DISTINCT FROM (f.first_competitive IS NOT NULL)) reach_errors,
      count(*) FILTER(WHERE q.y IS DISTINCT FROM coalesce(f.first_competitive.y,FALSE)) outcome_errors,
      count(*) FILTER(WHERE q.reached AND (q.outcome_gid IS DISTINCT FROM f.first_competitive.gid OR q.outcome_t IS DISTINCT FROM f.first_competitive.t)) first_event_errors
      FROM q JOIN future f USING(row_id)''').fetchdf().to_dict('records')[0]
    js(root/'public/outcome_bridge.json',bridge)
    if any(bridge[k] for k in ('reach_errors','outcome_errors','first_event_errors')):raise RuntimeError('New follow-up does not reproduce the reviewed IV next-choice outcome; no estimates published')
    # Exposure row carries the contemporaneous account identifier; no guessed numeric-to-name mapping.
    c.execute('''CREATE OR REPLACE TABLE qnames AS SELECT q.row_id,p.disconnected_username_norm AS username_norm
      FROM q JOIN panel p ON q.game_id=p.game_id AND q.recipient_id=p.disconnected_user_id''')
    if c.execute('SELECT count(*),count(DISTINCT row_id) FROM qnames').fetchone()!=(n,n):raise RuntimeError('Exposure-to-panel identity join is not one-to-one')
    if 'snapshot' in inputs:
        from static_analyses import profile_view
        profile_view(c,inputs)
        profile='''LEFT JOIN qnames n USING(row_id) LEFT JOIN profiles pr ON n.username_norm=pr.username_norm'''
        age=f'''CASE WHEN pr.returned AND pr.created_at_ms>0 AND pr.created_at_ms<=q.archive_start_ms
                 THEN (q.archive_start_ms-pr.created_at_ms)/{DAY}.0 END AS account_age_days'''
    else:profile='';age='NULL::DOUBLE AS account_age_days'
    history=''
    prior='NULL::BIGINT AS prior_observed_opportunities,NULL::BIGINT AS prior_observed_grants'
    if 'history' in inputs:
        log('Computing strictly prior all-source opportunity counts')
        history_hashes=[]
        with heartbeat('Authenticating and accumulating all-source histories'):
            for p in inputs['history']:history_hashes.append(check_file(p))
            js(root/'history_inputs_PRIVATE.json',history_hashes)
            c.execute('CREATE OR REPLACE VIEW broad AS SELECT * FROM '+parq(inputs['history']))
            require(c,'broad',['chooser_user_id','api_last_move_at_ms','kind_draw'])
            copy(c,'''SELECT chooser_user_id,api_last_move_at_ms AS t,
               count(*) OVER(PARTITION BY chooser_user_id ORDER BY api_last_move_at_ms RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS prior_n,
               sum(kind_draw::BIGINT) OVER(PARTITION BY chooser_user_id ORDER BY api_last_move_at_ms RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS prior_g
               FROM broad SEMI JOIN (SELECT DISTINCT recipient_id FROM q) users ON chooser_user_id=recipient_id''',root/'history_prefix.parquet')
        c.execute('CREATE OR REPLACE VIEW prefix AS SELECT * FROM '+parq([root/'history_prefix.parquet']))
        c.execute('''CREATE OR REPLACE TABLE h AS SELECT q.row_id,coalesce(h.prior_n,0) prior_n,coalesce(h.prior_g,0) prior_g
             FROM q ASOF LEFT JOIN prefix h ON q.recipient_id=h.chooser_user_id AND q.archive_start_ms>h.t''')
        history='LEFT JOIN h USING(row_id)';prior='h.prior_n AS prior_observed_opportunities,h.prior_g AS prior_observed_grants'
    copy(c,'SELECT q.*,f.* EXCLUDE(row_id),'+age+','+prior+' FROM q JOIN future f USING(row_id) '+profile+' '+history+' ORDER BY q.row_id',root/'analysis.parquet')
    return bridge

def fit_responses(d,outcomes,label):
    n=len(d['row_id']);received=np.asarray(d['received'],float)
    base=dict(group=label,rows=n,receipts=int(received.sum()),inference='shared_account_OR_date_CR0',historical_instrument_treated_as_fixed=True)
    if n<2000 or min(received.sum(),n-received.sum())<20:
        return [dict(base,outcome=o,supported=False,reason='INSUFFICIENT_GROUP_SUPPORT') for o in outcomes]
    xs,names,_,_,groups,missing=es.controls(d,True)
    raw=np.column_stack(xs+[d['adjusted_7d'],received]+[outcomes[o] for o in outcomes])
    residual,info=num.partial_out(raw,groups,len(names));del raw,xs
    z,t=residual[:,0],residual[:,1]
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1])
    meat=lambda s:fs.shared_meat(s,codes,True)
    first=fs.ols(t,z,meat);output=[]
    for k,o in enumerate(outcomes):
        y=residual[:,2+k];fit=es.iv_result(y,t,z,meat);rf=fit.pop('reduced_form',{});fit.pop('first_stage',None)
        binary=o.startswith('next_grant') or o.startswith('any_grant')
        scale=100 if binary else 1
        row=dict(base,outcome=o,units='percentage_points' if binary else 'additional_events',
                 control_mean=float(np.mean(outcomes[o][received==0])),
                 first_stage_pp_per_SD=100*REFERENCE_SD*first.get('coefficient',np.nan),
                 first_stage_F=first.get('wald_F_one_df'),
                 reduced_form_per_SD=scale*REFERENCE_SD*rf.get('coefficient',np.nan),**info,**fit)
        for old,new in [('iv_coefficient','effect'),('iv_standard_error','se'),('iv_ci_low','ci_low'),('iv_ci_high','ci_high')]:
            if old in fit:row[new]=scale*fit[old]
        # The vendored routine labels AR intervals in pp even for count outcomes; convert explicitly.
        intervals=row.pop('AR95_intervals_pp',None)
        if intervals is not None:row['AR95_intervals_outcome_units']=[[v/100 if isinstance(v,(float,int)) and not binary else v for v in interval] for interval in intervals]
        output.append(row)
    return output

def transmission(inputs,root,workers,memory):
    if 'iv' not in inputs:raise FileNotFoundError('Reviewed expanded IV cohort is unavailable')
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    c=connection(root,workers,memory);view_panel(c,inputs)
    build_followup(c,inputs,root)
    c.execute('CREATE OR REPLACE VIEW analysis AS SELECT * FROM '+parq([root/'analysis.parquet']))
    csv(c,'''SELECT received,count(*) n,count(*) FILTER(WHERE account_age_days IS NOT NULL) known_age,
        count(*) FILTER(WHERE account_age_days<=30) age_at_most_30_days,
        count(*) FILTER(WHERE prior_observed_opportunities=0) no_prior_observed_opportunities
        FROM analysis GROUP BY received''',pub/'experience_coverage.csv')
    table=pq.read_table(root/'analysis.parquet');data=arrays(table.drop(['first_competitive']));del table
    # These groups overlap across classification families; they are not mutually exclusive treatment arms.
    age=np.asarray(data['account_age_days'],float);nprior=np.asarray(data['prior_observed_opportunities'],float);gprior=np.asarray(data['prior_observed_grants'],float)
    masks={
      'all':np.ones(len(age),bool),
      'recent_90d_no_competitive_opportunities':data['fair_90']==0,
      'recent_90d_opportunities_no_grants':(data['fair_90']>0)&(data['kind_90']==0),
      'recent_90d_prior_granters':data['kind_90']>0,
      'observed_no_prior_opportunity':nprior==0,
      'observed_prior_opportunities_no_grants':(nprior>0)&(gprior==0),
      'observed_prior_granters':gprior>0,
      'known_account_age_at_most_30d':np.isfinite(age)&(age<=30),
      'known_account_age_31_to_365d':np.isfinite(age)&(age>30)&(age<=365),
      'known_account_age_over_365d':np.isfinite(age)&(age>365)}
    outcomes={}
    for h in (7,30,90):
        outcomes[f'next_grant_competitive_{h}']=np.asarray(data['y'],float)*(np.asarray(data['outcome_t'])<=np.asarray(data['anchor_ms'])+h*DAY)
        outcomes[f'any_grant_competitive_{h}']=(data[f'grants_competitive_{h}']>0).astype(float)
        for state in ('competitive','clearly_worse'):
            for kind in ('grants','opportunities'):outcomes[f'{kind}_{state}_{h}']=np.asarray(data[f'{kind}_{state}_{h}'],float)
    all_results=[];groupcounts=[]
    for label,mask in masks.items():
        groupcounts.append(dict(group=label,rows=int(mask.sum()),receipts=int(np.asarray(data['received'])[mask].sum())))
        selected=outcomes if label=='all' else {k:v for k,v in outcomes.items() if k in ('next_grant_competitive_90','grants_competitive_90','opportunities_competitive_90')}
        if not mask.any():
            all_results.extend(dict(group=label,outcome=k,supported=False,reason='NO_OBSERVED_GROUP_MEMBERS') for k in selected);continue
        ds={k:np.asarray(v)[mask] for k,v in data.items()}
        ys={k:v[mask] for k,v in selected.items()}
        log(f'Transmission group {label}: {int(mask.sum()):,} exposures')
        with heartbeat('IV response estimates'):fits=fit_responses(ds,ys,label)
        js(root/(label+'_fits.json'),fits);all_results+=fits;del ds,ys
    fs.holm(all_results,field='iv_p_value_asymptotic',out='p_Holm_declared_transmission_family')
    js(pub/'transmission_estimates.json',all_results);pd.DataFrame(all_results).to_csv(pub/'transmission_estimates.csv',index=False)
    pd.DataFrame(groupcounts).to_csv(pub/'group_support.csv',index=False)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7.5,4.5))
    for state,label in [('competitive','Competitive opportunities'),('clearly_worse','Clearly-worse opportunities')]:
        rs=[r for r in all_results if r.get('group')=='all' and r.get('outcome','').startswith('grants_'+state+'_') and r.get('supported')]
        if rs:
            h=[int(r['outcome'].rsplit('_',1)[1]) for r in rs];ax.errorbar(h,[r['effect'] for r in rs],yerr=[1.96*r['se'] for r in rs],marker='o',capsize=3,label=label)
    ax.axhline(0,color='grey',lw=.7);ax.set(xlabel='Days after receipt',ylabel='Additional grants per receipt',title='Cumulative recipient response: IV estimates')
    if ax.lines:ax.legend(frameon=False)
    fig.tight_layout();fig.savefig(pub/'cumulative_transmission.png',dpi=180);plt.close(fig)
    (pub/'INTERPRETATION.md').write_text('All outcomes preserve the reviewed 90-day-spaced, complete-history and complete-follow-up IV exposure cohort. Counts are zero for complete-window nonreachers. Future games must start after the exposure timing proxy, end within the horizon, and face a different opponent. Administrative censoring is not coded zero. Estimates inherit conditional assignment, exclusion and monotonicity assumptions; subgroup comparisons are exploratory and need subgroup first stages. Counts include intervening receipts and own-action feedback: these are total recipient responses, not isolated impulse parameters. Opportunity counts and giving counts are separate outcomes; a ratio is not a causal willingness parameter. Known account-age groups use a selected current-profile sample. No prior observed opportunity is not proof of first-ever familiarity; recent non-granters are not lifetime non-granters. These estimates do not identify psychological norm learning or a multigeneration multiplier. All tests are exploratory; the within-package Holm family is not preregistration.\n')
    c.close();return dict(status='COMPLETE_EXPLORATORY_IV_EXTENSION',groups=groupcounts,estimate_rows=len(all_results))

def iv_sensitivity(inputs,root,workers,memory):
    """Known-direct-effect sensitivity with re-estimated robust variance at each delta."""
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    reviewed=read(PKG/'evidence/expanded_estimates.json')
    if isinstance(reviewed,dict):reviewed=reviewed['estimates']
    primary=[r for r in reviewed if r.get('specification')=='main90_pooled']
    fsrow=next(r for r in primary if r.get('estimator')=='first_stage_per_reference_SD')
    rfrow=next(r for r in primary if r.get('estimator')=='RF_kindness_per_reference_SD')
    placebo=next(r for r in reviewed if r.get('specification')=='ordinary90_placebo' and r.get('outcome')=='y')
    first=fsrow['coefficient_pp']/100;rf=rfrow['coefficient_pp']
    planning=[]
    for margin in (.005,.01,.015,abs(rf)):
        # Approximate 80% power TOST at true zero: Phi(margin/se-z_.95)-Phi(-margin/se+z_.95)=.8.
        target=margin/(1.6448536269514722+1.2815515655446004)
        planning.append(dict(equivalence_margin_pp_per_SD=margin,target_SE_pp=target,
          current_SE_pp=placebo['standard_error_pp'],independence_scaling_total_rows=math.ceil(placebo['n']*(placebo['standard_error_pp']/target)**2),
          assumption='inverse_sqrt_N; clustered dependence may prevent this gain; not a retrieval ETA'))
    pd.DataFrame(planning).to_csv(pub/'ordinary_placebo_precision_plan.csv',index=False)
    js(pub/'reviewed_scale.json',dict(first_stage_pp_per_SD=fsrow['coefficient_pp'],reduced_form_pp_per_SD=rf,
         direct_effect_erasing_point_estimate_pp_per_SD=rf,ordinary_placebo=placebo))
    grid=np.unique(np.r_[np.linspace(-.04,.04,81),rf,0.])
    rows=[]
    if 'iv' in inputs:
        d=arrays(pq.read_table(inputs['iv']));xs,names,_,_,groups,_=es.controls(d,True)
        residual,info=num.partial_out(np.column_stack(xs+[d['adjusted_7d'],np.asarray(d['received'],float),np.asarray(d['y'],float)]),groups,len(names));del xs
        z,t,y=residual.T;codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda s:fs.shared_meat(s,codes,True)
        zz=float(z@z);zd=float(z@t);zy=float(z@y)
        if abs(zd)<1e-15:raise RuntimeError('No first-stage covariance for sensitivity analysis')
        beta0=zy/zd;per_delta=zz/(100*REFERENCE_SD*zd)
        s0=z*(y-beta0*t);sdelta=z*(per_delta*t-z/(100*REFERENCE_SD))
        V=meat(np.column_stack([s0,sdelta]))/zd**2
        for delta in grid:
            # Exact residual-score covariance polynomial; avoids rescanning the same 2.7M rows 82 times.
            beta=beta0-delta*per_delta;var=V[0,0]+2*delta*V[0,1]+delta*delta*V[1,1]
            row=dict(direct_effect_pp_per_SD=delta,effect_pp=100*beta,supported=bool(var>0 and np.isfinite(var)))
            if row['supported']:
                se=math.sqrt(var);row.update(se_pp=100*se,ci_low_pp=100*(beta-fs.CRIT*se),ci_high_pp=100*(beta+fs.CRIT*se))
            rows.append(row)
        zero=next(r for r in rows if r['direct_effect_pp_per_SD']==0)
        old=next(r for r in primary if r.get('estimator')=='2SLS')
        if abs(zero['effect_pp']-old['iv_coefficient_pp'])>1e-7 or abs(zero['se_pp']-old['iv_standard_error_pp'])>1e-7:raise RuntimeError('IV sensitivity zero-delta bridge failed')
        status='COMPLETE_WITH_CONDITIONAL_ROBUST_INTERVALS'
    else:
        rows=[dict(direct_effect_pp_per_SD=v,effect_pp=(rf-v)/first,supported=True,intervals_available=False) for v in grid]
        status='POINT_SENSITIVITY_ONLY_MISSING_PRIVATE_IV_DATA'
    pd.DataFrame(rows).to_csv(pub/'exclusion_sensitivity.csv',index=False)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    d=pd.DataFrame(rows).sort_values('direct_effect_pp_per_SD');fig,ax=plt.subplots(figsize=(7.5,4.5))
    ax.plot(d.direct_effect_pp_per_SD,d.effect_pp)
    if 'ci_low_pp' in d:ax.fill_between(d.direct_effect_pp_per_SD,d.ci_low_pp,d.ci_high_pp,alpha=.2)
    ax.axhline(0,color='grey',lw=.7);ax.axvline(0,color='grey',lw=.7)
    ax.set(xlabel='Assumed direct effect (pp per instrument SD)',ylabel='Receipt effect (percentage points)',title='Sensitivity to an exclusion violation')
    fig.tight_layout();fig.savefig(pub/'exclusion_sensitivity.png',dpi=180);plt.close(fig)
    (pub/'INTERPRETATION.md').write_text('Each direct-effect value is assumed known, additive and linear in the same historical score. Intervals condition on that value; they do not estimate or integrate uncertainty about the violation. Zero is exact exclusion. The tipping value is a calibration, not evidence that such a channel exists. The ordinary-game placebo has a different population and is not automatically a bound on the direct effect. Precision planning does not expand or re-estimate the ordinary-game sample.\n')
    return dict(status=status,grid_points=len(rows),direct_effect_tipping_pp_per_SD=rf)
