"""Receipt heterogeneity and horizon diagnostics on the authenticated IV cohort.

Separate from the switching model: no instrument is inserted into a logit.
All tests are exploratory; previous aggregate/subgroup results were inspected.
"""
from pathlib import Path
import sys,json,math
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from util import *
from prepare_sequences import DAY,END
from model_analysis import holm
PKG=Path(__file__).resolve().parent
sys.path.insert(0,str(PKG/'vendor_iv'))
import expanded_stats as es
import followup_stats as fs
import comparison_core as cmp
import iv_numerics as num


def resolve_iv(project):
    p=Path(project)/'derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet'
    if not p.exists():return None
    expected=json.loads((PKG/'evidence/expanded_summary.json').read_text())
    row=next(r for r in expected['analysis_validation']['files'] if r['path']=='spaced90.parquet')
    require(p.stat().st_size==row['bytes'] and sha256_file(p)==row['sha256'],'Reviewed IV cohort has changed')
    require(pq.ParquetFile(p).metadata.num_rows==2682330,'Unexpected IV cohort size')
    return p


def future_sql():
    terms=[]
    for h in (7,30,90):
        for label,condition in [('competitive','p.board>=2'),('lost','p.board=0')]:
            cond=f'p.api_last_move_at_ms<=q.anchor_ms+{h*DAY} AND {condition}'
            terms.extend([f'count(p.game_id) FILTER(WHERE {cond})::BIGINT n_{label}_{h}',
              f'count(p.game_id) FILTER(WHERE {cond} AND p.y=1)::BIGINT g_{label}_{h}'])
    terms.append('''arg_min(struct_pack(gid:=p.game_id,t:=p.api_last_move_at_ms,y:=(p.y=1)),
      struct_pack(t:=p.api_last_move_at_ms,ord:=p.archive_ordinal,gid:=p.game_id)) FILTER(WHERE p.board>=2) AS first_choice''')
    return '''SELECT q.row_id,'''+','.join(terms)+f''' FROM iv q LEFT JOIN source p
      ON p.chooser_user_id=q.recipient_id AND p.api_last_move_at_ms>q.anchor_ms
      AND p.api_last_move_at_ms<=q.anchor_ms+{90*DAY} AND p.utc_ms>q.anchor_ms
      AND p.disconnected_user_id<>q.opponent_id AND p.game_id<>q.game_id GROUP BY q.row_id'''


def build(db,path,private,report,identity):
    db.execute(f'CREATE OR REPLACE VIEW iv AS SELECT * FROM read_parquet({qs(path)})')
    n,u,bad=db.execute(f'''SELECT count(*),count(DISTINCT row_id),count(*) FILTER(WHERE NOT complete90 OR anchor_ms+{90*DAY}>={END}) FROM iv''').fetchone()
    require(n==u and bad==0,'Invalid reviewed IV completeness or identifiers')
    dest=private/'iv_analysis.parquet'
    if not ready(dest,identity):
        future=private/'iv_future.parquet'
        if not ready(future,identity):
            log('Building cumulative receipt outcomes on the complete 90-day cohort')
            copy_query(db,future_sql(),future,identity)
        db.execute(f'CREATE OR REPLACE VIEW future AS SELECT * FROM read_parquet({qs(future)})')
        bridge=records(db,'''SELECT count(*) n,
          count(*) FILTER(WHERE q.reached IS DISTINCT FROM (f.first_choice IS NOT NULL)) reach_errors,
          count(*) FILTER(WHERE q.y IS DISTINCT FROM coalesce(f.first_choice.y,FALSE)) outcome_errors,
          count(*) FILTER(WHERE q.reached AND (q.outcome_gid IS DISTINCT FROM f.first_choice.gid OR q.outcome_t IS DISTINCT FROM f.first_choice.t)) event_errors
          FROM iv q JOIN future f USING(row_id)''')[0]
        atomic_json(report/'IV_OUTCOME_BRIDGE.json',bridge)
        require(not any(bridge[k] for k in ['reach_errors','outcome_errors','event_errors']),'Receipt outcome reconstruction does not reproduce reviewed cohort')
        prefix=private/'iv_prior_prefix.parquet'
        if not ready(prefix,identity):
            log('Accumulating strictly prior main-panel choice histories for receipt subgroups')
            copy_query(db,'''WITH counts AS (
              SELECT chooser_user_id AS chooser,api_last_move_at_ms AS t,count(*)::BIGINT n,sum(y)::BIGINT g
              FROM source SEMI JOIN (SELECT DISTINCT recipient_id FROM iv) q ON chooser_user_id=q.recipient_id
              WHERE api_last_move_at_ms>0 GROUP BY chooser_user_id,api_last_move_at_ms)
              SELECT chooser,t,sum(n) OVER(PARTITION BY chooser ORDER BY t)::BIGINT prior_n,
                sum(g) OVER(PARTITION BY chooser ORDER BY t)::BIGINT prior_g FROM counts''',prefix,identity)
        copy_query(db,f'''SELECT q.*,f.* EXCLUDE(row_id,first_choice),
          coalesce(h.prior_n,0)::BIGINT prior_main_n,coalesce(h.prior_g,0)::BIGINT prior_main_g
          FROM iv q JOIN future f USING(row_id)
          ASOF LEFT JOIN read_parquet({qs(prefix)}) h ON q.recipient_id=h.chooser AND q.archive_start_ms>h.t
          ORDER BY q.row_id''',dest,identity)
    return dest


def fit_group(data,mask,outcomes,label):
    idx=np.flatnonzero(mask);n=len(idx)
    received=np.asarray(data['received'],float)[mask]
    if n<2000 or min(received.sum(),n-received.sum())<20:
        return [dict(group=label,outcome=k,supported=False,reason='INSUFFICIENT_GROUP_SUPPORT',rows=n) for k in outcomes],None,idx
    d={k:np.asarray(v)[mask] for k,v in data.items()}
    xs,names,_,_,groups,missing=es.controls(d,True)
    raw=np.column_stack(xs+[d['adjusted_7d'],received]+[v[mask] for v in outcomes.values()]);del xs
    res,info=num.partial_out(raw,groups,len(names));del raw
    z,t=res[:,0],res[:,1];den=float(z@t)
    codes=cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda s:fs.shared_meat(s,codes,True)
    first=fs.ols(t,z,meat);rows=[];scores=[]
    for j,name in enumerate(outcomes):
        y=res[:,j+2];fit=es.iv_result(y,t,z,meat)
        factor=100. if name=='next_grant_90' else 1.
        row=dict(group=label,outcome=name,rows=n,receipts=int(received.sum()),
             control_mean=float(outcomes[name][mask][received==0].mean()),units='percentage_points' if factor==100 else 'additional_events',
             first_stage_F=first.get('wald_F_one_df'),first_stage_supported=first.get('supported',False),
             supported=fit.get('supported',False),reason=fit.get('reason'),
             effect=factor*fit.get('iv_coefficient',np.nan),SE=factor*fit.get('iv_standard_error',np.nan),
             p_value=fit.get('iv_p_value_asymptotic'),
             AR95_intervals=fit.get('AR95_intervals_pp'),AR95_units='percentage_points; divide by 100 for count outcomes',
             covariance='shared_account_OR_date_CR0',**info)
        rows.append(row)
        scores.append(z*(y-fit.get('iv_coefficient',0.)*t)/den*factor if abs(den)>1e-15 else np.zeros(n))
    return rows,np.column_stack(scores),idx


def run(db,path,private,report,identity,profile_path=None):
    if path is None:
        status=dict(status='NOT_RUN_MISSING_REVIEWED_IV_COHORT')
        atomic_json(report/'RECEIPT_STATUS.json',status);return status
    dest=build(db,path,private,report,identity)
    if profile_path is not None:
        from auxiliary_tests import profile_view
        profile_view(db,profile_path)
        table=db.execute(f'''SELECT a.*,
          CASE WHEN p.returned AND p.created_at_ms>0 AND p.created_at_ms<=a.archive_start_ms
               THEN (a.archive_start_ms-p.created_at_ms)/{DAY}.0 END AS known_age_days
          FROM read_parquet({qs(dest)}) a
          LEFT JOIN source s ON a.game_id=s.game_id AND a.recipient_id=s.disconnected_user_id
          LEFT JOIN profiles p ON s.disconnected_username_norm=p.username_norm ORDER BY a.row_id''').to_arrow_table()
        require(table.num_rows==pq.ParquetFile(dest).metadata.num_rows,'Profile-age join changed IV row count')
    else:table=pq.read_table(dest)
    data={k:table[k].combine_chunks().to_numpy(zero_copy_only=False) for k in table.column_names};del table
    outputs={'next_grant_90':np.asarray(data['y'],float)}
    for state in ('competitive','lost'):
        for kind in ('n','g'):
            outputs[f'{kind}_{state}_days_1_7']=np.asarray(data[f'{kind}_{state}_7'],float)
            outputs[f'{kind}_{state}_days_8_30']=np.asarray(data[f'{kind}_{state}_30'],float)-outputs[f'{kind}_{state}_days_1_7']
            outputs[f'{kind}_{state}_days_31_90']=np.asarray(data[f'{kind}_{state}_90'],float)-np.asarray(data[f'{kind}_{state}_30'],float)
    rows,scores,idx=fit_group(data,np.ones(len(data['row_id']),bool),outputs,'all')
    require(scores is not None,'Insufficient support in reviewed pooled IV cohort')
    pooled=rows[0]
    reviewed=json.loads((PKG/'evidence/expanded_estimates.json').read_text())
    if isinstance(reviewed,dict):reviewed=reviewed['estimates']
    old=next(r for r in reviewed if r.get('specification')=='main90_pooled' and r.get('estimator')=='2SLS')
    require(abs(pooled['effect']-old['iv_coefficient_pp'])<1e-7 and abs(pooled['SE']-old['iv_standard_error_pp'])<1e-7,'Original IV coefficient/covariance reproduction failed')
    codes=cmp.covariance_codes(data['recipient_id'],data['opponent_id'],data['archive_start_ms']//DAY)
    covariance=fs.shared_meat(scores,codes,True);contrasts=[];names=list(outputs)
    # Compare effects per day, not unequal cumulative horizons. Opportunity effects remain separate.
    for kind in ('n','g'):
        a=names.index(f'{kind}_competitive_days_1_7');b=names.index(f'{kind}_competitive_days_31_90')
        delta=rows[a]['effect']/7-rows[b]['effect']/60
        variance=covariance[a,a]/49+covariance[b,b]/3600-2*covariance[a,b]/420
        contrasts.append(contrast(f'{kind}_competitive_early_minus_late_effect_per_day',delta,variance))
    subgroup_scores={}
    prior_n=np.asarray(data['prior_main_n']);prior_g=np.asarray(data['prior_main_g'])
    groups={'prior_main_opportunities_no_grants':(prior_n>0)&(prior_g==0),
            'prior_main_granters':prior_g>0,'no_prior_main_opportunity':prior_n==0}
    if 'known_age_days' in data:
        age=np.asarray(data['known_age_days'],float)
        groups.update(known_age_at_most_30d=np.isfinite(age)&(age<=30),
          known_age_31_to_365d=np.isfinite(age)&(age>30)&(age<=365),
          known_age_over_365d=np.isfinite(age)&(age>365))
    supports=[]
    for label,mask in groups.items():
        log(f'Receipt subgroup {label}: {int(mask.sum()):,} exposures')
        result,sc,ix=fit_group(data,mask,{'next_grant_90':outputs['next_grant_90']},label)
        rows+=result;supports.append(dict(group=label,rows=int(mask.sum()),receipts=int(np.asarray(data['received'])[mask].sum())))
        if sc is not None and result[0]['supported']:
            full=np.zeros(len(mask));full[ix]=sc[:,0];subgroup_scores[label]=(result[0]['effect'],full)
    a='prior_main_granters';b='prior_main_opportunities_no_grants'
    if a in subgroup_scores and b in subgroup_scores:
        da,sa=subgroup_scores[a];dbeta,sb=subgroup_scores[b]
        var=float(fs.shared_meat(sa-sb,codes,True)[0,0])
        contrasts.append(contrast('prior_granters_minus_prior_non_granters_receipt_effect_pp',da-dbeta,var))
    else:contrasts.append(dict(test='prior_granters_minus_prior_non_granters_receipt_effect_pp',supported=False,reason='UNSUPPORTED_SUBGROUP',p_value=None))
    holm(rows,out='p_Holm_receipt_estimates');holm(contrasts,out='p_Holm_three_receipt_contrasts')
    # DataFrame handles heterogeneous diagnostic columns without dropping missing-status rows.
    pd.DataFrame(rows).to_csv(report/'receipt_IV_estimates.csv',index=False)
    pd.DataFrame(contrasts).to_csv(report/'receipt_IV_contrasts.csv',index=False)
    csv_write(report/'receipt_subgroup_support.csv',supports)
    status=dict(status='EXPLORATORY_IV_TESTS_COMPLETE',rows=len(data['row_id']),original_IV_reproduced=True,
       prior_history='Strictly before exposure game start; observed main-panel opportunities since November 2023, not lifetime or all-source history',
       timing='Inherits reviewed recorded-time proxy and follow-up rules',
       inference='Historical instrument treated as fixed; shared-account OR exposure-date CR0; subgroup first stages and null-moment AR sets retained',
       limits=['Heterogeneity is not unique to a gate','Later receipts and own actions remain in the total response',
       'Window effects on grant counts and opportunity counts are distinct; no causal conditional-rate ratio',
        'Known-age subgroups use a selected current-profile sample; missing age is not zero age',
        'No statement of permanent conversion','Prior results have been inspected; this is not independent confirmation'])
    atomic_json(report/'RECEIPT_STATUS.json',status);return status


def contrast(name,delta,variance):
    if not np.isfinite(variance) or variance<=0:return dict(test=name,effect=float(delta),supported=False,reason='NONPOSITIVE_COVARIANCE_NOT_REPAIRED',p_value=None)
    se=math.sqrt(variance)
    return dict(test=name,effect=float(delta),SE=se,ci_low=float(delta-1.959964*se),ci_high=float(delta+1.959964*se),
                p_value=math.erfc(abs(delta/se)/math.sqrt(2)),supported=True)
