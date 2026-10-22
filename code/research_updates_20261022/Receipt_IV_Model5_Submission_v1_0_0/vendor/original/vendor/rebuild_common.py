"""All-time-five comparison migration; isolated outputs and frozen producers."""
from pathlib import Path
import sys, os, json, time, shutil, gc
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor_primary'))
from primary_common import *
import primary_inputs as primary
import cutoffs
import r9_models as fits
import r9_common as r9
import cached_inputs, phase_inputs, performance_cache as cache
import performance_histories as fast, performance_chronology as chron
import performance_runtime, cache_auth
from types import SimpleNamespace
import concurrent.futures as cf
import multiprocessing as mp
VERSION='1.0.3'
ENTRY=['active_timeout','recipient_disconnect_main','recipient_fair_arm_main','selected_entry_90','analysis_entry_90']
COUNTS=[f'{v}_{d}' for d in (30,90) for v in ('fair','kind','disconnect','receipt','claim')]
OUTCOMES=['y','reached','outcome_gid','outcome_t','outcome_start','outcome_opponent']
IDENTITY=['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms']
RULE=dict(version=VERSION,support=DEFINITION['support'],receipt_spacing=DEFINITION['spacing'],
 comparison_frame='Original Phase 100 additional-game hash frame: one-in-32 selection excluding the older one-in-1024 pilot; deterministic focal orientation retained',
 comparison_risk='Only selected receipt anchors strictly earlier than candidate start close the 90-day risk window; start must be strictly greater than previous anchor + 90 days',
 entry='All-time-five, first observed pair, observed nonadjacent predecessor, real-time pool, 97-day history, start + 90 days < panel end',
 ordinary='Entry frame restricted to mate/resign/stalemate, additionally anchor + 90 days < panel end',
 entry_labels='Rebuilt receipt selection before and after observation-window cuts; original certified main-panel role labels',
 controls='X0_ENV_indicator primary; X0 beside it; Score A and its own three donor-history controls',
 covariance=DEFINITION['covariance'],score_scale=SD,
 metadata='Reuse authenticated returned metadata; request only missing/invalid potentially eligible games; retain exactly the existing three-record quarantine; block on any additional unresolved metadata',
 no_new_engine_work=True,private_rows_exported=False)

def stage(root,conf,build,deps=()):
    return frozen.r.stable_stage(Path(root),conf,build,list(deps))

def connection(root,memory=8):return db(Path(root)/'spill',memory)

def check_stage(path,conf):return frozen.r9_inputs.stage_file(Path(path),conf)

def mapped(fn,jobs,workers,label):
    if not jobs:return []
    results=[];started=time.monotonic()
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending={pool.submit(fn,j):j for j in jobs}
        with heartbeat(label):
            for f in cf.as_completed(pending):
                results.append(f.result());done=len(results);elapsed=time.monotonic()-started
                log(f'{label}: {done}/{len(jobs)} complete; elapsed {elapsed/60:.1f} min; remaining task ETA {elapsed/done*(len(jobs)-done)/60:.1f} min')
    return results

def ensure(c,query,label):require(c.execute(query).fetchone()[0]==0,label)

def candidate_root(run,b):return Path(b.get('candidate_run',run))

def prepare(a,run,conf):
    b=primary.bind(a,run,conf)
    save(run/'PRIVATE/PRIMARY_BOUND.json',b)
    expected=load(PACKAGE/'evidence/comparison100_summary.json')
    oldconf=expected['configuration_sha256'];fc=expected['comparison_frame']['configuration_sha256']
    old=a.project/'derived/replication/run2_phase100_score_a_v100_PRIVATE'/oldconf[:12]
    fr=a.project/'derived/replication/run2_phase100_frames_v100_PRIVATE'/fc[:12]
    require(frozen.r.io.cfgsha(load(old/'config.json'))==oldconf,'Old comparison configuration changed')
    require(frozen.r.io.cfgsha(load(fr/'config.json'))==fc,'Old frame configuration changed')
    for rec in load(PACKAGE/'evidence/comparison100_REPORT_MANIFEST.json'):
        frozen.r.io.checked(old/'report'/rec['path'],rec['sha256'],rec['bytes'])
    oldpaths=load(old/'PREPARED_INPUTS_PRIVATE.json')
    for name in ('F','O'):oldpaths[name]=str(check_stage(oldpaths[name],oldconf))
    oldscores={'F':str(check_stage(old/'scores_combined/F.parquet',oldconf)),
               'O':str(check_stage(old/'ordinary_scores/scores.parquet',oldconf))}
    for sample in ('F100','O100'):
        for level in r9.LEVELS:
            folder=old/'fits'/(sample+'__A__'+level)
            for name in ('result.json','influence_PRIVATE.parquet','dependencies_PRIVATE.json'):check_stage(folder/name,oldconf)
            for dep in load(folder/'dependencies_PRIVATE.json'):frozen.r.io.checked(dep['path'],dep['sha256'])
    source=phase_inputs.research_inputs(a.project,min(a.workers,4))
    require({(p['month'],p['shard'],p['sha256']) for p in source['parts']}==
            {(p['month'],p['shard'],p['sha256']) for p in b['bound']['parts']},'Comparison and receipt donor histories differ')
    require(sorted(source['author_ids'].values())==sorted(b['bound']['binding']['author_ids']),'Author ID mismatch')
    local=cache_auth.authenticate(SimpleNamespace(project_root=a.project,desktop=a.result_dir,plan=a.local_plan,workers=min(a.workers,4)))
    phase_metadata=load(fr/'config.json')['phase']['metadata']
    for path in (local['metadata'],phase_metadata):
        receipt=load(Path(path).parent/'_DONE.json')
        check_stage(path,receipt['config_sha256'])
    check_stage(fr/'chronology/features.parquet',fc)
    check_stage(fr/'support/chron_queries.parquet',fc)
    quarantine=[]
    for m in cache_auth.ex.MONTHS:
        p=check_stage(fr/'coverage'/m/'unresolved_PRIVATE.parquet',fc)
        quarantine.append(str(p))
    rates=check_stage(old/'environment/combined_rates/rates.parquet',oldconf)
    b['known_rates'].append(str(rates))
    save(run/'PRIVATE/PRIMARY_BOUND.json',b)
    binding=dict(primary=b,source=source,local=local,frame_root=str(fr),frame_conf=fc,
      comparison_root=str(old),comparison_conf=oldconf,old_paths=oldpaths,old_scores=oldscores,
      metadata=[local['metadata'],phase_metadata],quarantine=quarantine)
    from repair_reuse import authenticate_parent
    authenticate_parent(a,run,binding)
    from repair_completed import authenticate_chronology
    authenticate_chronology(a,run,binding)
    save(run/'PRIVATE/BINDING.json',binding)
    save(run/'report/rebuild_definition.json',RULE)
    save(run/'report/input_authentication.json',dict(receipt_rows=EXPECTED_N,old_entry_rows=14742651,
      old_ordinary_rows=9528012,fixed_frame_rows=cache_auth.FRAME_ROWS,reference_sha256=sha(b['bound']['reference']),
      old_comparison_configuration=oldconf,old_frame_configuration=fc,old_files_read_only=True))
    return binding

def bind(run):return load(run/'PRIVATE/BINDING.json')
