from common import *
from estimate import sqlfit
NUMS=['payoff10','premium10','crd100','drd100','log_cc','log_dc','cc_missing','dc_missing']
CATS=['month','speed','rating_tier','stage']
COMPLETE=' AND '.join(f'{s} IS NOT NULL AND isfinite({s})' for s in NUMS+['gap100'])+" AND speed IS NOT NULL AND month IS NOT NULL"

def rates(db,path,groups,where='true',source='aged'):
    export(db,path,f'''WITH a AS (SELECT {groups},chooser,count(*)::DOUBLE n,sum(y)::DOUBLE k FROM {source} WHERE {where} GROUP BY ALL),
      t AS (SELECT {groups},sum(n) n,sum(k) k,count(*) g,sum(k*k) kk,sum(k*n) kn,sum(n*n) nn FROM a GROUP BY ALL)
      SELECT {groups},n opportunities,k grants,g choosers,100*k/n rate_pct,
      CASE WHEN g>1 THEN 100*sqrt(greatest(0,kk-2*k/n*kn+pow(k/n,2)*nn)*g/(g-1))/n END cluster_se_pp FROM t ORDER BY {groups}''')

def shares(db,path,source):
    parts=[]
    for days in [7,14,30,90,365]:
        for label,condition in [('all','true'),('competitive','board>=-100'),('clearly_worse','board<=-300')]:
            parts.append(f'''SELECT {days} under_days,{qs(label)} state,count(*) opportunities,sum(y) grants,
              count(*) FILTER(WHERE age_days IS NOT NULL) age_observed_opportunities,
              coalesce(sum(y) FILTER(WHERE age_days IS NOT NULL),0) age_observed_grants,
              coalesce(sum(y) FILTER(WHERE age_days<{days}),0) young_grants,
              coalesce(sum(y) FILTER(WHERE age_days IS NULL AND (game_ms-first_ms)/86400000.<{days}),0) possibly_young_missing_grants,
              100.*young_grants/nullif(grants,0) lower_share_pct,
              100.*(young_grants+possibly_young_missing_grants)/nullif(grants,0) upper_share_pct,
              100.*young_grants/nullif(age_observed_grants,0) observed_only_share_pct
              FROM {source} WHERE {condition}''')
    export(db,path,' UNION ALL '.join(parts))

def model_sets(db,run):
    report=run/'report';results=[]
    groups=[('all_sample','true')]+[(f'age_ge_{n}',f'age_days>={n}') for n in [30,90,365]]+[(f'tenure_{i}',f'tenure LIKE {qs(str(i)+"_%")}') for i in range(5)]
    for label,condition in groups:
        for model,where,targets,cats,nums in [
            ('gradient_minimal','(board>=-100 OR board<=-300)',['competitive'],[],[]),
            ('gradient_full','(board>=-100 OR board<=-300)',['competitive'],CATS+['gap_bin'],NUMS),
            ('competitive_stage','board>=-100',['stage_mid','stage_late'],['month','speed','rating_tier','board_bin','gap_bin'],NUMS),
            ('competitive_gap','board>=-100',['gap100'],CATS+['board_bin'],NUMS)]:
            filename=f'TENURE_MODEL_{label}_{model}.json';dest=report/filename
            # Re-estimate report files; expensive source/projection/download stages resume independently.
            log(label+' '+model)
            query=f'SELECT * FROM aged WHERE ({condition}) AND ({where}) AND ({COMPLETE})'
            with heartbeat('Fitting '+label+' '+model):r=sqlfit(db,query,targets,cats,nums)
            r.update(sample=label,model=model,interpretation='Descriptive LPM on account probability sample; age availability may select accounts')
            dump(dest,r);results.append(dict(file=filename,status=r['status'],estimates=r.get('estimates',{})))
    dump(report/'TENURE_MODEL_INDEX.json',results)

def persistence(db,run):
    # Cohort age is frozen at first observed first-year opportunity, not at year two.
    db.execute('''CREATE OR REPLACE TEMP TABLE py AS SELECT chooser,yr,any_value(username) username,
      count(*)::DOUBLE n,sum(y)::DOUBLE k,min(game_ms) first_year_ms,
      any_value(CASE WHEN first_age IS NOT NULL THEN created_ms END) created_ms FROM aged WHERE board>=-100 GROUP BY chooser,yr''')
    # Exact account leave-out cell residuals remove observable board/stage/speed composition.
    db.execute('''CREATE OR REPLACE TEMP TABLE pcells AS SELECT chooser,yr,board_bin,stage,speed,
      count(*)::DOUBLE n,sum(y)::DOUBLE k FROM aged WHERE board>=-100 AND speed IS NOT NULL GROUP BY ALL''')
    db.execute('''CREATE OR REPLACE TEMP TABLE pres AS WITH totals AS (SELECT yr,board_bin,stage,speed,sum(n) nt,sum(k) kt FROM pcells GROUP BY ALL)
      SELECT chooser,yr,sum(c.n) n,sum(c.k-c.n*(t.kt-c.k)/(t.nt-c.n)) residual_sum
      FROM pcells c JOIN totals t USING(yr,board_bin,stage,speed) WHERE t.nt>c.n GROUP BY chooser,yr''')
    db.execute(f'''CREATE OR REPLACE TEMP VIEW pp AS SELECT a.chooser,a.n n1,a.k k1,b.n n2,b.k k2,
      CASE WHEN a.first_year_ms>=a.created_ms THEN (a.first_year_ms-a.created_ms)/86400000. END baseline_age,
      r1.residual_sum/nullif(r1.n,0) residual1,r2.residual_sum/nullif(r2.n,0) residual2,
      r1.n adjusted_n1,r2.n adjusted_n2
      FROM py a LEFT JOIN py b ON a.chooser=b.chooser AND b.yr=2
      LEFT JOIN pres r1 ON a.chooser=r1.chooser AND r1.yr=1
      LEFT JOIN pres r2 ON a.chooser=r2.chooser AND r2.yr=2 WHERE a.yr=1''')
    parts=[]
    for name,where in [('all','true')]+[(f'baseline_age_ge_{v}',f'baseline_age>={v}') for v in [30,90,365]]+[(f'baseline_bin_{i}',f'{age_bin("baseline_age")} LIKE {qs(str(i)+"_%")}') for i in range(5)]:
        for minimum in [1,5,10]:
            parts.append(f'''WITH a AS (SELECT *,k1/n1 p1,k2/n2 p2,n1*n2/(n1+n2) w FROM pp WHERE {where} AND n1>={minimum} AND n2>={minimum}),
            t AS (SELECT count(*) accounts,sum(n1) opportunities_y1,sum(n2) opportunities_y2,corr(p1,p2) raw_equal_account_correlation,
              corr(residual1,residual2) cell_adjusted_equal_account_correlation,sum(w) sw,sum(w*p1) sx,sum(w*p2) sy,
              sum(w*p1*p2) sxy,sum(w*p1*p1) sxx,sum(w*p2*p2) syy,
              count(*) FILTER(WHERE residual1 IS NOT NULL AND residual2 IS NOT NULL) adjusted_accounts FROM a)
            SELECT {qs(name)} cohort,{minimum} minimum_each_year,* EXCLUDE(sw,sx,sy,sxy,sxx,syy),
              (sxy-sx*sy/sw)/nullif(sqrt(greatest(0,(sxx-sx*sx/sw)*(syy-sy*sy/sw))),0) harmonic_opportunity_weighted_correlation FROM t''')
    # Parentheses keep each CTE local in a UNION.
    export(db,run/'report/PERSISTENCE.csv',' UNION ALL '.join('('+s+')' for s in parts))
    export(db,run/'report/PERSISTENCE_RETENTION.csv',f'''SELECT {age_bin('baseline_age')} cohort,k1>0 ever_competitive_kind_year1,
      count(*) year1_accounts,count(*) FILTER(WHERE n2>0) reached_year2,100.*count(*) FILTER(WHERE n2>0)/count(*) reached_pct,
      sum(n2) year2_opportunities,sum(k2) year2_grants,100.*sum(k2)/nullif(sum(n2),0) year2_opportunity_rate_pct,
      100.*avg(k2/n2) year2_equal_account_mean_rate_pct FROM pp GROUP BY ALL ORDER BY ALL''')
    dump(run/'report/PERSISTENCE_METHOD.json',dict(region='competitive in both years',years=['2023-11 through 2024-10','2024-11 through 2025-10'],
      cohort='Account age at first competitive opportunity in year one; creation missing stays unknown',
      weights='n1*n2/(n1+n2); explicitly differs from any earlier unspecified opportunity-count weighting',
      adjustment='Within each year subtract leave-one-account-out cell rate: board five-bin category × eight ply bins × speed; aggregate residuals by account',
      limits='Descriptive correlations among observed returners; no assertion of stable preferences or removal of all state heterogeneity; no confidence intervals for correlations'))

def patrons(db,run):
    # Large historical profile frame, homogeneous snapshot date, current-main-panel histories.
    db.execute('''CREATE OR REPLACE TEMP VIEW patron_source AS SELECT s.chooser_user_id chooser,s.outcome_kind_draw::INTEGER y,
      s.engine_eval_cp_disconnected board,s.chooser_elo rating,s.api_created_at_ms game_ms,p.created_ms,p.patron,p.match_cell,
      (a.first_ms-p.created_ms)/86400000. first_age,(s.api_created_at_ms-p.created_ms)/86400000. age_days
      FROM src s JOIN accounts a ON s.chooser_user_id=a.chooser JOIN profiles_cache p ON a.username=p.username
      WHERE p.profile_source='august' AND p.patron IS NOT NULL AND p.created_ms IS NOT NULL AND a.first_ms>=p.created_ms''')
    results=[]
    for threshold in [0,30,90,365]:
        log(f'Patron comparison: use opportunities at age >= {threshold} days')
        with heartbeat('Aggregating Patron histories'):
            db.execute(f'''CREATE OR REPLACE TEMP TABLE patron_accounts AS SELECT chooser,any_value(patron)::INTEGER y,any_value(match_cell) match_cell,
              any_value(first_age) first_age,avg(rating)/100. rating100,
              count(*) FILTER(WHERE board>=-100) nf,count(*) FILTER(WHERE board<=-300) nl,
              coalesce(sum(y) FILTER(WHERE board>=-100),0)>0 ef,coalesce(sum(y) FILTER(WHERE board<=-300),0)>0 el
              FROM patron_source WHERE age_days>={threshold} GROUP BY chooser''')
        for minimum in [1,4]:
            view=f'''SELECT * EXCLUDE(ef,el),ef::INTEGER ever_fair,el::INTEGER ever_losing,
               ln(1+nf) log_nf,ln(1+nl) log_nl,ln(1+first_age) log_age,{age_bin('first_age')} cohort
               FROM patron_accounts WHERE nf>={minimum} AND nl>={minimum}'''
            export(db,run/f'report/PATRON_age{threshold}_min{minimum}_rates.csv',f'''SELECT cohort,ever_fair,ever_losing,count(*) accounts,sum(y) patrons,avg(y)*100 patron_pct
               FROM ({view}) GROUP BY ALL ORDER BY ALL''')
            splits=[('pooled','true')]
            if threshold==0:splits +=[(f'cohort_{i}',f'cohort LIKE {qs(str(i)+"_%")}') for i in range(5)]
            for label,where in splits:
                q=f'SELECT * FROM ({view}) WHERE match_cell IS NOT NULL AND ({where})'
                result=sqlfit(db,q,['ever_fair','ever_losing'],[],['rating100','log_nf','log_nl','log_age'],absorb='match_cell',cluster='match_cell')
                result.update(minimum_each_state=minimum,opportunity_min_age=threshold,cohort=label,
                  population='Returned active August profile acquisition frame; outcome-dependent sampling; not an unconditional population Patron rate',
                  outcome='August current Patron status; not observed payment or historical Patron adoption',
                  specification='New tenure sensitivity with original match-cell absorption, exposure counts, mean rating and baseline age; not exact rerun of prior all-control specification')
                if result.get('status')=='ESTIMATED' and all(result['estimates'][x]['status']=='ESTIMATED' for x in ['ever_fair','ever_losing']):
                    import math
                    c=result['target_covariance_pp2'];result['fair_minus_losing_pp']=result['estimates']['ever_fair']['coefficient_pp']-result['estimates']['ever_losing']['coefficient_pp']
                    result['contrast_se_pp']=math.sqrt(max(0,c[0][0]+c[1][1]-2*c[0][1]))
                name=f'PATRON_MODEL_age{threshold}_min{minimum}_{label}.json';dump(run/'report'/name,result)
                results.append(dict(file=name,status=result['status']))
    dump(run/'report/PATRON_MODEL_INDEX.json',results)

def run_tenure(db,run):
    export(db,run/'report/TENURE_COVERAGE.csv','''SELECT age_source,tenure,competitive,count(*) opportunities,sum(y) grants,count(DISTINCT chooser) choosers,
      count(*) FILTER(WHERE raw_age<0) negative_age_rows,
      count(DISTINCT chooser) FILTER(WHERE raw_first_age<0) creation_after_first_record_accounts FROM aged GROUP BY ALL ORDER BY ALL''')
    db.execute('''CREATE OR REPLACE TEMP VIEW sample_shares AS SELECT p.*,a.first_ms FROM aged p JOIN accounts a USING(chooser)''')
    shares(db,run/'report/NOVICE_GRANT_SHARE_PROBABILITY_SAMPLE.csv','sample_shares')
    # Census bounds are particularly useful: most grants were in the profile acquisition frame.
    db.execute('''CREATE OR REPLACE TEMP VIEW census_age AS SELECT s.outcome_kind_draw::INTEGER y,s.engine_eval_cp_disconnected board,
      s.api_created_at_ms game_ms,a.first_ms,
      CASE WHEN a.first_ms>=coalesce(c.created_ms,f.created_ms)
        THEN (s.api_created_at_ms-coalesce(c.created_ms,f.created_ms))/86400000. END age_days
      FROM src s JOIN accounts a ON s.chooser_user_id=a.chooser LEFT JOIN profiles_cache c USING(username) LEFT JOIN profiles_fetch f USING(username)''')
    with heartbeat('Census bounds on novice grant share'):shares(db,run/'report/NOVICE_GRANT_SHARE_CENSUS_BOUNDS.csv','census_age')
    rates(db,run/'report/TENURE_BOARD_RATES.csv','tenure,board_bin')
    rates(db,run/'report/TENURE_BOARD_STAGE_RATES.csv','tenure,board_bin,stage')
    model_sets(db,run);persistence(db,run);patrons(db,run)
    dump(run/'report/TENURE_COMPLETE.json',dict(status='TENURE_COMPUTATION_COMPLETE',interpretation_gate='Inspect creation-date coverage, confidence intervals and account support; computation success is not a substantive pass'))
