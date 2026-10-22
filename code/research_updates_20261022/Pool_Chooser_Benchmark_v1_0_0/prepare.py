"""Certified 41.5m-panel adapter and outcome-independent disjoint sampling."""
from __future__ import annotations
import numpy as np
import pandas as pd
from io_utils import *

START = 1698796800000       # 2023-11-01
VALID = 1722470400000       # 2024-08-01
SPLIT = 1730419200000       # 2024-11-01
END = 1761955200000         # 2025-11-01
Q_EDGES = [0., .2, .4, .6, .8, 1.]
Q0 = 2
B_EDGES = [-np.inf, -300., -100., 100., 300., np.inf]
# Discrete reported board bins use <= at -300 and +100; perception boundaries
# use the exact half-open convention below, with equality sensitivity reported.
C0, C1 = (0*4+2)*5+Q0, (2*4+2)*5+Q0


def records(db, sql):
    return db.execute(sql).fetchdf().to_dict('records')


def source_view(db, paths):
    files = '[' + ','.join(qs(p) for p in paths) + ']'
    db.execute(f'''CREATE OR REPLACE VIEW source AS SELECT *,
      outcome_kind_draw::INTEGER y,
      CASE WHEN engine_eval_cp_disconnected<=-300 THEN 0
        WHEN engine_eval_cp_disconnected< -100 THEN 1
        WHEN engine_eval_cp_disconnected<=100 THEN 2
        WHEN engine_eval_cp_disconnected<300 THEN 3 ELSE 4 END board,
      CASE WHEN ply_count=2 THEN 0 WHEN ply_count<=10 THEN 1
        WHEN ply_count<=40 THEN 2 ELSE 3 END stage
      FROM read_parquet({files},hive_partitioning=false)''')


def prepare(db, private, report, args, production=True):
    audit = records(db, '''SELECT count(*) AS "rows",sum(y)::BIGINT grants,
      count(DISTINCT game_id) distinct_games,
      count(DISTINCT chooser_user_id) accounts,
      count(*) FILTER(WHERE api_status IS DISTINCT FROM 'timeout'
       OR five_second_rule_passed IS DISTINCT FROM true
       OR sf100k_nodes_requested IS DISTINCT FROM 100000
       OR chooser_user_id IS NULL OR disconnected_user_id IS NULL
       OR chooser_user_id=disconnected_user_id OR y IS NULL OR y NOT IN (0,1)
       OR engine_eval_cp_disconnected IS NULL OR ply_count IS NULL
       OR month<'2023-11' OR month>'2025-10') invalid FROM source''')[0]
    require(audit['invalid'] == 0, 'Certified source definitions failed')
    require(audit['distinct_games']==audit['rows'], 'Duplicate game IDs in source')
    if production:
        require([audit[k] for k in ['rows','grants','accounts']] == [41534331,570091,3224173],
                'Certified sample counts differ')
    json_write(report/'SOURCE_AUDIT.json', audit)
    accounts = private/'accounts.parquet'
    if not accounts.exists():
        copy_query(db, f'''SELECT chooser_user_id chooser,
          count(*) FILTER(WHERE month<'2024-11' AND (board>=2 OR board=0)) pilot_n,
          count(*) FILTER(WHERE api_last_move_at_ms>={START} AND api_last_move_at_ms<{SPLIT}) n_train
          FROM source GROUP BY 1''', accounts)
    db.execute(f'CREATE OR REPLACE VIEW accounts AS SELECT * FROM read_parquet({qs(accounts)})')
    cohort = private/'cohort.parquet'
    if not cohort.exists():
        pilot_cap = 100000 if production else 0
        old_eval_cap = 50000 if production else 0
        copy_query(db, f'''WITH ordered AS (
          SELECT *,row_number() OVER(ORDER BY md5(chooser::VARCHAR || ':20260920'),chooser) pilot_rank
          FROM accounts WHERE pilot_n>0),
          old_eval AS (SELECT chooser FROM ordered WHERE pilot_rank>{pilot_cap}
            ORDER BY md5(chooser::VARCHAR || ':20260921'),chooser LIMIT {old_eval_cap}),
          eligible AS (SELECT o.* FROM ordered o ANTI JOIN old_eval e USING(chooser)
            WHERE pilot_rank>{pilot_cap} AND n_train>0),
          ranked AS (SELECT *,row_number() OVER(ORDER BY
            md5(chooser::VARCHAR || {qs(':chooser:'+str(args.seed))}),chooser) new_rank FROM eligible)
          SELECT chooser,pilot_rank,new_rank,
            CASE WHEN new_rank<={args.dev_accounts} THEN 'development' ELSE 'evaluation' END cohort
          FROM ranked WHERE new_rank<={args.dev_accounts+args.eval_accounts}''', cohort)
    db.execute(f'CREATE OR REPLACE VIEW cohort AS SELECT * FROM read_parquet({qs(cohort)})')
    support = records(db, 'SELECT cohort,count(*) accounts FROM cohort GROUP BY 1 ORDER BY 1')
    require(len(support)==2 and support[0]['accounts']==args.dev_accounts
            and support[1]['accounts']==args.eval_accounts, 'Not enough eligible disjoint accounts')
    csv_write(report/'cohort_support.csv', support)
    json_write(report/'SAMPLE_RULE.json', dict(pilot_excluded=100000 if production else 0,
      prior_construal_eval_excluded=50000 if production else 0,
      prior_pilot_hash_seed=20260920,prior_construal_hash_seed=20260921,
      sample_seed=args.seed,required_second_year_activity=False,outcome_based_sampling=False,
      caveat='Disjoint from the specified pilot/challenge and construal cohorts; prior aggregate results were inspected. Not a preregistration claim.'))
    path = private/'sequences.parquet'
    if not path.exists():
        db.execute(f'''CREATE OR REPLACE TEMP TABLE chosen AS SELECT
          s.chooser_user_id chooser,s.game_id,c.cohort,s.api_created_at_ms start_ms,
          s.api_last_move_at_ms t,s.month,s.y,s.board,s.stage,s.ply_count ply,
          s.chooser_elo::DOUBLE rating,s.disconnected_elo::DOUBLE opponent_rating,
          s.api_speed speed,s.tc_base_s::DOUBLE tc_base,s.tc_inc_s::DOUBLE tc_inc,
          CASE WHEN s.chooser_color IN ('white','w') THEN 1
            WHEN s.chooser_color IN ('black','b') THEN 0 ELSE -1 END color,
          s.chooser_win_premium_v2::DOUBLE premium,s.chooser_draw_payoff_v2::DOUBLE draw_payoff,
          s.chooser_win_payoff_v2::DOUBLE win_payoff,
          s.chooser_pre_rd_v2::DOUBLE crd,s.disconnected_pre_rd_v2::DOUBLE drd,
          s.chooser_pre_sigma_v2::DOUBLE cvol,s.disconnected_pre_sigma_v2::DOUBLE dvol,
          s.chooser_clock_last_obs_s::DOUBLE cclock,s.disconnected_clock_last_obs_s::DOUBLE dclock,
          s.engine_eval_cp_disconnected::DOUBLE b,
          s.engine_eval_cp_disconnected_raw::DOUBLE b_raw,s.engine_eval_is_mate is_mate,
          s.sf100k_score_type_side_to_move score_type
          FROM source s JOIN cohort c ON c.chooser=s.chooser_user_id''')
        bad = records(db, '''SELECT count(*) AS "rows",
          count(*) FILTER(WHERE NOT(isfinite(premium) AND premium>0 AND isfinite(draw_payoff)
            AND isfinite(win_payoff)) OR premium IS NULL OR draw_payoff IS NULL OR win_payoff IS NULL) missing_cost,
          max(abs(win_payoff-draw_payoff-premium)) payoff_identity_max_error
          FROM chosen''')[0]
        json_write(report/'PAYOFF_AUDIT.json', bad)
        guard = int(args.timing_guard_seconds * 1000)
        db.execute(f'''CREATE OR REPLACE TEMP TABLE timing AS
          SELECT *, count(*) OVER(PARTITION BY chooser,t)>1 OR
            coalesce(max(t) OVER(PARTITION BY chooser ORDER BY t,game_id
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)+{guard}>=start_ms,false) OR
            coalesce(min(start_ms) OVER(PARTITION BY chooser ORDER BY t,game_id
              ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)<=t+{guard},false) overlapping
          FROM chosen WHERE t>={START} AND t<{END} AND start_ms>0 AND start_ms<=t
            AND speed<>'correspondence' ''')
        counts = records(db, '''SELECT (SELECT count(*) FROM chosen) selected_rows,
          count(*) time_valid_rows,count(*) FILTER(WHERE overlapping) overlapping_rows
          FROM timing''')[0]
        copy_query(db, f'''WITH valid AS (SELECT *,
          0.5-draw_payoff/(2*premium) expected_score,
          greatest(0.,-draw_payoff) loss FROM timing WHERE NOT overlapping
          AND isfinite(premium) AND premium>0 AND isfinite(draw_payoff) AND isfinite(win_payoff)
          AND abs(win_payoff-draw_payoff-premium)<=1e-6*greatest(1.,abs(premium)))
          SELECT *,CASE WHEN t<{VALID} THEN 0 WHEN t<{SPLIT} THEN 1 ELSE 2 END period
          FROM valid WHERE expected_score>=0 AND expected_score<=1
          ORDER BY chooser,t,game_id''', path)
        counts.update(retained_rows=db.execute(f'SELECT count(*) FROM read_parquet({qs(path)})').fetchone()[0],
          guard_seconds=args.timing_guard_seconds,
          time='API lastMoveAt is a proxy, not a verified action timestamp',
          selection='Overlap exclusions use neighboring observed opportunities; all candidates share these exclusions',
          expected_score='0.5-r_G/(2*premium), implied by reconstructed payoff pair; not displayed-rating Elo expectation')
        json_write(report/'TIMING_AND_COST_SELECTION.json', counts)
    return path


def encode(frame, min_cell_count=10):
    """All empirical scaling, support and baseline tiers use early development data only."""
    df = frame.sort_values(['chooser','t','game_id']).reset_index(drop=True).copy()
    e = df.expected_score.to_numpy(float)
    q = np.minimum(np.searchsorted(Q_EDGES[1:-1], e, side='right'), 4)
    df['q'] = q
    df['cell'] = (df.board*4+df.stage)*5+q
    fitmask = (df.cohort=='development') & (df.period==0)
    counts = df.loc[fitmask].groupby('cell').size()
    supported = sorted(int(c) for c,n in counts.items() if n >= min_cell_count)
    require(C0 in supported and C1 in supported, 'Both fixed 11–40-ply / E=[.4,.6) anchors need early-training support')
    keep = df.cell.isin(supported)
    support_rows = df.assign(retained=keep).groupby(['cohort','period','retained'],observed=True).agg(
        opportunities=('y','size'),grants=('y','sum')).reset_index().to_dict('records')
    # Baseline rating is fixed at the first valid pre-window observation, before support dropping.
    # Keep the first row even when its rating is missing; groupby.first would
    # silently borrow a later rating. Missing initial ratings use the stated fallback.
    baseline = df[df.period<2].drop_duplicates('chooser',keep='first').set_index('chooser').rating
    df = df[keep].copy().reset_index(drop=True)
    require(len(df)>0, 'No observations in common early-training support')
    df['prior_group'] = np.searchsorted([1600,2000,2400],df.chooser.map(baseline).fillna(1800),side='right')
    df['tier'] = np.searchsorted([1600,2000,2400],df.rating.fillna(1800),side='right')
    raw = df.b_raw.to_numpy(float)
    df['perception_valid'] = np.isfinite(raw) & (df.is_mate==False) & (df.score_type=='cp')
    # Exact raw-score half-open bins recover the sigma=0 perception comparator.
    df['perception_board'] = np.searchsorted(B_EDGES[1:-1],raw,side='right')
    df['boundary'] = np.isin(raw,B_EDGES[1:-1])
    f = (df.cohort=='development') & (df.period==0)
    columns, names = [], []
    def add(name, a): columns.append(np.asarray(a,float)); names.append(name)
    for name,scale,center in [('rating',400,1800),('crd',100,60),('drd',100,60),
                              ('cvol',.05,.06),('dvol',.05,.06)]:
        v=df[name].to_numpy(float); missing=~np.isfinite(v)
        add(name,np.clip((np.where(missing,center,v)-center)/scale,-8,8))
        add(name+'_missing',missing)
    for name in ['cclock','dclock','tc_base','tc_inc']:
        v=df[name].to_numpy(float);missing=~np.isfinite(v)|(v<0)
        add(name,np.log1p(np.where(missing,0,v))/4)
        add(name+'_missing',missing)
    speeds = df.speed.fillna('missing')
    levels = sorted(set(speeds[f]))
    for speed in levels[1:]: add('speed_'+str(speed),speeds==speed)
    add('speed_unseen',~speeds.isin(levels))
    # Month-of-year seasonality is extrapolatable to year two; no test-only month dummy.
    for month in range(1,12): add('month_of_year_'+str(month),df.month.str[-2:].astype(int)==month)
    add('white',df.color==1)
    add('color_missing',df.color<0)
    Z=np.column_stack(columns)
    means=Z[f].mean(axis=0); sd=Z[f].std(axis=0)
    active=sd>1e-10
    Z=(Z[:,active]-means[active])/sd[active]
    names=np.array(names)[active].tolist()
    # There is no intercept or separate board/stage/E/gap/K/payoff control.
    meta=dict(support=supported,anchors=[C0,C1],q_edges=Q_EDGES,board_edges=['-inf',-300,-100,100,300,'inf'],
      z_names=names,means=means[active].tolist(),scales=sd[active].tolist(),
      normalization_data='development before 2024-08-01',time_controls='speed categories plus log base/increment',
      calendar='month-of-year, not unidentified year-two date effects',
      board_boundary_note='Main panel retains its frozen <= boundaries. Perception uses half-open raw bins for all matched comparators.',
      support_selection=support_rows)
    arrays={}
    for cohort in ['development','evaluation']:
        m=(df.cohort==cohort).to_numpy(); sub=df[m]
        accounts,ids=np.unique(sub.chooser.to_numpy(),return_inverse=True)
        n=np.bincount(ids,minlength=len(accounts));ptr=np.r_[0,np.cumsum(n)]
        require(np.all(ids==np.repeat(np.arange(len(accounts)),n)), 'Account ordering failed')
        d=dict(Z=Z[m],y=sub.y.to_numpy(float),ptr=ptr.astype(np.int64),ids=ids.astype(np.int64),
          period=sub.period.to_numpy(np.int64),cell=sub.cell.to_numpy(np.int64),
          board=sub.board.to_numpy(np.int64),stage=sub.stage.to_numpy(np.int64),q=sub.q.to_numpy(np.int64),
          kappa=sub.premium.to_numpy(float)/10,loss=sub.loss.to_numpy(float)/10,
          b=sub.b_raw.to_numpy(float),tier=sub.tier.to_numpy(np.int64),
          group=sub.prior_group.to_numpy(np.int64)[ptr[:-1]],
          perception_valid=sub.perception_valid.to_numpy(bool),boundary=sub.boundary.to_numpy(bool),
          perception_board=sub.perception_board.to_numpy(np.int64),
          accounts=accounts.astype(str),time=sub.t.to_numpy(np.int64))
        arrays[cohort]=d
    return arrays,meta


def subset(d, mask):
    mask=np.asarray(mask,bool);old=d['ids'][mask]
    kept,new=np.unique(old,return_inverse=True); n=np.bincount(new,minlength=len(kept))
    out={k:v[mask] for k,v in d.items() if k not in ['ptr','ids','group','accounts','aw']}
    out.update(ptr=np.r_[0,np.cumsum(n)].astype(np.int64),ids=new.astype(np.int64),
      group=d['group'][kept],accounts=d['accounts'][kept])
    if 'aw' in d: out['aw']=d['aw'][kept]
    return out


def perception_subset(d, support, drop_boundaries=False):
    pcell=(d['perception_board']*4+d['stage'])*5+d['q']
    mask=d['perception_valid'] & np.isin(pcell,support)
    if drop_boundaries: mask &= ~d['boundary']
    out=subset(d,mask)
    out['board']=out['perception_board'].copy()
    out['cell']=(out['board']*4+out['stage'])*5+out['q']
    return out
