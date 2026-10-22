#!/usr/bin/env python3
"""Run the new within-chooser analyses and verify/reuse completed work."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

for _thread_env in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS',
                    'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_thread_env]='1'
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
from threadpoolctl import threadpool_limits
from vendor import wave1_common as auth
import fe_suite as fe
import parallel_fe as parallel

ROOT=Path(__file__).resolve().parent
VERSION='1.0.2'
EXPECTED={'rows':41534331,'kind_draws':570091,'choosers':3224173}
RAW_BINS=['clearly_worse','modestly_worse_excluded','roughly_equal','disconnected_better','disconnected_clearly_better']
BIN_COUNTS=[22664818,3662090,9244704,2919470,3043249]
BIN_DRAWS=[106556,44072,240825,69801,108837]
SNAPSHOT='derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
SNAPSHOT_SHA='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
SNAPSHOT_EXPECTED={'returned':1305683,'patrons':4896,'missing_patron':0}
RATING_SHA='c0206294795930fea55b24600dcd3a518a47bc7defb2ef7c025df7b96f3251c9'
IV_SHA='b190961480a0eab1e232e81edf509142c5adcb49adafdc8bfc57681ad2b87df1'


def qs(x):return "'"+str(x).replace("'","''")+"'"
def rows(db,sql):
    r=db.execute(sql);keys=[x[0] for x in r.description]
    return [dict(zip(keys,v)) for v in r.fetchall()]


def verify_package():
    for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
        digest,name=line.split('  ',1);p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or not p.is_file() or auth.sha256_file(p)!=digest:
            raise ValueError(f'Package checksum failed: {name}')


def extract_checked(zpath,dest,expected=None):
    if expected and auth.sha256_file(zpath)!=expected:raise ValueError(f'Archive checksum failed: {zpath.name}')
    with zipfile.ZipFile(zpath) as z:
        if z.testzip():raise ValueError('Archive CRC failed')
        for name in z.namelist():
            target=(dest/name).resolve()
            if not target.is_relative_to(dest.resolve()):raise ValueError('Unsafe ZIP path')
        z.extractall(dest)


def verify_text_manifest(root,path):
    count=0
    for line in path.read_text().splitlines():
        if not line.strip():continue
        digest,name=line.split(None,1);name=name.strip().lstrip('*')
        p=(root/name).resolve()
        if not p.is_relative_to(root.resolve()) or auth.sha256_file(p)!=digest:
            raise ValueError(f'Existing-result manifest failed: {name}')
        count+=1
    return count


def reuse_results(public):
    """No new empirical estimates; keep original sample/covariance conventions."""
    directory=public/'completed_analyses';directory.mkdir()
    rating=directory/'rating';rating.mkdir()
    extract_checked(ROOT/'completed/rating_results.zip',rating,RATING_SHA)
    r=next(p for p in rating.iterdir() if p.is_dir())
    n=verify_text_manifest(r,r/'OUTPUT_MANIFEST.sha256')
    lineage=json.loads((r/'SAMPLE_LINEAGE.json').read_text())
    authority=json.loads((ROOT/'authority/SAMPLE_AUTHORITY.json').read_text())
    if lineage['fingerprint']!=authority['sample_fingerprint']:raise ValueError('Rating results belong to another main sample')
    original=directory/'iv_original';original.mkdir()
    extract_checked(ROOT/'completed/iv_original.zip',original,IV_SHA)
    insertion=directory/'iv_completion';insertion.mkdir()
    extract_checked(ROOT/'completed/iv_completion.zip',insertion)
    provenance=json.loads((insertion/'SOURCE_PROVENANCE.json').read_text())
    if provenance['source_archive_sha256']!=IV_SHA:raise ValueError('IV completion lineage mismatch')
    original_files={p.name:p for p in original.rglob('*') if p.is_file()}
    for name,digest in provenance['source_files'].items():
        if name not in original_files or auth.sha256_file(original_files[name])!=digest:
            raise ValueError(f'Original IV table mismatch: {name}')
        if auth.sha256_file(insertion/'stored_results'/name)!=digest:
            raise ValueError(f'IV insertion table mismatch: {name}')
    with (insertion/'stored_results/estimates.csv').open() as f:
        estimates=list(csv.DictReader(f))
    select=[r for r in estimates if r.get('specification') in
            ('main90_pooled','main90_repeat_pooled','main90_repeat_FE_diagnostic')]
    # Handle the stored schema explicitly; do not infer labels from effects.
    if not select:
        keys=list(estimates[0])
        spec_key=next((k for k in keys if any(r.get(k)=='main90_repeat_FE_diagnostic' for r in estimates)),None)
        if spec_key is None:raise ValueError('Stored repeated-recipient FE results absent')
        select=[r for r in estimates if r.get(spec_key) in ('main90_pooled','main90_repeat_pooled','main90_repeat_FE_diagnostic')]
    fe.csv_write(directory/'receipt_primary_and_repeat_comparisons.csv',select)
    ledger=[dict(analysis='relative_strength_and_payoff',action='VERIFIED_EXISTING_RESULTS',
             source_sha256=RATING_SHA,manifest_entries=n,
             note='Current competitive sample; chooser-by-board-state FE. No new fitting.'),
        dict(analysis='receipt_recipient_FE',action='VERIFIED_EXISTING_RESULTS',source_sha256=IV_SHA,
             manifest_entries=len(provenance['source_files']),
             note='Original repeated-exposure IV frame and original shared-account-or-date covariance preserved. No new fitting.')]
    fe.json_write(directory/'REUSE_LEDGER.json',ledger)
    return ledger


def load_patron(db,project,public):
    path=project/SNAPSHOT
    if not path.is_file():
        db.execute('CREATE TEMP TABLE patrons(username VARCHAR,patron TINYINT)')
        return {'status':'BLOCKED_MISSING_CERTIFIED_PROFILE','path':str(path)}
    if auth.sha256_file(path)!=SNAPSHOT_SHA:
        db.execute('CREATE TEMP TABLE patrons(username VARCHAR,patron TINYINT)')
        return {'status':'BLOCKED_PROFILE_HASH_MISMATCH','path':str(path)}
    db.execute(f'CREATE VIEW profile_snapshot AS SELECT * FROM read_parquet({qs(path)})')
    cols={r[0] for r in db.execute('DESCRIBE profile_snapshot').fetchall()}
    needed={'username_norm','returned','patron','queried_at_utc'}
    if not needed<=cols:raise ValueError('Certified profile schema changed')
    quality=rows(db,"""SELECT count(*) AS rows,
      count(*) FILTER(WHERE returned IS TRUE) returned,
      count(*) FILTER(WHERE returned IS TRUE AND patron IS TRUE) patrons,
      count(*) FILTER(WHERE returned IS TRUE AND patron IS NULL) missing_patron,
      min(queried_at_utc)::VARCHAR first_query,max(queried_at_utc)::VARCHAR last_query
      FROM profile_snapshot""")[0]
    if any(quality[k]!=v for k,v in SNAPSHOT_EXPECTED.items()):
        raise ValueError(f'August profile counts/Patron coding failed: {quality}')
    db.execute("""CREATE TEMP TABLE patrons AS SELECT lower(trim(username_norm)) AS username,
      patron::TINYINT AS patron FROM profile_snapshot WHERE returned IS TRUE""")
    if db.execute("SELECT count(*) FROM (SELECT username FROM patrons GROUP BY username HAVING count(*)>1 OR username IS NULL OR username='')").fetchone()[0]:
        raise ValueError('Profile identifiers missing or duplicated')
    result={'status':'READY_SELECTED_PROFILE_SAMPLE','sha256':SNAPSHOT_SHA,'path':str(path),**quality,
      'inclusion_weights_available':False,'population_claim':False,
      'meaning':'Selected August returned-profile sample. No extrapolation to all accounts. No gap-fill snapshots mixed in.'}
    fe.json_write(public/'PATRON_SOURCE.json',result)
    return result


def prepare(db,paths,private,public):
    source='read_parquet(['+','.join(qs(p) for p in paths)+'],hive_partitioning=false)'
    db.execute(f'CREATE VIEW panel AS SELECT * FROM {source}')
    raw=rows(db,'SELECT count(*) AS rows,sum(outcome_kind_draw::INT) kind_draws,count(DISTINCT chooser_user_id) choosers FROM panel')[0]
    if raw!=EXPECTED:raise ValueError(f'Main-panel headline counts changed: {raw}')
    bins=rows(db,'SELECT engine_fairness_bin board,count(*) AS rows,sum(outcome_kind_draw::INT) grants FROM panel GROUP BY 1')
    if {r['board']:r['rows'] for r in bins}!=dict(zip(RAW_BINS,BIN_COUNTS)) or {r['board']:r['grants'] for r in bins}!=dict(zip(RAW_BINS,BIN_DRAWS)):
        raise ValueError('Frozen state counts do not reproduce')
    fe.csv_write(public/'raw_state_counts.csv',bins)
    state='CASE engine_fairness_bin '+' '.join(f'WHEN {qs(s)} THEN {i}' for i,s in enumerate(RAW_BINS))+' END'
    ply='CASE WHEN ply_count<=4 THEN 0 WHEN ply_count<=6 THEN 1 WHEN ply_count<=8 THEN 2 WHEN ply_count<=10 THEN 3 WHEN ply_count<=20 THEN 4 WHEN ply_count<=40 THEN 5 WHEN ply_count<=80 THEN 6 ELSE 7 END'
    needs=['chooser_elo','disconnected_elo','chooser_win_premium_v2','chooser_pre_rd_v2','disconnected_pre_rd_v2','chooser_pre_sigma_v2','disconnected_pre_sigma_v2']
    valid=' AND '.join(f'{c} IS NOT NULL AND isfinite({c})' for c in needs)
    db.execute(f"""CREATE VIEW tagged AS SELECT *,{state} AS b,{ply} AS p,
      (chooser_user_id IS NOT NULL AND outcome_kind_draw IS NOT NULL
       AND engine_fairness_bin IN({','.join(qs(x) for x in RAW_BINS)})
       AND engine_eval_cp_disconnected IS NOT NULL AND isfinite(engine_eval_cp_disconnected)
       AND ply_count IS NOT NULL AND ply_count>=0 AND ply_count=floor(ply_count)) core_ok,
      (month IS NOT NULL AND length(month)=7 AND api_speed IS NOT NULL AND length(trim(api_speed))>0) time_ok,
      ({valid} AND chooser_win_premium_v2>0 AND chooser_pre_rd_v2>0 AND disconnected_pre_rd_v2>0
       AND chooser_pre_sigma_v2>0 AND disconnected_pre_sigma_v2>0) controls_ok,
      (chooser_clock_last_obs_s IS NULL OR NOT isfinite(chooser_clock_last_obs_s)) cm,
      (disconnected_clock_last_obs_s IS NULL OR NOT isfinite(disconnected_clock_last_obs_s)) dm
      FROM panel""")
    mismatch=db.execute("""SELECT count(*) FROM tagged WHERE core_ok AND b != CASE
      WHEN engine_eval_cp_disconnected<=-300 THEN 0 WHEN engine_eval_cp_disconnected< -100 THEN 1
      WHEN engine_eval_cp_disconnected<=100 THEN 2 WHEN engine_eval_cp_disconnected<300 THEN 3 ELSE 4 END""").fetchone()[0]
    if mismatch:raise ValueError('Stored state bins disagree with frozen evaluation boundaries')
    flow=rows(db,"""SELECT CASE WHEN NOT coalesce(core_ok,false) THEN 'invalid_core'
      WHEN NOT coalesce(time_ok,false) THEN 'invalid_calendar'
      WHEN NOT coalesce(controls_ok,false) THEN 'invalid_economic_controls'
      ELSE 'included_common_sample' END reason,count(*) AS rows,sum(outcome_kind_draw::INT) grants
      FROM tagged GROUP BY 1 ORDER BY 1""")
    fe.csv_write(public/'sample_flow.csv',flow)
    db.execute('CREATE VIEW eligible AS SELECT * FROM tagged WHERE core_ok AND time_ok AND controls_ok')
    n=db.execute('SELECT count(*) FROM eligible').fetchone()[0]
    if not n:raise ValueError('Empty common support')
    calendar=[list(r) for r in db.execute('SELECT DISTINCT month,api_speed FROM eligible ORDER BY 1,2').fetchall()]
    speeds=[r[0] for r in db.execute('SELECT DISTINCT api_speed FROM eligible ORDER BY 1').fetchall()]
    cal='CASE '+' '.join(f'WHEN month={qs(m)} AND api_speed={qs(s)} THEN {i}' for i,(m,s) in enumerate(calendar))+' END'
    speed='CASE api_speed '+' '.join(f'WHEN {qs(s)} THEN {i}' for i,s in enumerate(speeds))+' END'
    stages=rows(db,'SELECT b board,p ply,count(*) AS rows,sum(outcome_kind_draw::INT) grants FROM eligible GROUP BY 1,2 ORDER BY 1,2')
    fe.csv_write(public/'common_sample_state_stage_counts.csv',stages)
    state_n=np.zeros(5);stage_n=np.zeros(8)
    for row in stages:state_n[row['board']]+=row['rows'];stage_n[row['ply']]+=row['rows']
    if any(state_n==0) or any(stage_n==0):raise ValueError('Missing core state/stage support')
    ep=rows(db,'SELECT p,ply_count FROM eligible WHERE ply_count<=20 GROUP BY 1,2 ORDER BY 1,2')
    baseline={}
    for r in ep:baseline.setdefault(r['p'],int(r['ply_count']))
    early=[int(r['ply_count']) for r in ep if r['ply_count']!=baseline[r['p']]]
    db.execute(f"""CREATE VIEW joined AS SELECT e.*,coalesce(t.patron,-1)::TINYINT patron_status
      FROM eligible e LEFT JOIN patrons t ON lower(trim(e.chooser_username_norm))=t.username""")
    # The selector is an account marker, not a row-level changing treatment.
    bad=db.execute('SELECT count(*) FROM (SELECT chooser_user_id FROM joined GROUP BY 1 HAVING min(patron_status)!=max(patron_status))').fetchone()[0]
    if bad:raise ValueError('Profile join changes Patron classification within an account')
    coverage=rows(db,'SELECT patron_status,count(*) AS rows,count(DISTINCT chooser_user_id) choosers,sum(outcome_kind_draw::INT) grants FROM joined GROUP BY 1 ORDER BY 1')
    fe.csv_write(public/'patron_coverage.csv',coverage)
    fe.csv_write(public/'patron_state_stage_counts.csv',rows(db,
      'SELECT patron_status,b board,p ply,count(*) AS rows,count(DISTINCT chooser_user_id) choosers,'
      'sum(outcome_kind_draw::INT) grants FROM joined GROUP BY 1,2,3 ORDER BY 1,2,3'))
    clock=rows(db,"""SELECT sum(cm::INT) chooser_missing,sum(dm::INT) disconnected_missing,
      count(*) FILTER(WHERE NOT cm AND chooser_clock_last_obs_s<0) chooser_negative_clamped,
      count(*) FILTER(WHERE NOT dm AND disconnected_clock_last_obs_s<0) disconnected_negative_clamped FROM eligible""")
    fe.csv_write(public/'clock_handling.csv',clock)
    cache=private/'common_model_PRIVATE.parquet'
    fe.log(f'Sorting narrow private cache: {n:,} rows')
    db.execute(f"""COPY (SELECT chooser_user_id::BIGINT chooser,outcome_kind_draw::DOUBLE y,
      b::TINYINT board,p::TINYINT ply,ply_count::INTEGER exact_ply,
      ({cal})::SMALLINT calendar,({speed})::TINYINT speed,
      CASE WHEN cm THEN 0 ELSE ln(1+greatest(chooser_clock_last_obs_s,0)) END::DOUBLE log_cclock,
      CASE WHEN dm THEN 0 ELSE ln(1+greatest(disconnected_clock_last_obs_s,0)) END::DOUBLE log_dclock,
      cm::DOUBLE cclock_missing,dm::DOUBLE dclock_missing,
      (disconnected_elo-chooser_elo)::DOUBLE gap,chooser_win_premium_v2::DOUBLE premium,
      chooser_pre_rd_v2::DOUBLE crd,disconnected_pre_rd_v2::DOUBLE drd,
      chooser_pre_sigma_v2::DOUBLE cvol,disconnected_pre_sigma_v2::DOUBLE dvol,
      chooser_elo::DOUBLE rating,patron_status::TINYINT patron
      FROM joined ORDER BY chooser_user_id) TO {qs(cache)}
      (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 131072)""")
    meta={'rows':n,'calendar':calendar,'speeds':speeds,'early_levels':early,'early_omitted_ply_by_band':baseline,
          'competitive_weights':(state_n[2:]/state_n[2:].sum()).tolist(),
          'stage_weights':(stage_n/stage_n.sum()).tolist(),'common_support_exclusions':flow,
          'cache_sha256':auth.sha256_file(cache),'patron_coverage':coverage}
    fe.json_write(public/'MODEL_DESIGN.json',meta)
    return cache,meta


def run(args):
    started=time.monotonic();timing=[]
    workers=min(args.workers,os.cpu_count() or 1)
    verify_package()
    project=args.project_root.expanduser().resolve()
    if not project.is_dir():raise FileNotFoundError(f'Mount the project drive first: {project}')
    sample=(args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE').resolve()
    fe.log(f'Planning runtime at 8–10 workers: 5–10 minutes on a recent MacBook Pro with SSD; allow 15 minutes with heavy disk spill. This run uses {workers} workers. This is an estimate, not a measured full-suite time.')
    fe.log('Verifying the certified 41.5 million panel; no API calls')
    certified=auth.authenticate_sample(sample,verify_hashes=True,hash_workers=min(workers,2))
    timing.append({'phase':'source_authentication','seconds':time.monotonic()-started})
    paths=[r['path'] for r in certified['month_records']]
    before={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in paths}
    base=project/'derived/replication/within_chooser_suite_v102_PRIVATE';base.mkdir(parents=True,exist_ok=True)
    tag=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+str(os.getpid())
    private=Path(tempfile.mkdtemp(prefix=tag+'_',dir=base))
    public=private/('POOL_WITHIN_CHOOSER_SUITE_RESULTS_v102_'+tag);public.mkdir()
    fe.log(f'Private work directory: {private}')
    status=[];failures=[]
    fe.json_write(public/'SAMPLE_LINEAGE.json',auth.compact_sample_lineage(certified))
    fe.json_write(public/'ENVIRONMENT.json',{'python':sys.version,'platform':platform.platform(),
      'numpy':np.__version__,'pyarrow':pa.__version__,'duckdb':duckdb.__version__,'scipy':scipy.__version__,
      'workers':workers,'requested_workers':args.workers,'blas_threads_per_worker':1,
      'duckdb_threads':workers,'hash_workers':min(workers,2),'duckdb_memory':args.memory_limit})
    try:
        t0=time.monotonic()
        status.extend(reuse_results(public))
        db=duckdb.connect(str(private/'working.duckdb'))
        db.execute(f'SET threads={workers}');db.execute(f'SET memory_limit={qs(args.memory_limit)}')
        db.execute(f'SET temp_directory={qs(private/"spill")}');db.execute('SET preserve_insertion_order=true')
        try:
            profile=load_patron(db,project,public)
        except Exception as exc:
            db.execute('DROP TABLE IF EXISTS patrons')
            db.execute('CREATE TEMP TABLE patrons(username VARCHAR,patron TINYINT)')
            profile={'status':'BLOCKED_PROFILE_VALIDATION_FAILED','error':str(exc)}
        if profile['status'].startswith('READY'):
            p=Path(profile['path']);before[str(p)]=(p.stat().st_size,p.stat().st_mtime_ns)
        fe.json_write(public/'PATRON_SOURCE.json',profile)
        cache,meta=prepare(db,paths,private,public);db.close()
        timing.append({'phase':'profile_checks_and_common_cache','seconds':time.monotonic()-t0})
        paths_for_workers,shard_receipt=parallel.shards(cache,private/'shards',workers)
        fe.json_write(public/'PARQUET_PARTITIONS.json',shard_receipt)
        timing.append({'phase':'chooser_partitioning','seconds':shard_receipt['seconds']})
        with parallel.pool(workers) as executor:
            for group in ['states','weighting','speed_fe','patron']:
                if group=='patron' and not profile['status'].startswith('READY'):
                    status.append({'analysis':'patron','action':profile['status']});failures.append('patron')
                    continue
                try:
                    t0=time.monotonic();fe.log(f'Fitting {group} with {workers} processes, 1 numerical thread each')
                    fitted=parallel.fit_group(paths_for_workers,meta,public/group,group,executor,args.batch_size)
                    receipts=fe.export(fitted,meta,public/group)
                    timing.append({'phase':group,'seconds':time.monotonic()-t0})
                    status.append({'analysis':group,'action':'NEW_ESTIMATES_COMPLETE','models':[r['model'] for r in receipts]})
                except Exception as exc:
                    fe.json_write(public/(group+'_FAILED.json'),{'error':str(exc),'traceback':traceback.format_exc()})
                    fe.log(f'{group} failed: {exc}. Remaining independent modules will continue.')
                    failures.append(group);status.append({'analysis':group,'action':'FAILED','reason':str(exc)})
        if any((Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=v for p,v in before.items()):
            raise ValueError('A source file changed during execution')
        source=public/'executed_package';source.mkdir()
        for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
            _,name=line.split('  ',1);dest=source/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,dest)
        shutil.copy2(ROOT/'SHA256SUMS.txt',source/'SHA256SUMS.txt')
        outcome='COMPLETE' if not failures else 'PARTIAL_REQUIRES_REVIEW'
        fe.csv_write(public/'runtime.csv',timing)
        fe.json_write(public/'RUNTIME_RECEIPT.json',{'seconds_before_archiving':time.monotonic()-started,
          'workers':workers,'blas_threads_per_worker':1,'phase_seconds':timing})
        fe.json_write(public/'RUN_LEDGER.json',{'status':outcome,'modules':status,'failed_or_blocked':failures})
        fe.json_write(public/'_SUCCESS.json' if not failures else public/'_PARTIAL.json',{
            'status':outcome,'new_main_rows':meta['rows'],'source_fingerprint':certified['fingerprint'],
            'source_stats_unchanged':True,'full_source_hashes_verified_at_start':True,
            'network_requests':0,'private_rows_in_archive':False})
        (public/'READ_FIRST.md').write_text('# Within-chooser suite\n\nStatus: '+outcome+'\n\n'
          'New estimates: states, weighting, speed_fe, and selected-August-profile Patron interactions.\n'
          'Completed rating and recipient-FE results are verified copies, not newly estimated.\n'
          'Read RUN_LEDGER.json before interpreting any table. Missing/unidentified contrasts are not zero.\n'
          'Primary quantities are in each module\'s contrasts.parquet (and CSV copy); SEs are clustered by chooser.\n'
          'Weights and standardization are recorded in MODEL_DESIGN.json and the supplied METHODS.md.\n')
        auth.write_manifest_tsv(public)
        transfer=args.transfer_root.expanduser().resolve();transfer.mkdir(parents=True,exist_ok=True)
        archive=transfer/(public.name+'.zip')
        if archive.exists():raise FileExistsError(archive)
        auth.zip_tree(public,archive)
        archive.with_suffix('.zip.sha256').write_text(auth.sha256_file(archive)+'  '+archive.name+'\n')
        fe.log(f'{outcome} in {(time.monotonic()-started)/60:.1f} minutes. Upload:\n{archive}\n{archive}.sha256')
        return 0 if not failures else 2
    except Exception as exc:
        fe.json_write(private/'FAILED.json',{'error':str(exc),'traceback':traceback.format_exc()})
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers','--threads',dest='workers',type=int,default=10)
    p.add_argument('--memory-limit',default='6GB')
    p.add_argument('--batch-size',type=int,default=32768)
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.batch_size<16:p.error('workers 1..10; batch size >=16')
    if a.self_test:
        from test_suite import run_tests
        with threadpool_limits(limits=2):run_tests()
    else:sys.exit(run(a))


if __name__=='__main__':main()
