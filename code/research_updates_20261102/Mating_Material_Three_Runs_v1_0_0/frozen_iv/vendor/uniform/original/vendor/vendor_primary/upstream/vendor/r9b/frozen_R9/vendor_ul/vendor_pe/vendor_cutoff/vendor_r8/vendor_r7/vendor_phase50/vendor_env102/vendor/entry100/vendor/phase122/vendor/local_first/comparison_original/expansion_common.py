"""Frozen sampling, typed metadata, precision planning, and private archives."""
from __future__ import annotations
import hashlib, json, math, os, re, shutil, statistics, zipfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import local_io as io
import preliminary_core as core
from iv_numerics import user_hash

VERSION='1.0.0'
MODULUS=32
OLD_MODULUS=1024
SEED=2026090601
OLD_ROWS=1912023
MONTHS=core.MONTHS[:21]
SPEEDS=tuple(core.SPEEDS)
BASE=Path('/Volumes/XT_Pro/lichess_kindness')
OLD_REL='derived/replication/chooser_leniency_validity_local_v100_PRIVATE/20260906T052017Z_46893'
OUT_REL='derived/replication/comparison_expansion_v100_PRIVATE'
CHRON_REL='output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/chronology_input_manifest.tsv'
EXPANDED_REL='derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7'
ORDER_SEED=b'chooser-comparison-expansion-v100-fetch-order-20260911|'
FRAME_FIELDS=['game_id','utc_ms','archive_ordinal','white_id','black_id','recipient_id','opponent_id','recipient_color','month','speed_partition']
META_FIELDS=list(core.CORE_FIELDS)+['white_provisional','black_provisional']

def bits(ids):
    if any(not isinstance(g,str) or core.GID.fullmatch(g) is None for g in ids):
        raise ValueError('Invalid case-sensitive 8-character game ID')
    return user_hash(np.array(ids,dtype='S8').view('<u8').reshape(-1)^np.uint64(SEED))

def selected(ids,modulus=MODULUS):
    if modulus<2 or modulus&(modulus-1):raise ValueError('Power-of-two modulus required')
    return (bits(ids)&np.uint64(modulus-1))==0

def scalar_bits(g):
    if not isinstance(g,str) or core.GID.fullmatch(g) is None:return None
    mask=(1<<64)-1
    x=(int.from_bytes(g.encode('ascii'),'little')^SEED)+0x9e3779b97f4a7c15
    x &= mask
    x=((x^(x>>30))*0xbf58476d1ce4e5b9)&mask
    x=((x^(x>>27))*0x94d049bb133111eb)&mask
    return x^(x>>31)

def new_id(g):
    h=scalar_bits(g)
    return h is not None and (h&(MODULUS-1))==0 and (h&(OLD_MODULUS-1))!=0

def frame_schema():
    ints={'utc_ms','archive_ordinal','white_id','black_id','recipient_id','opponent_id'}
    return pa.schema([(n,pa.int64() if n in ints else pa.string()) for n in FRAME_FIELDS]+
                     [('previous_frame',pa.bool_()),('retrieval_rank',pa.binary(32))])

def orient(t,month,speed):
    ids=t['game_id'].to_pylist();h=bits(ids)
    w=io.arr(t,'white_id');b=io.arr(t,'black_id');start=io.arr(t,'utc_ms')
    if any(t[x].null_count for x in ('utc_ms','archive_ordinal','white_id','black_id')):
        raise RuntimeError('Null selected chronology fields; no silent exclusion')
    if np.any((start<int(core.STARTS[0]))|(start>=int(core.STARTS[21]))|(w<=0)|(b<=0)|(w==b)):
        raise RuntimeError('Selected chronology row violates inherited frame rules')
    rw=((h>>np.uint64(32))&np.uint64(1))==0
    d={n:t[n] for n in ('game_id','utc_ms','archive_ordinal','white_id','black_id')}
    d.update(recipient_id=np.where(rw,w,b),opponent_id=np.where(rw,b,w),recipient_color=np.where(rw,'white','black'),
             month=[month]*len(t),speed_partition=[speed]*len(t),previous_frame=(h&np.uint64(1023))==0,
             retrieval_rank=[hashlib.sha256(ORDER_SEED+g.encode('ascii')).digest() for g in ids])
    return pa.table(d,schema=frame_schema())

def metadata_schema():
    ints={'api_start_ms','anchor_ms','tc_base_s','tc_inc_s'}
    floats={'white_rating','black_rating'};bools={'rated','white_provisional','black_provisional'}
    return pa.schema([('game_id',pa.string())]+[(n,pa.int64() if n in ints else pa.float64() if n in floats else pa.bool_() if n in bools else pa.string()) for n in META_FIELDS]+[('record_errors',pa.string())])

def normalize(obj):
    gid=obj.get('id',obj.get('game_id'))
    if not isinstance(gid,str) or core.GID.fullmatch(gid) is None:return None
    r,errors=core.normalize_export(obj,gid)
    return {f.name:((';'.join(errors)) if f.name=='record_errors' else r.get(f.name)) for f in metadata_schema()}

def metadata_errors(row,frame):
    errors=set(filter(None,(row.get('record_errors') or '').split(';')))
    if row.get('source') not in core.SOURCES:errors.add('UNKNOWN_OR_MISSING_SOURCE')
    # Non-pool source alone excludes the game; preserve its row and every observed field.
    if row.get('source')=='pool':
        errors.update(core.validate_metadata(dict(row),frame,{},[]))
    return sorted(errors)

def precision_plan():
    nd=statistics.NormalDist();z=nd.inv_cdf(.95);zpower=nd.inv_cdf(.9)
    se=.028292388191929772;margin=.015;new_multiplier=OLD_MODULUS/MODULUS-1
    target=margin/(z+zpower);projected=se/math.sqrt(new_multiplier)
    power=max(0,2*nd.cdf(margin/projected-z)-1)
    return dict(previous_frame_rows=OLD_ROWS,modulus=MODULUS,total_expected_multiplier=32,new_expected_multiplier=31,
        expected_total_frame_rows=OLD_ROWS*32,expected_additional_frame_rows=OLD_ROWS*31,
        prior_placebo_SE_pp_per_reference_SD=se,reference_score_SD=.059411690344000595,
        equivalence_margin_pp_per_reference_SD=margin,equivalence_test='two one-sided 5% tests, 90% CI',
        target_power_if_true_effect_zero=.8,target_SE_pp_per_reference_SD=target,
        projected_new_sample_SE_pp_per_reference_SD=projected,projected_equivalence_power_at_zero=power,
        projected_new_placebo_rows=307863*31,projected_new_entry_rows=475568*31,
        approximation='SE scales as 1/sqrt(sample multiplier). Shared accounts, dates and outcome reuse may prevent this scaling.',
        guaranteed_power=False,previous_estimates_already_known=True,new_game_ids_not_an_independent_outcome_holdout=True,
        stopping_rule='fixed 1-in-32 frame; no stopping or expansion based on a new coefficient, p-value or CI',
        known_rate_games_per_second=29.05,uncached_hours=OLD_ROWS*31/29.05/3600)

def relocated(project,value):
    p=Path(value)
    if p.is_absolute():
        try:p=p.relative_to(BASE)
        except ValueError:raise RuntimeError('Source path outside recorded project')
    return io.child(project,p)

def report_zip(directory,destination):
    directory=Path(directory);destination=Path(destination)
    files=sorted(p for p in directory.iterdir() if p.is_file() and p.name!='REPORT_MANIFEST.json')
    io.js(directory/'REPORT_MANIFEST.json',[dict(path=p.name,bytes=p.stat().st_size,sha256=io.sha(p)) for p in files])
    zip_files(directory,destination,[p.relative_to(directory).as_posix() for p in files]+['REPORT_MANIFEST.json'])

def zip_files(root,destination,names):
    destination=Path(destination);tmp=destination.with_name(destination.name+'.partial')
    with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
        for n in names:z.write(io.child(root,n),n)
    os.replace(tmp,destination)
    side=destination.with_name(destination.name+'.sha256');side.write_text(io.sha(destination)+'  '+destination.name+'\n')
    return side

def require_disk(path,gib):
    free=shutil.disk_usage(path).free
    if free<gib*1024**3:raise RuntimeError(f'Need {gib:.1f} GiB free at {path}; available {free/1024**3:.1f} GiB')
