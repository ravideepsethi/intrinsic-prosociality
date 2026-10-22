#!/usr/bin/env python3
from __future__ import annotations
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'): os.environ[k]='1'
import argparse, fcntl, shutil, sys, traceback
from pathlib import Path
from utils import *
from source import pool_wave1_common as common
from core import *
from models import all_models
from activity import run_activity

def main():
    p=argparse.ArgumentParser(description='Cache-only flag, recipient support, visibility and activity-proxy first pass')
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path); p.add_argument('--chronology-root',type=Path)
    p.add_argument('--output',type=Path); p.add_argument('--phase',choices=['core','activity','all'],default='all')
    p.add_argument('--threads',type=int,default=8); p.add_argument('--workers',type=int,default=4)
    p.add_argument('--memory',default='6GB'); p.add_argument('--worker-memory',default='2GB')
    args=p.parse_args(); require(1<=args.threads<=10 and 1<=args.workers<=10,'Use 1–10 threads/workers')
    project=args.project.expanduser().resolve(); require(project.is_dir(),'Project not mounted: '+str(project))
    run=(args.output or project/'output/country_profile_first_pass_v100/run').expanduser().resolve()
    run.mkdir(parents=True,exist_ok=True); (run/'report').mkdir(exist_ok=True); (run/'PRIVATE').mkdir(exist_ok=True)
    lock=open(run/'RUN.lock','a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    package=read(ROOT/'PACKAGE_HASHES.json')
    for name,digest in package.items(): require(sha(ROOT/name)==digest,'Package file changed: '+name)
    snapshot=project/SNAPSHOT_REL; require(snapshot.is_file(),'Certified August snapshot not found: '+str(snapshot))
    require(sha(snapshot)==SNAPSHOT_SHA,'August profile snapshot SHA-256 mismatch')
    sources=[('august',snapshot)]; candidates=sorted(project.glob(SUPPLEMENT_GLOB))
    good=[f for f in candidates if sha(f)==SUPPLEMENT_SHA]
    if good: sources.append(('september',good[0]))
    if candidates and not good: log('No September supplement matches its certified checksum; August-only analysis retained.')
    ids=dict(version=VERSION,package_hash=signature(package),snapshot_sha=SNAPSHOT_SHA,
      supplement_sha=SUPPLEMENT_SHA if good else None,sample_fingerprint=read(ROOT/'authority/SAMPLE_AUTHORITY.json')['sample_fingerprint'])
    identity=signature(ids); idfile=run/'RUN_IDENTITY.json'
    if idfile.exists(): require(read(idfile)['identity']==identity,'Existing output has a different package/input identity; use a new --output directory')
    else: dump(idfile,dict(identity=identity,inputs=ids))
    dump(run/'report'/'RUN_SCOPE.json',dict(**ids,network_requests=0,profile_sources=[x[0] for x in sources],
      models='August only, returned, active accounts; exploratory selected-sample associations',
      pair_tables='All available August and September profiles; snapshot dates retained separately',
      population_weighting=False,threads=args.threads,workers=args.workers,memory=args.memory))
    shutil.copyfile(ROOT/'METHODS.md',run/'report/METHODS.md')
    db=connection(args.memory,args.threads,run/'PRIVATE/spill')
    try:
        if args.phase in ('core','all'):
            with Heartbeat('Profile audit'):
                normalize_profiles(db,sources,run)
            sample=args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
            with Heartbeat('Authenticate current panel'):
                auth=common.authenticate_sample(sample,verify_hashes=True,hash_workers=min(args.threads,4))
            dump(run/'report'/'SAMPLE_LINEAGE.json',common.compact_sample_lineage(auth))
            with Heartbeat('Project current panel and rebuild chooser histories'):
                prepare_panel(db,run,auth,identity)
            with Heartbeat('Coverage, country-pair support and visibility tables'):
                core_tables(db,run)
            report_zip(run,'SUPPORT')
            all_models(db,run)
            for name in ['profiles.parquet','accounts.parquet','user_map.parquet']:
                certify(run/'PRIVATE'/name,identity)
            dump(run/'report'/'CORE_SUCCESS.json',dict(status='COUNTRY_PROFILE_CORE_OK',identity=identity))
            report_zip(run,'CORE'); log('CORE_READY — this report can be reviewed while activity scanning continues')
        else:
            require((run/'report/CORE_SUCCESS.json').is_file(),'Run --phase core first')
            require(read(run/'report/CORE_SUCCESS.json')['identity']==identity,'Core source identity changed')
            for name in ['profiles.parquet','accounts.parquet','user_map.parquet']:
                require(valid(run/'PRIVATE'/name,identity),'Core checkpoint missing: '+name)
            for path in sorted((run/'PRIVATE/panel').glob('*.parquet')):
                require(valid(path,identity),'Panel checkpoint missing: '+str(path))
            require(len(list((run/'PRIVATE/panel').glob('*.parquet')))==24,'Expected 24 projected monthly files')
            restore_views(db,run)
        if args.phase in ('activity','all'):
            run_activity(db,project,run,args,identity)
            dump(run/'report'/'ACTIVITY_SUCCESS.json',dict(status='COUNTRY_PROFILE_ACTIVITY_OK',identity=identity))
            report_zip(run,'COMPLETE')
        log('COUNTRY_PROFILE_FIRST_PASS_OK')
    except Exception as e:
        dump(run/'ERROR.json',dict(error=str(e),traceback=traceback.format_exc()))
        log('STOPPED: '+str(e)+'; completed checkpoints retained.'); raise
    finally:
        db.close(); lock.close()

if __name__=='__main__': main()
