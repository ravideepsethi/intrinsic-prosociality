"""Frozen opportunity models, serialized contrasts, and explicit ply sensitivities."""
from __future__ import annotations
import hashlib, math
import numpy as np
import pandas as pd
from source import opportunity_models_cov_v100 as engine
from source import patron_stage10_common as common
from source import wave3b1_helpers as h

q=common.sql_string
PLY_CASE="""CASE WHEN p.ply_count IS NULL THEN 'missing'
 WHEN p.ply_count<=4 THEN '00_04' WHEN p.ply_count<=10 THEN '05_10'
 WHEN p.ply_count<=20 THEN '11_20' WHEN p.ply_count<=40 THEN '21_40'
 WHEN p.ply_count<=80 THEN '41_80' ELSE '81_plus' END"""


def cache_projection():
    return f"""p.chooser_username_norm::VARCHAR AS username_norm,
      p.month::VARCHAR AS month, {engine.speed_sql('p.api_speed')} AS speed_group,
      p.tournament_like_event::BOOLEAN AS tournament_like,
      p.engine_fairness_bin::VARCHAR AS fairness_bin,
      p.fair_competitive::BOOLEAN AS fair_competitive,
      p.clearly_worse::BOOLEAN AS clearly_worse,
      p.excluded_middle::BOOLEAN AS excluded_middle,
      p.draw_nonnegative::BOOLEAN AS favorable_draw,
      {engine.clock_bin_sql('p.chooser_clock_last_obs_s')} AS chooser_clock_bin,
      {engine.clock_bin_sql('p.disconnected_clock_last_obs_s')} AS disconnected_clock_bin,
      {engine.rating_gap_bin_sql('p.rating_gap')} AS rating_gap_bin,
      {PLY_CASE} AS ply_band"""


def build_cache(db,panel_paths,bridge,target):
    paths='['+','.join(q(p) for p in panel_paths)+']'
    db.execute(f"""COPY (
      WITH base AS (
        SELECT {cache_projection()},p.kind_draw::BOOLEAN AS kind_draw
        FROM read_parquet({paths},union_by_name=true,hive_partitioning=false) p
        SEMI JOIN (SELECT username_norm FROM read_parquet({q(bridge)}) WHERE returned) s
          ON p.chooser_username_norm=s.username_norm
      ) SELECT * EXCLUDE(kind_draw),count(*)::BIGINT AS opportunities,
         sum(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM base GROUP BY ALL ORDER BY username_norm,month,speed_group,fairness_bin,ply_band
    ) TO {q(target)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)""")
    qa=h.records(db,f"""WITH c AS (SELECT username_norm,sum(opportunities) n,sum(kind_draws) k
      FROM read_parquet({q(target)}) GROUP BY 1),s AS
      (SELECT username_norm,total_opps,total_kind_count FROM read_parquet({q(bridge)}) WHERE returned)
      SELECT count(*) accounts,coalesce(sum(n),0)::BIGINT opportunities,
        coalesce(sum(k),0)::BIGINT kind_draws,
        count(*) FILTER(WHERE n IS DISTINCT FROM total_opps OR k IS DISTINCT FROM total_kind_count
          OR c.username_norm IS NULL OR s.username_norm IS NULL) mismatches
      FROM c FULL JOIN s USING(username_norm)""")[0]
    if qa['mismatches']!=0: raise RuntimeError(f'Opportunity cache does not reproduce chooser histories: {qa}')
    qa['collapsed_rows']=int(db.execute(f'SELECT count(*) FROM read_parquet({q(target)})').fetchone()[0])
    return qa


def model_specs():
    desert=[('patron','patron')]
    for level,alias in [('disconnected_better','disconnected_better'),('roughly_equal','roughly_equal'),
                        ('modestly_worse_excluded','modestly_worse'),('clearly_worse','clearly_worse')]:
        desert.append((f"(fairness_bin={q(level)})::INTEGER",'eval_'+alias))
    for level,alias in [('disconnected_better','disconnected_better'),('roughly_equal','roughly_equal'),
                        ('modestly_worse_excluded','modestly_worse'),('clearly_worse','clearly_worse')]:
        desert.append((f"patron*(fairness_bin={q(level)})::INTEGER",'patron_x_eval_'+alias))
    price=[('patron','patron'),('favorable_draw::INTEGER','favorable_draw'),
           ('patron*favorable_draw::INTEGER','patron_x_favorable_draw')]
    triple=[('patron','patron'),('fair_competitive::INTEGER','fair_state'),
      ('favorable_draw::INTEGER','favorable_draw'),('patron*fair_competitive::INTEGER','patron_x_fair'),
      ('patron*favorable_draw::INTEGER','patron_x_favorable'),
      ('fair_competitive::INTEGER*favorable_draw::INTEGER','fair_x_favorable'),
      ('patron*fair_competitive::INTEGER*favorable_draw::INTEGER','patron_x_fair_x_favorable')]
    return [('patron_by_five_bin_desert_gradient','TRUE',desert),
            ('patron_by_favorable_price_in_fair_states','fair_competitive',price),
            ('patron_by_fair_state_by_favorable_price','fair_competitive OR clearly_worse',triple)]


def contrast_specs(name):
    if name=='patron_by_five_bin_desert_gradient':
        result=[('patron_gap_disconnected_clearly_better',{'patron':1})]
        result += [('patron_gap_'+x,{'patron':1,'patron_x_eval_'+x:1})
                   for x in ['disconnected_better','roughly_equal','modestly_worse','clearly_worse']]
        result.append(('patron_gap_clearly_better_minus_clearly_worse',{'patron_x_eval_clearly_worse':-1}))
        return result
    if name=='patron_by_favorable_price_in_fair_states':
        return [('patron_gap_costly',{'patron':1}),
                ('patron_gap_nonnegative',{'patron':1,'patron_x_favorable_draw':1}),
                ('additional_nonnegative_response',{'patron_x_favorable_draw':1})]
    return [('patron_gap_'+state+'_'+side,dict({'patron':1},
        **({'patron_x_fair':1} if state=='fair' else {}),
        **({'patron_x_favorable':1} if side=='nonnegative' else {}),
        **({'patron_x_fair_x_favorable':1} if state=='fair' and side=='nonnegative' else {})))
        for state in ['clearly_worse','fair'] for side in ['costly','nonnegative']]


def linear_combinations(model,specs):
    rows=[];kept=model['kept_terms'];beta=np.array(model['estimate_vector'])
    for covariance,matrix in model['covariance_matrices'].items():
        V=np.array(matrix)
        for label,weights in specs:
            base={'model':model['model'],'contrast':label,'covariance':covariance,
                  'opportunities':model['opportunities'],'chooser_clusters':model['chooser_clusters']}
            if any(key not in kept for key in weights):
                rows.append({**base,'status':'not_estimable_dropped_required_term'});continue
            a=np.array([weights.get(k,0) for k in kept],dtype=float)
            b=float(a@beta);var=float(a@V@a)
            if var < -1e-8: raise RuntimeError('Negative linear-combination variance')
            se=math.sqrt(max(var,0));z=b/se if se>0 else math.nan
            rows.append({**base,'status':'estimated','coefficient_pp':b,'se_pp':se,
              'statistic':z,'p_two_sided_approx':common.normal_two_sided_p(z),
              'ci95_low_pp':b-1.959963984540054*se,'ci95_high_pp':b+1.959963984540054*se})
    return rows


def fit_families(db,cache,bridge,state,digest,public,ply=False):
    # Persistent sorted table is unnecessary: the frozen covariance pass explicitly orders clusters.
    db.execute(f"""CREATE OR REPLACE TEMP VIEW opportunity_analysis AS
      WITH users AS (SELECT username_norm,patron::INTEGER AS patron,
        row_number() OVER(ORDER BY username_norm)-1 AS cluster_code
        FROM read_parquet({q(bridge)}) WHERE returned)
      SELECT c.*,u.patron,u.cluster_code FROM read_parquet({q(cache)}) c JOIN users u USING(username_norm)""")
    controls=engine.control_terms(db,'opportunity_analysis')
    levels=[r[0] for r in db.execute('SELECT DISTINCT ply_band FROM opportunity_analysis ORDER BY ply_band').fetchall()]
    masks=[('all','TRUE',[])] if not ply else [
      ('ply_gt4',"ply_band NOT IN ('missing','00_04')",[]),
      ('ply_gt10',"ply_band NOT IN ('missing','00_04','05_10')",[]),
      ('ply_gt20',"ply_band NOT IN ('missing','00_04','05_10','11_20')",[]),
      ('ply_band_controls','TRUE',engine.dummy_expressions('ply_band',levels,'ply'))]
    models=[];coefficients=[];contrasts=[];support=[]
    for label,mask,extra in masks:
        for name,condition,primary in model_specs():
            terms=[];seen=set()
            for expr,alias in controls+extra+primary:
                if alias not in seen: terms.append((expr,alias));seen.add(alias)
            full_name=name+'__'+label
            specification={'parent':digest,'name':full_name,'terms':terms,
                           'condition':f'({condition}) AND ({mask})'}
            sig=hashlib.sha256(h.auth.canonical_json(specification).encode()).hexdigest()
            def estimate(directory):
                model,coef=engine.fit_collapsed_model(db,table='opportunity_analysis',
                    condition=specification['condition'],model_name=full_name,terms=terms,
                    primary_terms=[a for _,a in primary])
                model['estimand_class']='new_ply_sensitivity' if ply else 'frozen_appendix_new_sample'
                coef['estimand_class']=model['estimand_class']
                model['ply_rule']=mask
                h.save_json(directory/'fit.json',model)
                common.write_csv(directory/'coefficients.csv',coef)
                return {'model':full_name,'opportunities':model['opportunities'],'status':'estimated'}
            fits=state/'opportunity_fits';fits.mkdir(parents=True,exist_ok=True)
            directory,_=h.prior.checkpoint(fits,full_name,sig,estimate)
            model=h.auth.load_json(directory/'fit.json')
            models.append(model);coefficients.append(pd.read_csv(directory/'coefficients.csv'))
            contrasts.extend(linear_combinations(model,contrast_specs(name)))
            support.append({k:model[k] for k in ['model','opportunities','collapsed_rows','chooser_clusters','rank','ply_rule']})
            h.log('OPPORTUNITY_MODEL_COMPLETE '+full_name)
    prefix='ply' if ply else 'opportunity'
    common.write_csv(public/(prefix+'_coefficients.csv'),pd.concat(coefficients,ignore_index=True))
    common.write_csv(public/(prefix+'_linear_combinations.csv'),pd.DataFrame(contrasts))
    common.write_csv(public/(prefix+'_support.csv'),pd.DataFrame(support))
    h.save_json(public/(prefix+'_models_and_covariance.json'),models)
    return {'models':len(models),'linear_combinations':len(contrasts),'scope':prefix,
            'not_estimable_contrasts':sum(r['status']!='estimated' for r in contrasts)}
