"""Pure, testable primitives. No network access, no automatic causal certification."""
from __future__ import annotations
import datetime as dt
import hashlib
import math
import re
from collections import Counter
from typing import Any
import numpy as np
import iv_numerics as num

DAY = 86_400_000
MONTHS = tuple(f'{v//12:04d}-{v%12+1:02d}' for v in range(2023*12+10,2025*12+10))
STARTS = np.array([int(dt.datetime.fromisoformat(m+'-01').replace(tzinfo=dt.timezone.utc).timestamp()*1000) for m in MONTHS],np.int64)
PANEL_END = int(dt.datetime(2025,11,1,tzinfo=dt.timezone.utc).timestamp()*1000)
PILOT_SAMPLE_SEED = b'chooser-leniency-independent-comparison-200k-v100-20260906|'
GID = re.compile(r'^[A-Za-z0-9]{8}$')
NARROW = frozenset({'mate','resign','stalemate'})
BROAD = NARROW | {'draw'}
TERMINAL = BROAD | {'outoftime','timeout','aborted','nostart','cheat','variantend','unknownfinish'}
SOURCES = frozenset({'pool','lobby','friend','api','arena','tournament','swiss','simul','ai','import','position'})
SPEEDS = {'ultrabullet':0,'bullet':1,'blitz':2,'rapid':3,'classical':4}
PILOT_Z_SD = 0.059288502306202064
PILOT_RF = 0.00029038213482045856


def independent_indices(ids: list[str], size: int) -> np.ndarray:
    """Fixed SHA-256 bottom-k: no source, terminal result or availability enters selection."""
    if not 0 < size <= len(ids):
        raise ValueError('Pilot size must be positive and not exceed the frame')
    if len(set(ids)) != len(ids) or any(not isinstance(g,str) or not GID.fullmatch(g) for g in ids):
        raise ValueError('Frame game IDs must be unique, exact case-sensitive eight-character strings')
    # Store full hex strings so embedded NUL bytes cannot truncate a comparison key.
    keys = np.array([hashlib.sha256(PILOT_SAMPLE_SEED+g.encode('ascii')).hexdigest() for g in ids],dtype='S64')
    return np.lexsort((np.asarray(ids,dtype='U8'),keys))[:size].astype(np.int64)


def terminal_label(s: Any) -> str:
    s = s.strip().lower() if isinstance(s,str) else None
    return s if s in TERMINAL else ('MISSING' if s is None or not s else 'OTHER_STATUS')


def safe_source(s: Any) -> str:
    return s if s in SOURCES else ('MISSING' if s is None else 'OTHER_EXPLICIT_SOURCE')


def normal_group(status: str | None, include_draw: bool = False) -> bool:
    return status in (BROAD if include_draw else NARROW)


def _int(v):
    return int(v) if isinstance(v,int) and not isinstance(v,bool) else None


def _rating(v):
    if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v > 0:
        return float(v)
    return None


def normalize_export(o: dict[str,Any], expected_id: str) -> tuple[dict[str,Any],list[str]]:
    """Read only historical game-export fields. Never infer absent chat/takeback data."""
    errors = []
    ids = [o[k] for k in ('id','game_id') if o.get(k) is not None]
    if not ids or any(v != expected_id for v in ids): errors.append('GAME_ID_MISMATCH')
    srcs = [o[k] for k in ('source','api_source') if o.get(k) is not None]
    if any(not isinstance(x,str) for x in srcs): errors.append('INVALID_SOURCE_TYPE')
    srcs = {x.strip().lower() for x in srcs if isinstance(x,str) and x.strip()}
    if len(srcs)>1: errors.append('ROW_SOURCE_CONFLICT')
    status = o.get('status')
    status = status.strip().lower() if isinstance(status,str) else None
    variant = o.get('variant'); variant = variant.get('key') if isinstance(variant,dict) else variant
    variant = variant.lower() if isinstance(variant,str) else None
    r = dict(game_id=expected_id,source=next(iter(srcs)) if len(srcs)==1 else None,
             status=status,api_start_ms=_int(o.get('createdAt')),anchor_ms=_int(o.get('lastMoveAt')),
             rated=o.get('rated') if isinstance(o.get('rated'),bool) else None,
             variant=variant,speed=o.get('speed').strip().lower() if isinstance(o.get('speed'),str) else None,
             winner=o.get('winner') if o.get('winner') in ('white','black') else None)
    clock = o.get('clock') if isinstance(o.get('clock'),dict) else {}
    r['tc_base_s'],r['tc_inc_s'] = _int(clock.get('initial')),_int(clock.get('increment'))
    players = o.get('players') if isinstance(o.get('players'),dict) else {}
    for side in ('white','black'):
        p = players.get(side) if isinstance(players.get(side),dict) else {}
        user = p.get('user') if isinstance(p.get('user'),dict) else {}
        names = [v.lower().strip() for v in (user.get('id'),user.get('name'),p.get('name')) if isinstance(v,str) and v.strip()]
        if len(set(names))>1: errors.append(side.upper()+'_USERNAME_CONFLICT')
        r[side+'_username'] = names[0] if names else None
        r[side+'_rating'] = _rating(p.get('rating'))
        # Optional provisional flags are not imputed from absence.
        r[side+'_provisional'] = p.get('provisional') if isinstance(p.get('provisional'),bool) else None
    return r,errors


CORE_FIELDS = ('source','status','api_start_ms','anchor_ms','rated','variant','speed','winner',
               'tc_base_s','tc_inc_s','white_username','black_username','white_rating','black_rating')


def merge_records(records: list[tuple[dict,list[str]]], game_id: str) -> tuple[dict,list[str]]:
    """Merge only agreeing observed fields. Disagreement is retained, never majority-voted."""
    out = {'game_id':game_id,'metadata_records_audited':len(records)}
    errors = set(e for _,errs in records for e in errs)
    for name in CORE_FIELDS + ('white_provisional','black_provisional'):
        vals = {r[name] for r,_ in records if r.get(name) is not None}
        out[name] = next(iter(vals)) if len(vals)==1 else None
        if len(vals)>1: errors.add('CONFLICT_'+name.upper())
    return out,sorted(errors)


def validate_metadata(r: dict, frame: dict, ledger: dict, prior_errors: list[str]) -> list[str]:
    errors = set(prior_errors)
    if ledger.get('source_conflict'): errors.add('LEDGER_SOURCE_CONFLICT')
    source=ledger.get('source')
    if source is not None and r.get('source') is not None and source!=r['source']:
        errors.add('SOURCE_LEDGER_DISAGREEMENT')
    if r.get('source') is None: r['source']=source # an explicit, independently recovered source is allowed
    if r.get('source') is None: errors.add('SOURCE_MISSING')
    ls=ledger.get('api_status')
    if ls is not None and r.get('status') is not None and ls!=r['status']: errors.add('STATUS_LEDGER_DISAGREEMENT')
    if ls is None and r.get('status') is not None and ledger.get('metadata_usable_records',0)>0:
        errors.add('LEDGER_STATUS_UNRESOLVED')
    if 'created_at_ms' in ledger and r.get('api_start_ms') is not None:
        if ledger['created_at_ms'] is None: errors.add('LEDGER_CREATED_TIME_UNRESOLVED')
        elif ledger['created_at_ms']!=r['api_start_ms']: errors.add('CREATED_TIME_LEDGER_DISAGREEMENT')
    if r.get('status') is None: r['status']=ls
    # Nonpool games need only a conflict-free explicit source to be excluded from a pool frame.
    if r.get('source')!='pool': return sorted(errors)
    for field in ('status','api_start_ms','anchor_ms','rated','variant','speed','tc_base_s','tc_inc_s',
                  'white_username','black_username','white_rating','black_rating'):
        if r.get(field) is None: errors.add('MISSING_'+field.upper())
    if r.get('status') not in TERMINAL: errors.add('NOT_RECOGNIZED_FINISHED_GAME')
    if r.get('rated') is not True: errors.add('NOT_RATED')
    if r.get('variant')!='standard': errors.add('NOT_STANDARD')
    if r.get('speed') not in SPEEDS: errors.add('NOT_REALTIME')
    if r.get('speed') is not None and r['speed']!=frame['speed_partition']: errors.add('SPEED_FRAME_DISAGREEMENT')
    start,anchor = r.get('api_start_ms'),r.get('anchor_ms')
    if start is not None and (start<=0 or start//1000 != frame['utc_ms']//1000):
        errors.add('CREATED_TIME_FRAME_DISAGREEMENT')
    if start is not None and anchor is not None and anchor<start: errors.add('ANCHOR_PRECEDES_CREATION')
    if r.get('tc_base_s') is not None and r['tc_base_s']<=0: errors.add('NONPOSITIVE_BASE_TIME')
    if r.get('tc_inc_s') is not None and r['tc_inc_s']<0: errors.add('NEGATIVE_INCREMENT')
    if r.get('white_username') is not None and r['white_username']==r.get('black_username'): errors.add('SAME_PLAYER')
    if not ledger.get('stage07_identity_agrees',True): errors.add('PRIOR_IDENTITY_GATE_FAILED')
    if r.get('status') in NARROW and ledger.get('in_certified_stage07'): errors.add('NORMAL_END_IN_STAGE07')
    if r.get('status') in ('mate','resign') and r.get('winner') not in ('white','black'): errors.add('MISSING_DECISIVE_WINNER')
    return sorted(errors)


def first_other_and_history(h: dict[str,np.ndarray], q: dict[str,np.ndarray]) -> dict[str,np.ndarray]:
    """Handles multiple exposures per person; skips ineligible games, never drops the person."""
    nq=len(q['sample_row'])
    result={'sample_row':q['sample_row'].copy(),'reached':np.zeros(nq,bool),'y':np.zeros(nq,bool),
            'outcome_t':np.full(nq,-1,np.int64),'outcome_start':np.full(nq,-1,np.int64),
            'outcome_opponent':np.full(nq,-1,np.int64),'own_fair90':np.zeros(nq,np.int64),
            'own_kind90':np.zeros(nq,np.int64),'lead_present':np.zeros(nq,bool),'lead_y':np.zeros(nq,bool)}
    use=np.flatnonzero(h['fair'])
    if not len(use): return result
    order=np.lexsort((h['gid'][use],h['ord'][use],h['t'][use],h['j'][use])); idx=use[order]
    ids=h['j'][idx]
    for k in range(nq):
        recipient=q['recipient_id'][k]; opponent=q['opponent_id'][k]; anchor=q['anchor_ms'][k]
        lo=np.searchsorted(ids,recipient,side='left'); hi=np.searchsorted(ids,recipient,side='right')
        if hi==lo: continue
        ii=idx[lo:hi]; tt=h['t'][ii]
        a=np.searchsorted(tt,anchor,side='right'); b=np.searchsorted(tt,anchor+90*DAY,side='right')
        for kk in range(a,b):
            e=ii[kk]
            if h['i'][e]==opponent or h['start'][e]<=anchor or h['gid'][e]==q['game_id'][k]: continue
            result['reached'][k]=True; result['y'][k]=h['y'][e]
            result['outcome_t'][k]=h['t'][e]; result['outcome_start'][k]=h['start'][e]
            result['outcome_opponent'][k]=h['i'][e]; break
        end=q['archive_start_ms'][k]-7*DAY
        a=np.searchsorted(tt,end-90*DAY,side='left'); b=np.searchsorted(tt,end,side='left')
        prior=ii[a:b]
        result['own_fair90'][k]=len(prior); result['own_kind90'][k]=int(h['y'][prior].sum())
        for e in prior[::-1]:
            if h['i'][e]!=opponent:
                result['lead_present'][k]=True; result['lead_y'][k]=h['y'][e]; break
    return result


def _sumsq(s: np.ndarray,*keys: np.ndarray) -> float:
    _,codes=num.factor(*keys)
    sums=np.bincount(codes,weights=s)
    return float(sums@sums)


def dependent_meat(s,recipient,opponent,date=None):
    """CR0 dyadic overlap; optionally union with same-day dependence, inclusion-exclusion.

    Counts each ordered observation pair once when it shares any account in either
    role, or shares the exposure date. Not a guarantee against nonlocal network shocks.
    """
    s=np.asarray(s,float); i=np.asarray(recipient,np.int64); j=np.asarray(opponent,np.int64)
    if np.any(i==j): raise ValueError('Self pairs are invalid')
    low,high=np.minimum(i,j),np.maximum(i,j)
    both_s=np.r_[s,s]; accounts=np.r_[i,j]
    value=_sumsq(both_s,accounts)-_sumsq(s,low,high)
    if date is not None:
        date=np.asarray(date,np.int64)
        value += _sumsq(s,date)-_sumsq(both_s,accounts,np.r_[date,date])+_sumsq(s,low,high,date)
    return value


def fit_reduced_form(y,z,i,j,day,include_day,scale=PILOT_Z_SD):
    y=np.asarray(y,float); z=np.asarray(z,float)
    if not np.isfinite(y).all() or not np.isfinite(z).all(): raise ValueError('Nonfinite residuals')
    den=float(z@z)
    if den<1e-20: return {'supported':False,'reason':'NO_RESIDUAL_SCORE_VARIATION'}
    beta=float(z@y)/den; score=z*(y-beta*z)
    v=dependent_meat(score,i,j,day if include_day else None)/den**2
    native=float(np.sqrt(np.mean(z*z)))
    ans={'coefficient_per_unit_score':beta,'coefficient_pp_per_pilot_SD':100*beta*scale,
         'coefficient_pp_per_native_SD':100*beta*native,'pilot_score_SD':scale,'native_residual_score_SD':native}
    if not math.isfinite(v) or v<=0:
        return {**ans,'supported':False,'reason':'NONPOSITIVE_DEPENDENCE_VARIANCE_NOT_REPAIRED'}
    se=math.sqrt(v); zcrit=1.959963984540054
    low,high=beta-zcrit*se,beta+zcrit*se
    ans.update(supported=True,standard_error_per_unit_score=se,
               standard_error_pp_per_pilot_SD=100*se*scale,
               ci95_low_pp_per_pilot_SD=100*low*scale,ci95_high_pp_per_pilot_SD=100*high*scale,
               p_value_asymptotic=math.erfc(abs(beta/se)/math.sqrt(2)),
               MDE80_pp_per_pilot_SD=100*(1.959963984540054+0.8416212335729143)*se*scale,
               ci90_low_pp_per_pilot_SD=100*(beta-1.6448536269514722*se)*scale,
               ci90_high_pp_per_pilot_SD=100*(beta+1.6448536269514722*se)*scale,
               reference_IV_RF_pp=100*PILOT_RF)
    for margin_pp in (0.03,0.015):
        ans[f'exploratory_TOST_within_plusminus_{margin_pp}_pp']=(
            ans['ci90_low_pp_per_pilot_SD']>-margin_pp and ans['ci90_high_pp_per_pilot_SD']<margin_pp)
    ans['exclusion_certified']=False
    return ans


def model_design(d: dict[str,np.ndarray],mask: np.ndarray,lag=7,with_history=False):
    n=int(mask.sum()); x={k:np.asarray(v)[mask] for k,v in d.items()}
    controls=[]; names=[]
    def add(name,value):
        a=np.asarray(value,float)
        if not np.isfinite(a).all(): raise ValueError('Unavailable control '+name)
        sd=float(a.std()); controls.append((a-a.mean())/(sd if sd>1e-12 else 1)); names.append(name)
    ir=x['recipient_rating']; jr=x['opponent_rating']; gap=(jr-ir)/100
    add('recipient_rating',ir); add('rating_gap',gap); add('rating_gap_square',gap*gap); add('abs_rating_gap',np.abs(gap))
    add('log_opponent_prior_decisions',np.log1p(x[f'n_{lag}d']))
    add('log_opponent_prior_counterparts',np.log1p(x[f'counterparts_{lag}d']))
    add('opponent_history_expected_rate',x[f'expected_{lag}d'])
    if with_history:
        add('log_recipient_prior_fair',np.log1p(x['own_fair90']))
        add('recipient_prior_kind_indicator',(x['own_kind90']>0).astype(float))
    _,cell=num.factor(x['month_code'],x['tc_base_s'],x['tc_inc_s'],np.floor((ir+jr)/200).astype(np.int64))
    day=x['archive_start_ms']//DAY; hour=(x['archive_start_ms']//3_600_000)%168
    groups=[cell,day,hour]
    matrix=np.column_stack(controls+[x[f'adjusted_{lag}d'],x['y'].astype(float),x['reached'].astype(float)])
    res,info=num.partial_out(matrix,groups,len(controls))
    return res,dict(n=n,assignment_cells=int(len(np.unique(cell))),continuous_controls=names,
        unavailable_controls=['pregame_rating_deviation','all_game_30d_volume','internal_conduct_score'],**info)
