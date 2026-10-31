#!/usr/bin/env python3
"""Build the fixed nested frame and portable API input. No network or estimates."""
from __future__ import annotations
import argparse, csv, fcntl, hashlib, json, os, platform, shutil, sys, time
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import expansion_common as x
import cache_scan
import local_io as io

PKG=Path(__file__).resolve().parent

def authenticate(project):
    a=io.load(PKG/'evidence/authority.json');old=project/x.OLD_REL
    io.checked(old/'comparison_sample/games.parquet',a['original_frame_sha256'])
    config=io.load(old/'config.json')
    if io.comparison_v110_config_sha(config)!=a['original_validity_config_sha256']:
        raise RuntimeError('Original validity configuration differs')
    if config.get('sample_modulus')!=1024 or config.get('sampling_seed')!=x.SEED or config.get('sampling_months')!=list(x.MONTHS):
        raise RuntimeError('Original sampling rule differs')
    if config.get('script_hashes',{}).get('validity_local.py')!=a['original_sampler_sha256']:
        raise RuntimeError('Original executed sampler differs from the reviewed source')
    if pq.ParquetFile(old/'comparison_sample/games.parquet').metadata.num_rows!=x.OLD_ROWS:
        raise RuntimeError('Original frame row count changed')
    # Read the completed expanded result, not a newer run selected by filename order.
    expanded=project/x.EXPANDED_REL
    io.checked(expanded/'report/_DONE.json',a['expanded_receipt_sha256'])
    if io.cfgsha(io.load(expanded/'config.json'))!=a['expanded_config_sha256']:
        raise RuntimeError('Expanded IV configuration differs from the reviewed result')
    prior=io.load(PKG/'evidence/prior_authority.json')
    linepath=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'lineage_PRIVATE.json'
    io.checked(linepath,prior['comparison_lineage_sha256']);line=io.load(linepath)
    master=project/'derived/replication/comparison_reconciled_v100_PRIVATE/20260907T013118Z_71e0e5c6_eb4091b7a862/master/comparison_frame.parquet'
    io.checked(master,line['reconciled_master_sha256'])
    if pq.ParquetFile(master).metadata.num_rows!=x.OLD_ROWS:raise RuntimeError('Prior metadata frame count differs')
    manifest=project/x.CHRON_REL;io.checked(manifest,a['chronology_manifest_sha256'])
    with manifest.open() as f:all_rows=list(csv.DictReader(f,delimiter='\t'))
    if len(all_rows)!=852 or sum(int(r['rows']) for r in all_rows)!=7763847245:
        raise RuntimeError('Canonical chronology manifest differs')
    with (PKG/'evidence/original_comparison_sampling.csv').open() as f:authority={r['file_id']:r for r in csv.DictReader(f)}
    jobs=[]
    for r in all_rows:
        key=f'{int(r["file_index"]):04d}'
        if key not in authority:continue
        s=authority[key];p=x.relocated(project,r['path']);pf=pq.ParquetFile(p)
        names=set(pf.schema_arrow.names)
        if not {'game_id','utc_ms','archive_ordinal','white_id','black_id'}<=names:raise RuntimeError('Missing chronology fields')
        if p.stat().st_size!=int(r['bytes']) or pf.metadata.num_rows!=int(s['input_rows']) or pf.metadata.num_row_groups!=int(r['row_groups']):
            raise RuntimeError('Chronology metadata differs')
        jobs.append(dict(path=str(p),file_id=key,month=s['month'],speed=s['speed'],rows=int(s['input_rows']),
                         original_sample_rows=int(s['sample_rows']),sha256=s['input_observed_sha256'],signature=io.sig(p)))
    if len(jobs)!=105 or {r['file_id'] for r in jobs}!=set(authority):raise RuntimeError('Original 105-file frame coverage differs')
    return str(old/'comparison_sample/games.parquet'),jobs

def sample_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(out):
        if io.sig(job['path'])!=job['signature']:raise RuntimeError('Chronology changed before sampling')
        nr=kept=old=0
        with pq.ParquetWriter(out/'sample.parquet',x.frame_schema(),compression='zstd') as w:
            for batch in pq.ParquetFile(job['path']).iter_batches(columns=['game_id','utc_ms','archive_ordinal','white_id','black_id'],batch_size=262144,use_threads=False):
                t=pa.Table.from_batches([batch]);mask=x.selected(t['game_id'].to_pylist());nr+=len(t)
                if not mask.any():continue
                v=x.orient(t.filter(pa.array(mask)),job['month'],job['speed']);w.write_table(v)
                kept+=len(v);old+=int(io.arr(v,'previous_frame').sum())
        io.checked(job['path'],job['sha256'])
        if io.sig(job['path'])!=job['signature'] or nr!=job['rows'] or old!=job['original_sample_rows']:
            raise RuntimeError('Chronology/sample accounting differs from original receipt')
        return dict(scanned_rows=nr,sampled_rows=kept,previous_frame_rows=old,input_sha256=job['sha256'],input_signature=job['signature'])
    path,r=io.stage(job['out'],job['conf'],build)
    if io.sig(job['path'])!=job['signature']:raise RuntimeError('Chronology changed after completed sampling')
    if r['input_signature']!=job['signature']:io.checked(job['path'],job['sha256'])
    return dict(path=str(path),**{k:r[k] for k in ('scanned_rows','sampled_rows','previous_frame_rows')})

def assemble_frame(root,conf,parts,old,memory,expected_old=x.OLD_ROWS):
    def build(out):
        c=io.conn(out/'spill',memory,4)
        try:
            c.execute('CREATE VIEW all_rows AS SELECT * FROM '+io.parq(parts))
            n,nd,nold=c.execute('SELECT count(*),count(DISTINCT game_id),sum(previous_frame::BIGINT) FROM all_rows').fetchone()
            if n!=nd or nold!=expected_old:raise RuntimeError('Duplicate IDs or old-frame count mismatch')
            c.execute('CREATE VIEW original AS SELECT * FROM '+io.parq([old]))
            diffs=' OR '.join(f'a.{k} IS DISTINCT FROM b.{k}' for k in x.FRAME_FIELDS)
            mismatch=c.execute('SELECT count(*) FROM (SELECT * FROM all_rows WHERE previous_frame) a FULL OUTER JOIN original b USING(game_id) WHERE '+diffs).fetchone()[0]
            if mismatch:raise RuntimeError('Expanded frame does not exactly reproduce every original field and orientation')
            counts=[]
            for month in x.MONTHS:
                rows=io.copy(c,'SELECT * FROM all_rows WHERE month='+io.lit(month)+' ORDER BY game_id',out/(month+'.parquet'))
                nprior=c.execute('SELECT count(*) FROM all_rows WHERE month='+io.lit(month)+' AND previous_frame').fetchone()[0]
                counts.append(dict(month=month,rows=rows,previous_frame_rows=nprior,new_rows=rows-nprior))
            io.js(out/'counts.json',counts)
            return dict(frame_rows=n,previous_frame_rows=nold,new_rows=n-nold,original_fields_reproduced=True)
        finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    return io.stage(root/'frame',conf,build)

def aggregate_cache(root,conf,parts,memory):
    def build(out):
        c=io.conn(out/'spill',memory,4)
        try:
            if not parts:
                io.table(out/'empty.parquet',pa.Table.from_pylist([],schema=x.metadata_schema()));parts0=[out/'empty.parquet']
            else:parts0=parts
            fields=['game_id','count(*)::BIGINT AS metadata_records']
            fields += [f'first({n}) FILTER(WHERE {n} IS NOT NULL) AS {n}' for n in x.META_FIELDS]
            tests=[f'count(DISTINCT {n})>1' for n in x.META_FIELDS]
            tests += ["count(*) FILTER(WHERE coalesce(record_errors,'')<>'')>0"]
            fields += ['('+' OR '.join(tests)+') AS cached_conflict_or_prior_flag']
            io.copy(c,'SELECT '+','.join(fields)+' FROM '+io.parq(parts0)+' GROUP BY game_id',out/'metadata.parquet')
            return dict(cache_distinct_ids=pq.ParquetFile(out/'metadata.parquet').metadata.num_rows)
        finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    return io.stage(root/'cache_merged',conf,build)

def readiness_sql():
    required=('status','api_start_ms','anchor_ms','rated','variant','speed','tc_base_s','tc_inc_s','white_username','black_username','white_rating','black_rating')
    ok=[f'm.{n} IS NOT NULL' for n in required]
    ok += ['m.rated=TRUE',"m.variant='standard'",'m.speed=f.speed_partition','m.tc_base_s>0','m.tc_inc_s>=0',
           'm.api_start_ms//1000=f.utc_ms//1000','m.anchor_ms>=m.api_start_ms','m.white_username<>m.black_username',
           'm.white_rating>0','m.black_rating>0','isfinite(m.white_rating)','isfinite(m.black_rating)',
           'm.status IN ('+','.join(map(io.lit,sorted(x.core.TERMINAL)))+')',
           "(m.status NOT IN ('mate','resign') OR m.winner IN ('white','black'))"]
    return '''CASE WHEN f.previous_frame THEN 'PREVIOUS_FRAME_REUSE'
        WHEN m.game_id IS NULL THEN 'NO_CACHE'
        WHEN m.cached_conflict_or_prior_flag THEN 'CACHE_CONFLICT_OR_PRIOR_FLAG'
        WHEN m.source IS NULL OR m.source NOT IN ('''+','.join(map(io.lit,sorted(x.core.SOURCES)))+''') THEN 'CACHE_SOURCE_UNRESOLVED'
        WHEN m.source<>'pool' THEN 'CACHED_NONPOOL'
        WHEN '''+' AND '.join(ok)+''' THEN 'CACHED_POOL_METADATA'
        ELSE 'CACHE_METADATA_INCOMPLETE_OR_INVALID' END'''

def plan_requests(root,conf,memory):
    def build(out):
        c=io.conn(out/'spill',memory,4)
        try:
            c.execute('CREATE VIEW frame AS SELECT * FROM '+io.parq([root/'frame'/(m+'.parquet') for m in x.MONTHS]))
            c.execute('CREATE VIEW metadata AS SELECT * FROM '+io.parq([root/'cache_merged/metadata.parquet']))
            sql='SELECT f.*,'+readiness_sql()+' AS preparation_status FROM frame f LEFT JOIN metadata m USING(game_id)'
            io.copy(c,sql,out/'denominator.parquet')
            c.execute('CREATE VIEW d AS SELECT * FROM '+io.parq([out/'denominator.parquet']))
            counts=dict(c.execute('SELECT preparation_status,count(*) FROM d GROUP BY 1').fetchall())
            # Select only by metadata availability; ALL games remain in denominator.parquet.
            n=io.copy(c,"SELECT game_id,utc_ms,speed_partition FROM d WHERE preparation_status NOT IN ('PREVIOUS_FRAME_REUSE','CACHED_NONPOOL','CACHED_POOL_METADATA') ORDER BY retrieval_rank,game_id",out/'targets.parquet')
            io.js(out/'counts.json',counts)
            if sum(counts.values())!=pq.ParquetFile(root/'frame'/(x.MONTHS[0]+'.parquet')).metadata.num_rows+sum(pq.ParquetFile(root/'frame'/(m+'.parquet')).metadata.num_rows for m in x.MONTHS[1:]):
                raise RuntimeError('Denominator lost rows')
            return dict(api_targets=n,status_counts=counts,metadata_identity_against_global_dictionary_verified=False)
        finally:c.close();shutil.rmtree(out/'spill',ignore_errors=True)
    return io.stage(root/'requests',conf,build)

def portable(root,conf,desktop):
    dest=desktop/f'CHOOSER_COMPARISON_EXPANSION_INPUT_{conf[:12]}_PRIVATE.zip'
    def build(out):
        shutil.copyfile(root/'requests/targets.parquet',out/'targets.parquet')
        shutil.copyfile(root/'DESIGN_FREEZE.json',out/'DESIGN_FREEZE.json')
        transfer=dict(version=x.VERSION,config_sha256=conf,target_rows=pq.ParquetFile(out/'targets.parquet').metadata.num_rows,
            original_frame_reused=x.OLD_ROWS,global_identity_reconciliation_required=True,
            purpose='Additional-game metadata retrieval only; no treatment or placebo estimation')
        io.js(out/'TRANSFER.json',transfer)
        files=[dict(path=p.name,sha256=io.sha(p),bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file()]
        io.js(out/'INPUT_MANIFEST.json',dict(config_sha256=conf,files=files))
        return dict(target_rows=transfer['target_rows'])
    folder,_=io.stage(root/'portable',conf,build)
    names=['targets.parquet','DESIGN_FREEZE.json','TRANSFER.json','INPUT_MANIFEST.json']
    if dest.exists():
        side=Path(str(dest)+'.sha256')
        if not side.is_file() or io.sha(dest)!=side.read_text().split()[0]:raise RuntimeError('Existing portable ZIP checksum differs')
    else:
        x.require_disk(desktop,2+sum((folder/n).stat().st_size for n in names)/1024**3)
        with io.heartbeat('Packing private download input'):x.zip_files(folder,dest,names)
    return dest

def execute(args):
    started=time.monotonic();project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():raise RuntimeError('Connect XT_Pro and check Desktop paths')
    with io.heartbeat('Verifying existing frame and source receipts'):old,jobs=authenticate(project)
    cfg=dict(version=x.VERSION,modulus=x.MODULUS,original_modulus=1024,seed=x.SEED,months=x.MONTHS,
        authority=io.load(PKG/'evidence/authority.json'),design_sha256=io.sha(PKG/'DESIGN.md'),
        code={p.name:io.sha(p) for p in sorted(PKG.glob('*.py'))},precision=x.precision_plan())
    conf=io.cfgsha(cfg);root=project/x.OUT_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This preparation is already running')
    if (root/'config.json').exists() and io.load(root/'config.json')!=io.clean(cfg):raise RuntimeError('Resume configuration changed')
    io.js(root/'config.json',cfg)
    freeze=root/'DESIGN_FREEZE.json'
    if not freeze.exists():
        io.js(freeze,dict(config_sha256=conf,frozen_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
             phase='before new chronology sampling, cache classification and API retrieval',specification=cfg,
             expanded_design_reference=io.load(PKG/'evidence/expanded_config.json'),new_effects_estimated=False))
    elif io.load(freeze)['config_sha256']!=conf:raise RuntimeError('Freeze changed')
    io.log('Fixed nested 1-in-32 frame; same orientation; original 1,912,023 games must reproduce exactly.')
    io.log('Local preparation only: ZERO API requests; no Stockfish or effect estimates.')
    io.log('Private outputs: '+str(root));x.require_disk(project,35)
    for j in jobs:j.update(out=str(root/'sample_parts'/j['file_id']),conf=conf)
    with io.heartbeat('Sampling and verifying chronology'):
        results=io.mapped(sample_job,jobs,args.workers,'Chronology files')
    with io.heartbeat('Verifying nesting and writing 21 monthly frame files'):
        _,frame=assemble_frame(root,conf,[Path(r['path'])/'sample.parquet' for r in results],old,args.memory_gb)
    ip=root/'CACHE_INVENTORY_PRIVATE.json'
    if not ip.exists():
        with io.heartbeat('Inventory of completed local API caches'):
            sources=cache_scan.inventory(cache_scan.discover(project)+args.extra_cache_root)
        io.js(ip,sources)
    sources=io.load(ip);groups=cache_scan.group_jobs(sources)
    io.log(f'New games: {frame["new_rows"]:,}; checking {len(sources):,} completed cache files in {len(groups):,} groups.')
    cache_jobs=[dict(inputs=v,out=str(root/'cache_scan'/f'group_{k:05d}'),conf=io.cfgsha([conf,v])) for k,v in enumerate(groups)]
    results=io.mapped(cache_scan.scan_group,cache_jobs,args.workers,'Local cache groups') if cache_jobs else []
    with io.heartbeat('Reconciling cached metadata'):
        aggregate_cache(root,conf,[Path(r['path'])/'records.parquet' for r in results],args.memory_gb)
        _,requests=plan_requests(root,conf,args.memory_gb)
    summary=dict(status='COMPARISON_EXPANSION_INPUT_READY',config_sha256=conf,frame_rows=frame['frame_rows'],
        previous_frame_rows=frame['previous_frame_rows'],additional_frame_rows=frame['new_rows'],api_targets=requests['api_targets'],
        status_counts=requests['status_counts'],cache_files=len(sources),cache_parse_gaps=sum(r['cache_parse_gaps'] for r in results),
        cache_inventory_frozen=True,late_cache_files_not_implicitly_added=True,original_fields_reproduced=True,
        network_requests=0,stockfish_searches=0,effects_estimated=False,precision_plan=x.precision_plan(),
        api_hours_at_previous_rate=requests['api_targets']/29.05/3600,elapsed_seconds=time.monotonic()-started,
        identity_reconciliation_and_analysis_still_required=True)
    io.js(root/'PREPARATION_COMPLETE.json',summary)
    portable_path=portable(root,conf,desktop)
    report=root/'preparation_report';report.mkdir(exist_ok=True)
    io.js(report/'summary.json',summary);shutil.copyfile(PKG/'DESIGN.md',report/'DESIGN.md')
    shutil.copyfile(root/'frame/counts.json',report/'frame_counts.json')
    dest=desktop/f'CHOOSER_COMPARISON_EXPANSION_PREPARATION_REPORT_{conf[:12]}.zip'
    x.report_zip(report,dest)
    io.log(f'READY: {requests["api_targets"]:,} API targets; estimated {summary["api_hours_at_previous_rate"]:.1f} hours before backoffs.')
    print('UPLOAD: '+str(dest));print('UPLOAD: '+str(dest)+'.sha256')
    print('PRIVATE INPUT (keep private): '+str(portable_path));print('PRIVATE INPUT SHA: '+str(portable_path)+'.sha256')
    print('Next: RUN_DOWNLOAD.command after other Lichess API requests have finished. It also works on the home laptop with this input ZIP.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=x.BASE);p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=4)
    p.add_argument('--extra-cache-root',action='append',type=Path,default=[])
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.memory_gb<1:p.error('Require 1–10 workers and at least 1 GB for the merge')
    os.umask(0o077)
    try:execute(a)
    except KeyboardInterrupt:io.log('Interrupted; completed stages remain reusable.');raise SystemExit(130)
    except Exception as e:io.log('STOPPED: '+str(e));raise SystemExit(2)

if __name__=='__main__':main()
