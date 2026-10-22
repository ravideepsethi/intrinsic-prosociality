"""Historical IV projection semantics, with an explicit extended calendar."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
import iv_numerics as num
from common import *

def projected_schema():
    return pa.schema([('j',pa.int64()),('i',pa.int64()),('t',pa.int64()),('start',pa.int64()),
        ('ord',pa.int64()),('gid',pa.string()),('y',pa.bool_()),('arm',pa.bool_()),
        ('fair',pa.bool_()),('rt',pa.bool_()),('cell',pa.int16())])

def project_batch(b):
    if any(b[x].null_count for x in ['chooser_user_id','disconnected_user_id','anchor_ms','utc_ms','archive_ordinal','grant','timeout_chooser_win']):
        raise RuntimeError('Missing required history identity, time or arm')
    j=arr(b,'chooser_user_id',np.int64);i=arr(b,'disconnected_user_id',np.int64)
    t=arr(b,'anchor_ms',np.int64);start=arr(b,'utc_ms',np.int64)
    if np.any((j<0)|(i<0)|(j>=2**32)|(i>=2**32)|(j==i)|(t<start)):
        raise RuntimeError('Invalid identity or timestamp ordering')
    if not np.isin(arr(b,'grant'),[0,1]).all():raise RuntimeError('Nonbinary draw outcome')
    y=arr(b,'grant',bool);win=arr(b,'timeout_chooser_win',bool)
    if np.any(y&win):raise RuntimeError('A kindness draw cannot also be a chooser win')
    speed=np.array([SPEEDS.index(x) if x in SPEEDS else -1 for x in b['speed'].to_pylist()],np.int8)
    rt=(speed>=0)&(arr(b,'tc_base_s',float)>0)
    cp=arr(b,'cp',float);ply=arr(b,'ply',float)
    gap=arr(b,'opp_rating',float)-arr(b,'rating',float)
    valid=np.isfinite(cp)&np.isfinite(ply)&np.isfinite(gap)&rt
    fair=np.isfinite(cp)&(cp>=-100)
    cell=num.state_cells(np.nan_to_num(cp),np.nan_to_num(ply),np.maximum(speed,0),np.nan_to_num(gap))
    out=pa.table(dict(j=j,i=i,t=t,start=start,ord=arr(b,'archive_ordinal',np.int64),
        gid=b['game_id'],y=y,arm=(y|win)&valid,fair=fair,rt=rt,cell=cell),schema=projected_schema())
    return out,(num.user_hash(j)%np.uint64(16)).astype(np.int8)

def empty_deltas(starts=STARTS):
    shape=(2,len(starts)+1,4,4,500)
    return np.zeros(shape,np.int64),np.zeros(shape,np.int64)

def add_deltas(n,s,b,starts=STARTS):
    use=arr(b,'arm',bool)
    j=arr(b,'j',np.int64)[use];i=arr(b,'i',np.int64)[use]
    t=arr(b,'t',np.int64)[use];y=arr(b,'y',np.int64)[use];cell=arr(b,'cell',np.int64)[use]
    if np.any((cell<0)|(cell>=500)):raise RuntimeError('Invalid historical state cell')
    jf=(num.user_hash(j)%np.uint64(4)).astype(np.int64);rf=(num.user_hash(i)%np.uint64(4)).astype(np.int64)
    for ix,lag in enumerate((7,30)):
        first=np.searchsorted(starts,t+lag*DAY,side='right')
        flat=(((first*4+jf)*4+rf)*500+cell)
        n[ix]+=np.bincount(flat,minlength=n[ix].size).reshape(n[ix].shape)
        s[ix]+=np.bincount(flat,weights=y,minlength=s[ix].size).reshape(s[ix].shape).astype(np.int64)

def assert_same_projection(c,new,old):
    """Full multiset comparison, not just matching row counts."""
    a=scan(new);b=scan(old);cols=','.join(ident(n) for n in projected_schema().names)
    query=f'''SELECT count(*) FROM ((SELECT {cols} FROM {a} EXCEPT ALL SELECT {cols} FROM {b})
        UNION ALL (SELECT {cols} FROM {b} EXCEPT ALL SELECT {cols} FROM {a}))'''
    n=c.execute(query).fetchone()[0]
    if n:raise RuntimeError(f'Historical projection bridge differs in {n} rows')
    return dict(status='EXACT_OLD_MONTH_PROJECTION_BRIDGE_OK',different_rows=0)

def assert_reference_bridge(old_n,old_s,pilot_n,pilot_s):
    # Extended calendar indices 2..25 are the original 24 target months.
    # The original terminal bucket is deliberately excluded from this comparison.
    if not np.array_equal(old_n[:,2:26],pilot_n[:,:24]):raise RuntimeError('Historical reference training counts changed')
    if not np.array_equal(old_s[:,2:26],pilot_s[:,:24]):raise RuntimeError('Historical reference training grants changed')
    old=num.expanding_reference(old_n[:,:-1],old_s[:,:-1])[:,2:26]
    expected=num.expanding_reference(pilot_n[:,:24],pilot_s[:,:24])
    if not np.allclose(old,expected,atol=1e-13,rtol=0,equal_nan=True):raise RuntimeError('Historical cross-fit references changed')
    return dict(status='EXACT_OLD_REFERENCE_COUNTS_BRIDGE_OK',months=24,counts_equal=True,
        grants_equal=True,reference_tolerance=1e-13,old_history_start='2023-11-01')
