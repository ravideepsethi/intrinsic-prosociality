"""Arena–pool comparisons and arena-only structural and persistence estimates."""
from __future__ import annotations

import gc
import os
from pathlib import Path
import numpy as np
import pandas as pd

from common import *
from estimation import fit, linear_contrast

CONTROLS = ['log_self_clock','log_opp_clock','log_rd','log_opp_rd','log_premium']
BASE_FE = ['chooser','tc_month','rating_bin','gap_bin']
FULL_FE = BASE_FE + ['board_stage']

def open_data(run, memory='6GB', threads=8):
    build=read_json(Path(run)/'private/BUILD.json')
    con=database(':memory:',threads,memory,Path(run)/'private/work/analysis')
    con.execute('CREATE VIEW all_opps AS SELECT * FROM '+parquet(build['narrow_paths']))
    con.execute(f'''CREATE VIEW eligible AS SELECT *, (source='arena')::DOUBLE AS arena,
      (eval>=-100)::DOUBLE AS fair,
      CASE WHEN clock_self>=0 THEN ln(1+clock_self) END AS log_self_clock,
      CASE WHEN clock_opp>=0 THEN ln(1+clock_opp) END AS log_opp_clock,
      CASE WHEN rd>0 THEN ln(rd) END AS log_rd, CASE WHEN opp_rd>0 THEN ln(opp_rd) END AS log_opp_rd,
      CASE WHEN premium>0 THEN ln(premium) END AS log_premium,
      concat(time_control,'|',month) AS tc_month,
      floor(rating/100)::INTEGER AS rating_bin, floor(gap/50)::INTEGER AS gap_bin,
      (board*8+stage)::INTEGER AS board_stage
      FROM all_opps WHERE source IN ('pool','arena') AND previous_status={q(NONADJACENT)}''')
    return con,build

COMPLETE = '''clock_self IS NOT NULL AND clock_self>=0 AND isfinite(clock_self)
 AND clock_opp IS NOT NULL AND clock_opp>=5 AND isfinite(clock_opp)
 AND rd>0 AND isfinite(rd) AND opp_rd>0 AND isfinite(opp_rd)
 AND premium>0 AND isfinite(premium) AND isfinite(payoff)
 AND rating IS NOT NULL AND gap IS NOT NULL AND ply IS NOT NULL
 AND time_control IS NOT NULL AND trim(time_control)<>''
 AND tc_base_s IS NOT NULL AND tc_inc_s IS NOT NULL'''

def load_frame(con, restriction, *, dual=True, strict_cell=False):
    sample='eligible'
    con.execute(f'CREATE OR REPLACE TEMP VIEW model_sample AS SELECT * FROM {sample} WHERE ({restriction}) AND ({COMPLETE})')
    key="concat(chooser::VARCHAR,'|',tc_month)" if strict_cell else 'chooser'
    if dual:
        con.execute(f'''CREATE OR REPLACE TEMP TABLE switchers AS SELECT {key} AS match_key
          FROM model_sample GROUP BY 1 HAVING min(arena)=0 AND max(arena)=1''')
        sample=f'model_sample WHERE {key} IN (SELECT match_key FROM switchers)'
    else:
        sample='model_sample'
    fields=['chooser','kind','arena','fair','board','stage','ply','rating','gap','payoff','premium',
            'tc_month','rating_bin','gap_bin','board_stage',*CONTROLS]
    frame=con.execute('SELECT '+','.join(fields)+' FROM '+sample).fetchdf()
    frame['tc_month']=frame['tc_month'].astype('category')
    if strict_cell:
        frame['chooser_tc_month']=pd.factorize(pd.MultiIndex.from_arrays([frame['chooser'],frame['tc_month']]))[0]
    return frame

def describe_frame(frame):
    result={}
    for source,value in [('pool',0),('arena',1)]:
        f=frame[frame.arena==value]
        result[source]={'n':len(f),'kind_draws':int(f.kind.sum()),'rate_pct':100*f.kind.mean() if len(f) else None,
                        'choosers':int(f.chooser.nunique())}
    pool=result['pool']['rate_pct']; arena=result['arena']['rate_pct']
    result['raw_difference_pp']=arena-pool if pool is not None and arena is not None else None
    result['raw_ratio']=arena/pool if pool and arena is not None else None
    return result

def persist_model(path,result):
    path=Path(path)
    json_write(path,result)
    side=path.with_suffix('.json.sha256')
    temp=side.with_name(side.name+'.tmp')
    temp.write_text(sha(path)+'  '+path.name+'\n')
    os.replace(temp,side)

def model_save(out, model_id, frame, targets, controls, effects, contract, label):
    path=Path(out)/(model_id+'.json')
    if path.exists():
        side=path.with_suffix('.json.sha256')
        if not side.is_file():
            # An interruption can occur between the two atomic writes. Preserve
            # the uncommitted JSON and recompute; a committed hash mismatch fails.
            archive_dir=Path(out).parents[1]/'private/incomplete_models'
            archive_dir.mkdir(parents=True,exist_ok=True)
            path.rename(archive_dir/(path.name+'.uncommitted.'+str(time.time_ns())))
        else:
            require(side.read_text().split()[0]==sha(path),'Individual model checkpoint hash failed: '+model_id)
            old=read_json(path)
            require(old['contract']==contract, 'Existing model has a different contract')
            return old
    log(f'Estimating {model_id}: {len(frame):,} rows, {frame.chooser.nunique():,} choosers')
    if len(frame)<100 or frame.chooser.nunique()<10:
        result={'status':'INSUFFICIENT_SUPPORT','n':len(frame),'clusters':int(frame.chooser.nunique())}
    else:
        result=fit(frame,targets,controls,effects)
    result.update({'model_id':model_id,'contract':contract,'design':label,
                   'sample_rates':describe_frame(frame),'causal_identification_certified':False})
    if result['status']=='ESTIMATED' and targets==['arena']:
        b=next(r['estimate_pp'] for r in result['coefficients'] if r['term']=='arena')/100
        # In an additive LPM with absorbed intercepts, mean fitted equals mean Y.
        # Hold each row's controls and fixed effects fixed and set arena to 0/1.
        p0=float(frame.kind.mean()-b*frame.arena.mean());p1=p0+b
        result['standardized_rates']={'pool_pct':100*p0,'arena_pct':100*p1,
          'arena_pool_ratio':p1/p0 if p0>0 and p1>=0 else None,
          'rates_within_unit_interval':0<=p0<=1 and 0<=p1<=1,
          'uncertainty':'Point estimates only; coefficient interval is for the difference.',
          'population':'The same estimation rows, held at their observed covariates and fixed effects.'}
    persist_model(path,result)
    gc.collect()
    return result

def descriptive(run,con):
    out=Path(run)/'public/descriptive'
    for name,group in [('source_month','source,month'),('source_board_stage','source,board,stage'),
                       ('source_speed','source,speed'),('source_rating','source,floor(rating/100)::INTEGER AS rating_bin'),
                       ('source_time_control','source,time_control')]:
        group_n=len(group.split(','))
        sql=f'''SELECT {group},count(*) AS opportunities,sum(kind)::BIGINT AS kind_draws,
          100*avg(kind) AS rate_pct,count(DISTINCT chooser) AS choosers
          FROM eligible GROUP BY {','.join(str(i+1) for i in range(group_n))}'''
        write_table(con,sql,out/name)
    write_table(con,f'''SELECT source,count(*) AS eligible_rows,
      count(*) FILTER(WHERE {COMPLETE}) AS complete_covariate_rows,
      count(*) FILTER(WHERE clock_self IS NULL) AS missing_chooser_clock,
      count(*) FILTER(WHERE time_control IS NULL OR trim(time_control)='') AS missing_time_control,
      count(*) FILTER(WHERE rd IS NULL OR opp_rd IS NULL) AS missing_rd,
      count(*) FILTER(WHERE premium IS NULL OR premium<=0) AS unavailable_premium
      FROM eligible GROUP BY source''',out/'covariate_coverage')
    # Both-source cell counts document overlap before any outcome comparison.
    write_table(con,'''SELECT time_control,month,board,stage,
      count(*) FILTER(WHERE source='pool') AS pool_n,
      count(*) FILTER(WHERE source='arena') AS arena_n
      FROM eligible GROUP BY 1,2,3,4''',out/'format_overlap_cells')

def suppression(run, memory, threads):
    con,build=open_data(run,memory,threads)
    out=Path(run)/'public/suppression';out.mkdir(parents=True,exist_ok=True)
    descriptive(run,con)
    contract=build['contract']
    for region,restriction in [('competitive','eval>=-100'),('all','TRUE'),('clearly_worse','eval<=-300')]:
        frame=load_frame(con,restriction)
        # A common complete-case, dual-format sample keeps ladder changes interpretable.
        ladder=[('chooser',['chooser'],[]),('full',FULL_FE,CONTROLS)]
        if region=='competitive':
            ladder=[('chooser',['chooser'],[]),('calendar_timecontrol',['chooser','tc_month'],[]),
                    ('board_stage',['chooser','tc_month','board_stage'],[]),('full',FULL_FE,CONTROLS)]
        for spec,effects,controls in ladder:
            model_save(out,region+'_'+spec,frame,['arena'],controls,effects,contract,
                       'Pool versus arena; both use the same observed-nonadjacency screen; common complete-case dual-format sample within region.')
        del frame;gc.collect()
    for name,restrict,strict in [('competitive_long','eval>=-100 AND ply>10',False),
                                  ('competitive_within_player_tc_month','eval>=-100',True)]:
        frame=load_frame(con,restrict,strict_cell=strict)
        effects=['chooser_tc_month','board_stage','rating_bin','gap_bin'] if strict else FULL_FE
        model_save(out,name,frame,['arena'],CONTROLS,effects,contract,
                   'Within dual-format chooser/time-control/month cells.' if strict else 'Competitive positions after ply 10.')
        del frame;gc.collect()
    frame=load_frame(con,'eval>=-100 OR eval<=-300')
    frame['arena_fair']=frame.arena*frame.fair
    r=model_save(out,'arena_by_board_merit',frame,['arena','arena_fair'],CONTROLS,FULL_FE,contract,
                 'Arena coefficient is the clearly-worse contrast; arena+arena_fair is competitive. Middle band excluded.')
    if r['status']=='ESTIMATED':
        r['contrasts']={'competitive':linear_contrast(r,{'arena':1,'arena_fair':1}),
                        'clearly_worse':linear_contrast(r,{'arena':1}),
                        'difference_between_board_regions':linear_contrast(r,{'arena_fair':1})}
        persist_model(out/'arena_by_board_merit.json',r)
    con.close()

def structural(run,memory,threads):
    con,build=open_data(run,memory,threads)
    out=Path(run)/'public/arena_structural';out.mkdir(parents=True,exist_ok=True)
    frame=load_frame(con,"source='arena'",dual=False)
    for board in (0,1,3,4):
        frame['board_'+str(board)]=(frame.board==board).astype(float)
    model_save(out,'five_board_states',frame,['board_0','board_1','board_3','board_4'],CONTROLS,
               BASE_FE+['stage'],build['contract'],'Arena only; roughly equal is the omitted board state.')
    binary=frame[(frame.board<=2)|(frame.board==4)].copy()
    model_save(out,'competitive_vs_clearly_worse',binary,['fair'],CONTROLS,BASE_FE+['stage'],build['contract'],
               'Arena-only desert contrast; middle band excluded.')
    del binary
    fair=frame[frame.board<=2].copy()
    for st in range(1,8): fair['stage_'+str(st)]=(fair.stage==st).astype(float)
    model_save(out,'competitive_game_stage',fair,['stage_'+str(st) for st in range(1,8)],CONTROLS,
               BASE_FE+['board'],build['contract'],'Arena only; competitive positions; ply 0–4 omitted.')
    equality=frame[frame.board.isin([1,2])].copy()
    equality['equal']=(equality.board==2).astype(float)
    for spec,effects,controls in [('chooser',['chooser'],[]),('covariates',BASE_FE,CONTROLS),
                                 ('exact_ply',BASE_FE+['ply'],CONTROLS)]:
        model_save(out,'equality_'+spec,equality,['equal'],controls,effects,build['contract'],
                   'Roughly equal versus better; raw counts are in descriptive tables.')
    con.close()

def persistence(run,memory,threads):
    con,build=open_data(run,memory,threads)
    out=Path(run)/'public/persistence';out.mkdir(parents=True,exist_ok=True)
    con.execute('''CREATE TABLE halves AS SELECT source,chooser,
      count(*) FILTER(WHERE month<='2024-10') AS n1,
      count(*) FILTER(WHERE month>'2024-10') AS n2,
      sum(kind) FILTER(WHERE month<='2024-10') AS k1,
      sum(kind) FILTER(WHERE month>'2024-10') AS k2
      FROM eligible WHERE eval>=-100 GROUP BY 1,2''')
    records=[]
    # Opportunity reliability is reported explicitly rather than pretending
    # the smaller arena panel measures individual propensities equally well.
    for source in ('arena','pool'):
        for minimum in (1,2,4,5,10):
            f=con.execute(f'''SELECT *,k1/n1 AS r1,k2/n2 AS r2,
              n1::DOUBLE*n2/(n1+n2) AS w FROM halves
              WHERE source={q(source)} AND n1>={minimum} AND n2>={minimum}''').fetchdf()
            r={'source':source,'minimum_per_half':minimum,'choosers':len(f),
               'opportunities':int(f.n1.sum()+f.n2.sum()),'grants':int(f.k1.sum()+f.k2.sum())}
            if len(f)>2 and f.r1.std()>0 and f.r2.std()>0:
                r['pearson']=float(f.r1.corr(f.r2));w=f.w.to_numpy();x=f.r1.to_numpy();y=f.r2.to_numpy()
                x=x-np.average(x,weights=w);y=y-np.average(y,weights=w)
                r['weighted_pearson']=float(np.sum(w*x*y)/np.sqrt(np.sum(w*x*x)*np.sum(w*y*y)))
            else:r.update(pearson=None,weighted_pearson=None)
            records.append(r)
    json_write(out/'split_half.json',{'contract':build['contract'],'estimates':records,
               'weight':'n1*n2/(n1+n2)','scope':'Competitive opportunities; fixed calendar halves; no disattenuation.'})
    write_table(con,'''SELECT source,CASE WHEN coalesce(k1,0)>0 THEN 'prior_granter' ELSE 'no_prior_grant' END AS history,
      count(*) AS choosers,sum(n2)::BIGINT AS next_half_opportunities,
      sum(coalesce(k2,0))::BIGINT AS next_half_grants,
      100*sum(coalesce(k2,0))/sum(n2) AS next_half_kindness_pct
      FROM halves WHERE n1>=4 AND n2>=1 GROUP BY 1,2''',out/'prior_granters')
    write_table(con,'''WITH a AS (SELECT source,chooser,count(*) AS n,sum(kind) AS k,
      count(*) FILTER(WHERE eval>=-100) AS fair_n,
      count(*) FILTER(WHERE eval>=-100 AND kind=1) AS fair_k FROM eligible GROUP BY 1,2)
      SELECT source,count(*) AS choosers,count(*) FILTER(WHERE k>=2) AS repeat_granters,
      count(*) FILTER(WHERE fair_k>=2) AS competitive_repeat_granters,
      sum(n) FILTER(WHERE k>=2)::BIGINT AS repeat_granter_opportunities,
      sum(k) FILTER(WHERE k>=2)::BIGINT AS repeat_granter_grants,
      count(*) FILTER(WHERE fair_n>=4) AS at_least_four_competitive_opportunities FROM a GROUP BY 1''',out/'episode_support')
    con.close()
