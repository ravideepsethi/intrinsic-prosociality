"""Local-only analysis contract; frozen comparison code is vendored unchanged."""
from cache_auth import *
import pyarrow.compute as pc
import author_history as authors
import iv_numerics as num
import audit_logic as audit
import expanded_logic as design
import expanded_stats as stats
import rebuild_logic as rebuild
import followup_logic as history

VERSION='1.1.0'
ANALYSIS_REL='derived/replication/run2_cached_analysis_v101_PRIVATE'
NEW_ID_BASE=1 << 40
SPEC=next(s for s in design.specifications() if s['name']=='ordinary90_placebo')
QUERY_COLUMNS=['row_id','game_id','month_code','archive_start_ms','anchor_ms',
    'recipient_id','opponent_id','recipient_rating','opponent_rating','tc_base_s','tc_inc_s',
    'status','recipient_username','opponent_username','ordinary_narrow','previous_frame',
    'pre_games_30d','eligible_main','first_observed_pair','expected_n7']
COUNT_COLUMNS=[f'{v}_{d}' for d in (90,30) for v in audit.COUNTS]
OLD_COLUMNS=['row_id','game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms',
    'month_code','recipient_rating','opponent_rating','tc_base_s','tc_inc_s',
    'pre_games_30d','eligible_main',
    'first_observed_pair','history_complete','at_risk_90','ordinary_narrow','complete90',
    'n_7d','adjusted_7d','expected_7d','counterparts_7d','y','reached',
    'outcome_gid','outcome_t','outcome_start','outcome_opponent']+COUNT_COLUMNS

def no_network():
    import socket
    def blocked(*a,**k):raise RuntimeError('Network access disabled in cached analysis')
    socket.create_connection=blocked
    socket.socket.connect=blocked
    socket.socket.connect_ex=blocked

def selected_baseline(path):
    d=arrays(io.read(path))
    keep,flow=design.entry_mask(d,90)
    keep &= np.asarray(d['ordinary_narrow'],bool)&np.asarray(d['complete90'],bool)
    return {k:v[keep] for k,v in d.items()},flow

def verify_baseline(path):
    """Numerical bridge to the reviewed result before applying author exclusions."""
    d,flow=selected_baseline(path)
    saved=[r for r in io.load(VENDOR/'comparison_original/evidence/expanded_estimates.json')
           if r.get('specification')=='ordinary90_placebo']
    result=stats.estimate(d,SPEC)
    for old in saved:
        row=next(r for r in result['estimates'] if r.get('outcome')==old['outcome'])
        for key in ('n','row_set_sha256','events'):
            if row[key]!=old[key]:raise RuntimeError('Original placebo bridge failed: '+key)
        for key in ('coefficient_pp','standard_error_pp'):
            if not np.isclose(row[key],old[key],rtol=1e-8,atol=1e-10):
                raise RuntimeError('Original placebo numerical bridge failed: '+key)
    return d,result

def assert_rows(c,query,expected,label):
    n,u=c.execute('SELECT count(*),count(DISTINCT row_id) FROM ('+query+')').fetchone()
    if n!=expected or u!=expected:raise RuntimeError(label+' lost or duplicated query rows')

def all_known(d,columns):
    for k in columns:
        a=np.asarray(d[k])
        if a.dtype.kind in 'fi' and not np.isfinite(a).all():raise RuntimeError('Missing required '+k)
        if a.dtype.kind=='O' and any(x is None for x in a):raise RuntimeError('Missing required '+k)
