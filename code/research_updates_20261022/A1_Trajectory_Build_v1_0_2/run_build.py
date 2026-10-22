#!/usr/bin/env python3
"""Recover fixed A1 trajectories, evaluate earlier positions, and report balance."""
from __future__ import annotations
import argparse,collections,concurrent.futures as cf,csv,datetime as dt,fcntl,gc,gzip,json,multiprocessing as mp
import os,platform,shutil,sys,time,traceback,zipfile
from pathlib import Path
import pyarrow as pa
import pyarrow.compute as pc
import local_io as io
import fetch_moves as fetch
import recover_logic as logic
import engine_jobs as engines
import compact_plan

PACKAGE=Path(__file__).resolve().parent
PREP_REL='derived/replication/a1_session_trajectory_prepare_v100_PRIVATE'
OUT_REL='derived/replication/a1_trajectory_build_v100_PRIVATE'
VIEW_REL='derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1/project_view'
VERSION='1.0.2'

def authenticate(project):
    authority=io.load(PACKAGE/'evidence/SUMMARY.json');conf=authority['config_sha256']
    prep=project/PREP_REL/conf[:16]
    if io.cfgsha(io.load(prep/'RUN_CONFIG.json'))!=conf:raise RuntimeError('Preparation configuration changed')
    success=io.load(prep/'_SUCCESS.json')
    if success.get('status')!='A1_PREPARATION_COMPLETE' or success.get('config_sha256')!=conf or success.get('lineage')!=authority['lineage']:
        raise RuntimeError('Preparation completion belongs to another sample')
    view=project/VIEW_REL;lineage=authority['lineage']
    current={'core_success_sha256':view/'output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/_SUCCESS.json',
        'core_summary_sha256':view/'output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/summary.json',
        'a1_private_sha256':view/'derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet',
        'a1_producer_sha256':view/'replication_package/code/10c_estimate_dynamic_prosociality_core.py'}
    for key,path in current.items():io.checked(path,lineage[key])
    expected=io.load(PACKAGE/'evidence/trajectory_targets_summary.json')
    if io.load(prep/'targets/target_summary.json')!=expected:raise RuntimeError('Frozen target totals changed')
    meta=io.load(PACKAGE/'evidence/main_sample_report.json')
    monthly={r['month']:r for r in expected['monthly']};paths=[];records=[]
    for item in meta['panel_outputs']:
        month=item['month'];root=prep/'targets'/('month_'+month)
        done=io.complete(root,io.cfgsha([conf,item]))
        if done is None:raise RuntimeError('Missing completed target month '+month)
        saved=io.load(root/'target_summary.json')
        if saved!={k:v for k,v in monthly[month].items() if k!='month'}:raise RuntimeError('Target month counts changed')
        path=root/'targets_PRIVATE.parquet';paths.append(path)
        records.append({'month':month,'sha256':io.sha(path),'rows':saved['rows']})
    return prep,paths,records,expected,authority

def build_plan(out,paths,expected):
    """Snapshot targets once. No downstream outcomes are used to select rows."""
    io.log(f'Preparing download plan: checking {expected["target_rows"]:,} targets; monthly snapshots, 300 games per request.')
    c=io.conn(out/'spill',4,2)
    try:
        q=c.execute('SELECT count(*),count(DISTINCT cohort_row_id),count(DISTINCT exposure_game_id),'
            'sum(len(board_plies)),count(*) FILTER(WHERE NOT complete_followup OR a1_att_weight<=0 OR a1_att_weight IS NULL) '
            'FROM '+io.parq(paths)).fetchone()
        n=expected['target_rows']
        if q!=(n,n,n,expected['requested_board_positions'],0):raise RuntimeError('Target uniqueness, count, or support changed')
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    units=[];i=0;rows=0;snapshots=0
    for source_index,source in enumerate(paths):
        table=io.read(source)
        table=table.take(pc.sort_indices(table,sort_keys=[('pilot_hash','ascending'),('exposure_game_id','ascending')]))
        if not table.num_rows:continue
        meta=compact_plan.write_month(out/f'month_{source_index:02d}.parquet',table)
        snapshots+=1
        for begin in range(0,table.num_rows,300):
            part=table.slice(begin,300);name=f'unit_{i:05d}'
            units.append({**meta,'unit':name,'row_group':begin//300,
                          'rows':part.num_rows,'sha256':compact_plan.batch_sha(part)})
            i+=1
        rows+=table.num_rows
        io.log(f'Plan: {rows:,}/{n:,} games; {snapshots} monthly files; {i:,} API batches indexed.')
    io.js(out/'units.json',units);return {'rows':n,'units':len(units)}

def replay_unit(root,unit,plan,run_conf,client,reader=None):
    unit_conf=io.cfgsha([run_conf,unit]);destination=root/'replay'/unit['unit']
    old=io.complete(destination,unit_conf)
    if old:return destination,io.load(destination/'summary.json')
    if reader is None:
        with compact_plan.Reader(plan) as own_reader:
            return replay_unit(root,unit,plan,run_conf,client,own_reader)
    targets=reader.read(unit).to_pylist()
    payload_key=io.cfgsha([fetch.URL,[t['exposure_game_id'] for t in targets]])
    records=fetch.recover_unit(root.parent/'api_payloads'/payload_key,targets,payload_key,client)
    def replay(out):
        games,positions=logic.replay_records(targets,records)
        io.table(out/'games_PRIVATE.parquet',games);io.table(out/'positions_PRIVATE.parquet',positions)
        stats={'rows':len(targets),'returned':len(records),'verified':sum(x=='VERIFIED' for x in games['status'].to_pylist()),
            'positions':positions.num_rows,'statuses':dict(collections.Counter(games['status'].to_pylist())),
            'clock_statuses':dict(collections.Counter(x for x in games['clock_status'].to_pylist() if x is not None))}
        io.js(out/'summary.json',stats);return stats
    dest,_=io.stage(destination,unit_conf,replay)
    return dest,io.load(dest/'summary.json')

def recover_all(root,plan,units,conf,client):
    started=time.monotonic();rows=0;new_requests=client.requests;paths=[];totals=collections.Counter();statuses=collections.Counter();clocks=collections.Counter()
    with compact_plan.Reader(plan) as reader:
        for i,unit in enumerate(units,1):
            path,s=replay_unit(root,unit,plan,conf,client,reader);paths.append(path)
            rows+=s['rows'];totals.update({k:s[k] for k in ('rows','returned','verified','positions')});statuses.update(s['statuses']);clocks.update(s['clock_statuses'])
            if s['verified']==0 or s['verified']/s['rows']<.95:
                # A widespread mismatch could be a source/decoder problem; stop
                # before spending days on the remaining frame, with evidence saved.
                io.js(root/'RECOVERY_BLOCKED.json',{'unit':unit['unit'],'counts':s,'reason':'More than 5% of a batch failed replay; inspect saved evidence before continuing'})
                raise RuntimeError('Replay validation failed for more than 5% of a batch; saved status counts: '+json.dumps(s['statuses']))
            elapsed=time.monotonic()-started;speed=rows/elapsed if elapsed else 0
            eta=(len(units)-i)*elapsed/i/3600
            io.log(f'Recovery {i:,}/{len(units):,} batches; accounted {rows:,}; verified {totals["verified"]:,}; {speed:.2f} games/s; ETA {eta:.1f} h')
    summary={**dict(totals),'statuses':dict(statuses),'clock_statuses':dict(clocks),
        'seconds_this_invocation':time.monotonic()-started,'network_requests_this_invocation':client.requests-new_requests,
        'http_seconds_this_invocation':client.http_seconds,'cooldown_seconds_this_invocation':client.wait_seconds}
    io.js(root/'RECOVERY_COMPLETE.json',summary)
    return paths,summary

def evaluate_all(root,replays,conf,engine_path,engine_meta,workers):
    started=time.monotonic();jobs=[];paths=[];counts=collections.Counter();statuses=collections.Counter()
    for replay in replays:
        dest=root/'engine'/replay.name;stage_conf=io.cfgsha([conf,io.sha(replay/'_DONE.json'),engine_meta])
        paths.append(dest)
        old=io.complete(dest,stage_conf)
        if old:
            s=io.load(dest/'summary.json');counts.update({k:s[k] for k in ('games','positions','mate_positions','engine_searches_executed')});statuses.update(s['score_statuses'])
        else:jobs.append((str(replay),str(dest),stage_conf))
    initial=counts['positions'];todo=len(jobs)
    io.log(f'Stockfish: reusing {initial:,} positions; {todo:,} batches remain; {workers} workers, 100,000 nodes/position')
    if jobs:
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),
                initializer=engines.prepare_worker,initargs=(str(engine_path),)) as executor:
            pending={};it=iter(jobs);completed=0
            def fill():
                while len(pending)<2*workers:
                    job=next(it,None)
                    if job is None:break
                    pending[executor.submit(engines.evaluate_unit,job)]=job
            fill()
            with io.heartbeat('Stockfish trajectory evaluations'):
                while pending:
                    done,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
                    for future in done:
                        pending.pop(future);_,s=future.result();completed+=1
                        counts.update({k:s[k] for k in ('games','positions','mate_positions','engine_searches_executed')});statuses.update(s['score_statuses'])
                        elapsed=time.monotonic()-started;rate=(counts['positions']-initial)/elapsed
                        eta=(todo-completed)/completed*elapsed/3600
                        io.log(f'Stockfish {completed:,}/{todo:,} new batches; {counts["positions"]:,} positions; {rate:.2f}/s; ETA {eta:.1f} h')
                    fill()
    summary={**dict(counts),'score_statuses':dict(statuses),'seconds_this_invocation':time.monotonic()-started,
        'reused_positions':initial,'engine':engine_meta}
    io.js(root/'ENGINE_COMPLETE.json',summary);return paths,summary

BALANCE_FIELDS=['plies_since_last_capture','no_capture_observed','recipient_last_move_capture',
 'recipient_last_clock_api_units','chooser_last_clock_api_units','recipient_move_1_cp_loss','recipient_move_2_cp_loss',
 'trajectory_all_requested_nodes_reached']

def assemble(out,paths,expected_rows):
    c=io.conn(out/'spill',4,4)
    try:
        src=io.parq([p/'features_PRIVATE.parquet' for p in paths]);c.execute('CREATE VIEW f AS SELECT * FROM '+src)
        n=c.execute('SELECT count(*),count(DISTINCT cohort_row_id),count(DISTINCT exposure_game_id) FROM f').fetchone()
        if n!=(expected_rows,)*3:raise RuntimeError('Feature assembly lost or duplicated targets')
        io.copy(c,'SELECT * FROM f',out/'trajectory_features_PRIVATE.parquet')
        c.execute('CREATE OR REPLACE VIEW f AS SELECT * FROM '+io.parq([out/'trajectory_features_PRIVATE.parquet']))
        result=[]
        for scope,condition in [('complete_followup','true'),('primary_conditional_choice','primary_conditional_choice')]:
            for field in BALANCE_FIELDS:
                # CP comparisons report a strict budget-qualified version.
                # Raw scores, all node counts and mates remain in private files.
                score_cond=' AND trajectory_all_requested_nodes_reached' if '_cp_' in field else ''
                rows=c.execute(f'''SELECT received_mercy,count(*) AS rows,sum(a1_att_weight) AS weight,
                  count(*) FILTER(WHERE {field} IS NOT NULL {score_cond}) AS observed,
                  sum(a1_att_weight) FILTER(WHERE {field} IS NOT NULL {score_cond}) AS observed_weight,
                  sum(a1_att_weight*cast({field} AS DOUBLE)) FILTER(WHERE {field} IS NOT NULL {score_cond}) AS sx,
                  sum(a1_att_weight*pow(cast({field} AS DOUBLE),2)) FILTER(WHERE {field} IS NOT NULL {score_cond}) AS sx2
                  FROM f WHERE {condition} GROUP BY received_mercy ORDER BY received_mercy''').fetchall()
                stats={}
                for arm,count,w,obs,ow,sx,sx2 in rows:
                    mean=sx/ow if ow else None;variance=max(0,sx2/ow-mean**2) if ow else None
                    stats[bool(arm)]={'rows':count,'observed':obs,'missing':count-obs,'weight':w,
                        'observed_weight':ow or 0,'mean':mean,'variance':variance}
                a=stats.get(True,{});b=stats.get(False,{})
                gap=a.get('mean')-b.get('mean') if a.get('mean') is not None and b.get('mean') is not None else None
                sd=((a['variance']+b['variance'])/2)**.5 if gap is not None else None
                result.append({'scope':scope,'trait':field,'treated_rows':a.get('rows',0),'control_rows':b.get('rows',0),
                  'treated_missing':a.get('missing',0),'control_missing':b.get('missing',0),
                  'treated_mean':a.get('mean'),'control_mean':b.get('mean'),'grant_minus_claim':gap,
                  'smd':gap/sd if sd else None,'treated_observed_weight':a.get('observed_weight',0),
                  'control_observed_weight':b.get('observed_weight',0),'weights':'original frozen ATT weights; no reweighting after missingness'})
        with (out/'trajectory_balance.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
        counts=[dict(zip(['month','received_mercy','status','rows','att_weight'],r)) for r in c.execute(
            'SELECT month,received_mercy,status,count(*),sum(a1_att_weight) FROM f GROUP BY ALL ORDER BY 1,2,3').fetchall()]
        io.js(out/'sample_accounting.json',counts)
        return {'rows':expected_rows,'balance_rows':len(result)}
    finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)

def report(root,desktop,summary,final=None):
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');name='A1_TRAJECTORY_REPORT_'+stamp
    public=root/'reports'/stamp;public.mkdir(parents=True);io.js(public/'SUMMARY.json',summary)
    for source in (PACKAGE/'README.md',PACKAGE/'DESIGN.md',PACKAGE/'VALIDATION.json'):
        if source.is_file():shutil.copyfile(source,public/source.name)
    if final:
        for name_ in ('trajectory_balance.csv','sample_accounting.json'):shutil.copyfile(final/name_,public/name_)
    files=[dict(path=p.name,sha256=io.sha(p),bytes=p.stat().st_size) for p in sorted(public.iterdir()) if p.is_file()]
    io.js(public/'REPORT_MANIFEST.json',files)
    dest=desktop/(name+'.zip');temp=Path(str(dest)+'.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(public.iterdir()):z.write(p,name+'/'+p.name)
    os.replace(temp,dest);sidecar=Path(str(dest)+'.sha256');sidecar.write_text(io.sha(dest)+'  '+dest.name+'\n')
    print('UPLOAD: '+str(dest));print('UPLOAD: '+str(sidecar))

def execute(args):
    started=time.monotonic();project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():raise RuntimeError('Connect XT_Pro and check project/Desktop paths')
    base=project/OUT_REL;base.mkdir(parents=True,exist_ok=True)
    lock=(base/'RUN.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another trajectory build is already running')
    with io.heartbeat('Checking frozen A1 inputs'):prep,sources,records,expected,authority=authenticate(project)
    engine_path=engines.find_engine(project,args.stockfish)
    engine_sha=io.load(PACKAGE/'evidence/engine_benchmark_summary.json')['sha256'];engine_meta=engines.probe(engine_path,engine_sha)
    io.log(f'Verified {engine_meta["name"]}; {args.workers} workers; 100,000 nodes per position; Threads=1 per engine.')
    confdata={'version':VERSION,'preparation_config_sha256':authority['config_sha256'],'lineage':authority['lineage'],
        'targets':records,'code':{p.name:io.sha(p) for p in sorted(PACKAGE.glob('*.py'))},
        'design_sha256':io.sha(PACKAGE/'DESIGN.md'),'request_url':fetch.URL,'engine':engine_meta}
    conf=io.cfgsha(confdata);root=base/conf[:16];root.mkdir(exist_ok=True);io.js(root/'RUN_CONFIG.json',confdata)
    io.log('Private outputs: '+str(root));io.log('One API request at a time; zero pause after success; automatic Stockfish stage follows recovery.')
    with io.heartbeat('Preparing or verifying the download plan'):
        plan,_=io.stage(root/'plan',conf,lambda out:build_plan(out,sources,expected))
    units=io.load(plan/'units.json')
    io.log(f'Download plan complete: {len(units):,} batches. Starting move recovery.')
    client=fetch.Client()
    try:
        with io.heartbeat('Recovering moves and clocks'):
            replays,recovery=recover_all(root,plan,units,conf,client)
    except Exception:
        blocked=io.load(root/'RECOVERY_BLOCKED.json') if (root/'RECOVERY_BLOCKED.json').is_file() else {}
        report(root,desktop,{'status':'A1_TRAJECTORY_RECOVERY_STOPPED','config_sha256':conf,'blocked':blocked,
            'network_requests_this_invocation':client.requests,'private_rows_in_report':False})
        raise
    report(root,desktop,{'status':'A1_TRAJECTORY_MOVES_RECOVERED','config_sha256':conf,'recovery':recovery,
        'next_step':'Stockfish starts automatically in the same process','private_rows_in_report':False})
    gc.collect();paths,engine=evaluate_all(root,replays,conf,engine_path,engine_meta,args.workers)
    final,_=io.stage(root/'final',conf,lambda out:assemble(out,paths,expected['target_rows']))
    summary={'status':'A1_TRAJECTORY_BUILD_COMPLETE' if recovery['verified']==expected['target_rows'] else 'A1_TRAJECTORY_BUILD_COMPLETE_WITH_MISSING',
        'config_sha256':conf,'preparation_config_sha256':authority['config_sha256'],'recovery':recovery,'engine':engine,
        'target_rows':expected['target_rows'],'requested_positions':expected['requested_board_positions'],
        'elapsed_seconds_this_invocation':time.monotonic()-started,'new_treatment_effects_estimated':False,
        'session_result_controls_built':False,'upstream_files_modified':False,'private_rows_in_report':False,
        'limitations':['Trajectory variables are pre-receipt but post-opponent-assignment.',
            'Raw API clock units are preserved; elapsed thinking times and historical finish times are not inferred.',
            'Terminal boards and searches returning fewer than 100000 nodes are explicitly flagged.',
            'CP changes involving mate scores stay missing; mate distances are retained separately.',
            'Balance uses frozen A1 weights and reports missingness; it does not establish random receipt.']}
    io.js(root/'_SUCCESS.json',summary);report(root,desktop,summary,final);io.log(summary['status']);lock.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path(os.environ.get('A1_TRAJ_PROJECT_ROOT','/Volumes/XT_Pro/lichess_kindness')))
    p.add_argument('--desktop',type=Path,default=Path(os.environ.get('A1_TRAJ_DESKTOP',str(Path.home()/'Desktop/Lichess_Desktop'))))
    p.add_argument('--workers',type=int,default=int(os.environ.get('A1_TRAJ_WORKERS','10')))
    p.add_argument('--stockfish',default=os.environ.get('A1_TRAJ_STOCKFISH'))
    args=p.parse_args()
    if not 1<=args.workers<=10:p.error('Workers must be 1–10')
    try:execute(args)
    except KeyboardInterrupt:io.log('Interrupted; run the same command to reuse completed batches');return 130
    except Exception as e:io.log('STOPPED: '+str(e));traceback.print_exc();return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
