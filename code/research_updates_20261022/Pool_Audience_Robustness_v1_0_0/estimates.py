"""Exact account-cell estimators with chooser-clustered uncertainty.

No rows are sampled. Cross-group contrasts retain covariance for choosers
appearing in both groups. The FE specification has chooser-by-group intercepts.
"""
from __future__ import annotations
import math
from scipy.stats import t as student_t
from common import one, records, qs

GROUPS = {0: 'remaining', 1: 'elite_not_known_streamer', 2: 'known_streamer', 3: 'rating_or_bot_unknown'}
METRICS = ('all_rate', 'competitive_rate', 'clearly_worse_rate', 'raw_gradient', 'log_ratio', 'chooser_fe_gradient')

def interval(value, se, df, level=0.95):
    if value is None or se is None or df < 1:
        return None, None
    critical = float(student_t.ppf((1+level)/2, df))
    return value-critical*se, value+critical*se

def group_expression(threshold, definition, view):
    c_elite = f'(ce >= {int(threshold)}' + (' OR ct' if definition == 'rating_directory_known_titles' else '') + ')'
    d_elite = f'(de >= {int(threshold)}' + (' OR dt' if definition == 'rating_directory_known_titles' else '') + ')'
    if view == 'chooser':
        return f'CASE WHEN cb THEN 3 WHEN cs THEN 2 WHEN {c_elite} THEN 1 WHEN ce IS NULL OR ce<=0 THEN 3 ELSE 0 END'
    if view == 'either_player':
        return (f'CASE WHEN cb OR dbot THEN 3 WHEN cs OR ds THEN 2 WHEN {c_elite} OR {d_elite} THEN 1 '
                'WHEN ce IS NULL OR ce<=0 OR de IS NULL OR de<=0 THEN 3 ELSE 0 END')
    raise ValueError(view)

def make_cells(db, group_sql, where='true'):
    db.execute(f'''CREATE OR REPLACE TEMP TABLE cells AS
        SELECT chooser, {group_sql} AS g, count(*)::BIGINT AS n,
        sum(y)::BIGINT AS k, count(*) FILTER(WHERE state=1)::BIGINT AS fn,
        sum(CASE WHEN state=1 THEN y ELSE 0 END)::BIGINT AS fk,
        count(*) FILTER(WHERE state=0)::BIGINT AS wn,
        sum(CASE WHEN state=0 THEN y ELSE 0 END)::BIGINT AS wk
        FROM base WHERE {where} GROUP BY chooser, g''')

def estimate_cells(db, tag, overall_n, overall_k):
    totals = records(db, '''SELECT g, sum(n)::BIGINT n, sum(k)::BIGINT k,
      sum(fn)::BIGINT fn, sum(fk)::BIGINT fk, sum(wn)::BIGINT wn, sum(wk)::BIGINT wk,
      count(*)::BIGINT accounts, count(*) FILTER(WHERE k>0)::BIGINT granters,
      count(*) FILTER(WHERE fn>0)::BIGINT fg, count(*) FILTER(WHERE wn>0)::BIGINT wg,
      count(*) FILTER(WHERE fn+wn>0)::BIGINT fwg,
      count(*) FILTER(WHERE fn>0 AND wn>0)::BIGINT sg,
      coalesce(sum(fn+wn) FILTER(WHERE fn>0 AND wn>0),0)::BIGINT sn,
      coalesce(sum(fn::DOUBLE*wn/(fn+wn)) FILTER(WHERE fn>0 AND wn>0),0)::DOUBLE sw,
      sum((fn::DOUBLE*wn/(fn+wn)) * (fk::DOUBLE/nullif(fn,0)-wk::DOUBLE/nullif(wn,0)))
        FILTER(WHERE fn>0 AND wn>0) AS wd
      FROM cells GROUP BY g ORDER BY g''')
    db.execute('''CREATE OR REPLACE TEMP TABLE scores(
      chooser VARCHAR, g INTEGER, all_rate DOUBLE, competitive_rate DOUBLE,
      clearly_worse_rate DOUBLE, raw_gradient DOUBLE, log_ratio DOUBLE, chooser_fe_gradient DOUBLE)''')
    results, summary, by_group = [], [], {}
    for a in totals:
        g = a['g']
        p = a['k']/a['n']
        pf = a['fk']/a['fn'] if a['fn'] else None
        pw = a['wk']/a['wn'] if a['wn'] else None
        gap = pf-pw if pf is not None and pw is not None else None
        lr = math.log(pf/pw) if pf and pw else None
        beta = a['wd']/a['sw'] if a['sw'] else None
        values = [p,pf,pw,gap,lr,beta]
        counts = [a['accounts'],a['fg'],a['wg'],a['fwg'],a['fwg'],a['sg']]
        ns = [a['n'],a['fn'],a['wn'],a['fn']+a['wn'],a['fn']+a['wn'],a['sn']]
        factors = []
        for j,G in enumerate(counts):
            factor = G/(G-1) if G>1 else None
            if factor is not None and j in (3,4) and ns[j]>2:
                factor *= (ns[j]-1)/(ns[j]-2)
            if j==5:
                factor = factor*(ns[j]-1)/(ns[j]-G-1) if factor and ns[j]>G+1 else None
            factors.append(factor)
        def expr_rate(k,n,pr,N):
            return f'({k}-({pr})*{n})/({N}::DOUBLE)' if pr is not None and N else '0.0'
        s0 = expr_rate('k','n',p,a['n'])
        sf = expr_rate('fk','fn',pf,a['fn'])
        sw = expr_rate('wk','wn',pw,a['wn'])
        sfw = f'({sf})-({sw})' if gap is not None else '0.0'
        slr = f'({sf})/{pf}-({sw})/{pw}' if lr is not None else '0.0'
        sfe = (f'''CASE WHEN fn>0 AND wn>0 THEN
           (fn::DOUBLE*wn/(fn+wn))*(fk::DOUBLE/fn-wk::DOUBLE/wn-({beta}))/({a['sw']})
           ELSE 0 END''' if beta is not None else '0.0')
        scaled = [f'({e})*{math.sqrt(f) if f is not None else 0.0}'
                  for e,f in zip([s0,sf,sw,sfw,slr,sfe],factors)]
        db.execute(f"INSERT INTO scores SELECT chooser,g,{','.join(scaled)} FROM cells WHERE g={g}")
        meat = one(db, 'SELECT '+','.join(f'sum({m}*{m}) AS {m}' for m in METRICS)+f' FROM scores WHERE g={g}')
        by_group[g] = {}
        for j,m in enumerate(METRICS):
            valid = values[j] is not None and factors[j] is not None
            se = math.sqrt(max(0,float(meat[m] or 0))) if valid else None
            v = values[j]
            lo,hi = interval(v,se,counts[j]-1)
            scale = 1 if m=='log_ratio' else 100
            r = dict(tag, group=GROUPS[g], group_code=g, metric=m,
                     estimate=None if v is None else v*scale,
                     cluster_se=None if se is None else se*scale,
                     ci95_low=None if lo is None else lo*scale,
                     ci95_high=None if hi is None else hi*scale,
                     units=('log ratio' if m=='log_ratio' else 'percent' if m.endswith('_rate') else 'percentage points'),
                     n=ns[j], chooser_clusters=counts[j],
                     variance_correction=factors[j],
                     status='estimated' if valid else 'insufficient_support',
                     few_clusters=counts[j]<30)
            results.append(r)
            by_group[g][m] = (v,se,counts[j])
        ratio = math.exp(lr) if lr is not None else None
        ratio_se = by_group[g]['log_ratio'][1]
        rl,rh = interval(lr,ratio_se,a['fwg']-1)
        summary.append(dict(tag,group=GROUPS[g],opportunities=a['n'],kind_draws=a['k'],
            chooser_accounts=a['accounts'],granting_accounts=a['granters'],
            opportunity_share_pct=100*a['n']/overall_n,
            kind_draw_share_pct=100*a['k']/overall_k if overall_k else None,
            all_rate_pct=100*p,competitive_n=a['fn'],competitive_k=a['fk'],
            clearly_worse_n=a['wn'],clearly_worse_k=a['wk'],
            competitive_rate_pct=None if pf is None else 100*pf,
            clearly_worse_rate_pct=None if pw is None else 100*pw,
            raw_gradient_pp=None if gap is None else 100*gap,
            rate_ratio=ratio,ratio_ci95_low=None if rl is None else math.exp(rl),
            ratio_ci95_high=None if rh is None else math.exp(rh),
            chooser_fe_gradient_pp=None if beta is None else 100*beta,
            chooser_fe_se_pp=None if by_group[g]['chooser_fe_gradient'][1] is None else 100*by_group[g]['chooser_fe_gradient'][1],
            chooser_fe_n=a['sn'],chooser_fe_accounts=a['sg']))
    contrasts = []
    for ga in (1,2):
        if ga not in by_group or 0 not in by_group:
            continue
        for m in ('all_rate','competitive_rate','clearly_worse_rate','raw_gradient','chooser_fe_gradient'):
            va,sa,ca = by_group[ga][m]
            vb,sb,cb = by_group[0][m]
            if va is None or vb is None or sa is None or sb is None:
                continue
            r = one(db,f'''SELECT sum(z*z) AS meat, count(*) AS clusters_union FROM
              (SELECT chooser,sum(CASE WHEN g={ga} THEN {m} ELSE -{m} END) z
               FROM scores WHERE g IN(0,{ga}) GROUP BY chooser)''')
            se = math.sqrt(max(0,float(r['meat'] or 0)))
            df = min(ca,cb)-1
            diff = va-vb
            lo,hi = interval(diff,se,df)
            lo90,hi90 = interval(diff,se,df,.90)
            contrasts.append(dict(tag,group_a=GROUPS[ga],group_b=GROUPS[0],metric=m,
                difference_pp=100*diff,cluster_se_pp=100*se,
                ci95_low_pp=100*lo,ci95_high_pp=100*hi,
                ci90_low_pp=100*lo90,ci90_high_pp=100*hi90,
                reference_df=df,clusters_union=r['clusters_union'],
                within_exploratory_margin_025pp=(lo90>-.0025 and hi90<.0025),
                within_exploratory_margin_050pp=(lo90>-.005 and hi90<.005),
                few_clusters=min(ca,cb)<30))
    return summary, results, contrasts

def standardize(db, group_sql, tag, min_cell=10):
    """Four-cell common support, same covariate weights in both desert states.

    A coarse descriptive adjustment, not a causal audience estimator. Inference
    conditions on strata and weights. Rating-defined groups may have no overlap.
    """
    out = []
    # Group and state comparisons use exactly the same strata. Calendar quarter,
    # both ratings, speed, game stage and both clocks are controlled jointly.
    strata = '''concat_ws('|',cast(floor(ce/200) AS VARCHAR),cast(floor(de/200) AS VARCHAR),
       speed,cast(floor((month_index-1)/3) AS VARCHAR),
       CASE WHEN ply<=10 THEN 'p1' WHEN ply<=30 THEN 'p2' WHEN ply<=60 THEN 'p3' ELSE 'p4' END,
       CASE WHEN cc<15 THEN 'c1' WHEN cc<60 THEN 'c2' ELSE 'c3' END,
       CASE WHEN dc<15 THEN 'd1' WHEN dc<60 THEN 'd2' ELSE 'd3' END)'''
    db.execute(f'''CREATE OR REPLACE TEMP VIEW adjusted_input AS SELECT *,{group_sql} g,
        {strata} AS s FROM base WHERE state IN(0,1) AND ce>0 AND de>0
        AND ply IS NOT NULL AND ply>=0 AND cc IS NOT NULL AND dc IS NOT NULL
        AND isfinite(cc) AND isfinite(dc) AND cc>=0 AND dc>=0 AND speed IS NOT NULL''')
    db.execute('''CREATE OR REPLACE TEMP TABLE strata_cells AS SELECT g,state,s,count(*) n,
        sum(y) k FROM adjusted_input WHERE g IN(0,1,2) GROUP BY g,state,s''')
    for other in (1,2):
        db.execute(f'''CREATE OR REPLACE TEMP TABLE support AS
          SELECT s,sum(n)::DOUBLE AS ns FROM strata_cells WHERE g IN(0,{other})
          GROUP BY s HAVING count(*)=4 AND min(n)>={int(min_cell)}''')
        info=one(db,'SELECT count(*) strata,sum(ns) n FROM support')
        r=dict(tag,comparison=GROUPS[other]+' minus remaining',minimum_cell_n=min_cell,
               common_strata=info['strata'],supported_opportunities=int(info['n'] or 0),
               status='no_common_support',adjustment='common-support coarse standardization')
        if not info['strata']:
            out.append(r)
            continue
        db.execute('''CREATE OR REPLACE TEMP TABLE adjusted_cells AS
           SELECT c.*,s.ns/(SELECT sum(ns) FROM support) w,c.k::DOUBLE/c.n AS p
           FROM strata_cells c JOIN support s USING(s)''')
        rows=records(db,f'''SELECT g,state,sum(w*p) AS rate,sum(n)::BIGINT n
             FROM adjusted_cells WHERE g IN(0,{other}) GROUP BY g,state''')
        rates={(a['g'],a['state']):a['rate'] for a in rows}
        a=rates[other,1]-rates[other,0]
        b=rates[0,1]-rates[0,0]
        db.execute(f'''CREATE OR REPLACE TEMP TABLE adjusted_scores AS
          SELECT v.chooser,
            sum(CASE WHEN v.g={other} THEN (2*v.state-1)*c.w*(v.y-c.p)/c.n ELSE 0 END) a,
            sum(CASE WHEN v.g=0 THEN (2*v.state-1)*c.w*(v.y-c.p)/c.n ELSE 0 END) b,
            bool_or(v.g={other}) ha,bool_or(v.g=0) hb
          FROM adjusted_input v JOIN adjusted_cells c ON v.g=c.g AND v.state=c.state AND v.s=c.s
          WHERE v.g IN(0,{other}) GROUP BY v.chooser''')
        meat=one(db,'''SELECT count(*) G,sum(ha::INTEGER) ga,sum(hb::INTEGER) gb,
             sum(a*a) aa,sum(b*b) bb,sum((a-b)*(a-b)) dd FROM adjusted_scores''')
        G=meat['G']
        se=math.sqrt(float(meat['dd'])*G/(G-1)) if G>1 else None
        lo,hi=interval(a-b,se,min(meat['ga'],meat['gb'])-1)
        r.update(status='estimated' if lo is not None else 'insufficient_clusters',
            competitive_other_pct=100*rates[other,1],clearly_worse_other_pct=100*rates[other,0],
            competitive_remaining_pct=100*rates[0,1],clearly_worse_remaining_pct=100*rates[0,0],
            other_gradient_pp=100*a,remaining_gradient_pp=100*b,
            gradient_difference_pp=100*(a-b),cluster_se_pp=None if se is None else 100*se,
            ci95_low_pp=None if lo is None else 100*lo,ci95_high_pp=None if hi is None else 100*hi,
            chooser_clusters=G,other_clusters=meat['ga'],remaining_clusters=meat['gb'])
        for g,label in ((other,'other'),(0,'remaining')):
            supported=sum(x['n'] for x in rows if x['g']==g)
            total=one(db,f'SELECT coalesce(sum(n),0) n FROM strata_cells WHERE g={g}')['n']
            r[label+'_complete_control_opportunities']=total
            r[label+'_support_share_of_complete_controls_pct']=100*supported/total if total else None
        out.append(r)
    return out
