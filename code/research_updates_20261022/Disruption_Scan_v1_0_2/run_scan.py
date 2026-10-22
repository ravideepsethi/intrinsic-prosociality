#!/usr/bin/env python3
"""Run locally against read-only Lichess archives, returning aggregate diagnostics."""
import argparse,fcntl,platform,shutil,sys,time,traceback,zipfile
from pathlib import Path
import numpy as np,pandas as pd
from support import *
from aggregate import api_month,traffic_month
from detector import *
from reporting import diagnostics,plot_episodes,review_text

def package_code():
 p=PKG/'PACKAGE_MANIFEST.json'
 if not p.is_file():raise RuntimeError('Package manifest missing')
 d=read(p)
 for r in d['files']:
  f=PKG/r['path']
  if not f.is_file() or sha(f)!=r['sha256']:raise RuntimeError('Code bundle changed: '+r['path'])
 return sha(p)

def bundle(attempt,desktop,status,cfg):
 pub=attempt/'public';pub.mkdir(parents=True,exist_ok=True)
 js(pub/'RUN_STATUS.json',status);js(pub/'RUN_CONFIGURATION.json',cfg)
 for name in ('DESIGN.md','PACKAGE_MANIFEST.json'):shutil.copy2(PKG/name,pub/name)
 stamp=attempt.name;out=Path(desktop)/('DISRUPTION_SCAN_REPORT_'+stamp+'.zip');out.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for p in sorted(pub.rglob('*')):
   if p.is_file():z.write(p,arcname=out.stem+'/'+str(p.relative_to(pub)))
 out.with_suffix('.zip.sha256').write_text(sha(out)+'  '+out.name+'\n')
 log('UPLOAD: '+str(out));log('UPLOAD: '+str(out)+'.sha256');return out

def run(args):
 began=time.monotonic();project=Path(args.project).expanduser().resolve();desktop=Path(args.desktop).expanduser().resolve()
 code=package_code();cfg=dict(version='1.0.2',project=str(project),workers=args.workers,memory=args.memory,top=args.top,
  start=utc(START),end_exclusive=utc(END),code_manifest_sha256=code,thresholds=THRESHOLDS,windows=WINDOWS,
  references_days=REFERENCES,skip_traffic=args.skip_traffic,no_main_overlay=args.no_main_overlay,
  environment=dict(python=platform.python_version(),duckdb=duckdb.__version__,numpy=np.__version__,pandas=pd.__version__))
 if not project.is_dir():raise FileNotFoundError('Project directory does not exist: '+str(project))
 root=project/'derived/replication/disruption_scan_v102_PRIVATE'/sig(cfg)[:12];root.mkdir(parents=True,exist_ok=True)
 lock=(root/'RUN.lock').open('a')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise RuntimeError('This identical disruption run is already active')
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');attempt=root/'attempts'/stamp;pub=attempt/'public';pub.mkdir(parents=True)
 js(root/'CONFIG.json',cfg);status={};issues=[];summaries=[];traffic=[];rc=0
 try:
  source_schemas=[];items,issues=discover(project,source_schemas)
  js(pub/'legacy_schema_diagnostics.json',source_schemas)
  selected={r['month'] for r in items}
  js(pub/'input_discovery.json',dict(eligible_sources=[{k:v for k,v in r.items() if k!='paths'} for r in items],issues=issues,
    unavailable_months=[m for m in MONTHS if m not in selected],scope='canonical broad API frame only; no timeout-only substitution'))
  if not items:raise RuntimeError('No completed broad API months with the required timestamp/account schema. See input_discovery.json; no API refetch performed.')
  status['preflight']=dict(status='COMPLETE',eligible_months=sorted(selected),expected_rows=sum(r['expected_rows'] for r in items))
  if args.preflight_only:
   status['scan']={'status':'NOT_RUN_PREFLIGHT_ONLY'}
  else:
   for item in items:
    m=item['month']
    try:
     s=api_month(item,root/'api'/m,code,args.workers,args.memory);summaries.append(s)
     for n in ('timestamp_audit.csv','daily_counts.csv'):
      p=pub/'monthly_audits'/m/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/'api'/m/n,p)
    except Exception as e:
     rc=2;issues.append(dict(month=m,stage='API',error=str(e)));log('API month failed '+m+': '+str(e))
    js(pub/'module_issues.json',issues)
   good=[r['month'] for r in summaries if r['coverage_usable']]
   if not good:raise RuntimeError('No API months passed timing/account coverage gates')
   if not args.skip_traffic:
    for m in good:
     try:traffic.append(traffic_month(project,m,root/'traffic'/m,code,args.workers,args.memory))
     except Exception as e:rc=2;traffic.append(dict(month=m,available=False,reason=str(e)));log('Traffic unavailable '+m+': '+str(e))
   pd.DataFrame(summaries).to_csv(pub/'api_month_coverage.csv',index=False);js(pub/'traffic_coverage.json',traffic)
   status['api_aggregation']=dict(status='COMPLETE_AVAILABLE_MONTHS',months=good,rows=sum(r['included'] for r in summaries),unknown_or_failed_months=[m for m in MONTHS if m not in good])
   # Prevent stale traffic output from a prior attempt being used after an input-validation failure.
   allowed_traffic={r['month'] for r in traffic if r.get('available')}
   counts,all_counts,all_speeds,starts,valid=assemble(root,summaries)
   for m in good:
    if m not in allowed_traffic:
     a,b=bounds(m);starts[(a-START)//MINUTE:(b-START)//MINUTE]=np.nan
   adjust=bool(allowed_traffic==set(good) and not args.skip_traffic)
   volume=before_traffic(starts) if adjust else None
   mode='same_weekday_minute_with_predetermined_start_volume' if adjust else 'same_weekday_minute_without_traffic_adjustment'
   with heartbeat('Screening discovery accounts'):
    seeds=find_seeds(counts,valid,volume)
    pd.DataFrame(seeds).to_csv(pub/'discovery_threshold_crossings.csv',index=False)
    candidates=select_episodes(seeds,args.top)
    # Freeze list BEFORE touching validation-account counts or diagnostic overlays.
    js(pub/'CANDIDATES_FROZEN.json',dict(rule=THRESHOLDS,baseline_mode=mode,candidates=candidates,discovery_only=True))
   with heartbeat('Checking disjoint validation accounts'):
    episodes=validate(candidates,counts,valid,volume)
   episodes=diagnostics(attempt,episodes,summaries,args.workers,args.memory,project,not args.no_main_overlay,root)
   with heartbeat('Writing episode figures'):
    plot_episodes(pub,episodes,counts,all_counts,all_speeds,starts,valid,volume,mode)
   review_text(pub,episodes,summaries,mode,issues)
   status['screen']=dict(status='COMPLETE_EXPLORATORY_CANDIDATE_SCREEN',threshold_crossings=len(seeds),candidates=len(episodes),
     replicated_candidates=sum(e['replicates_in_disjoint_accounts'] for e in episodes),externally_verified_outages=0,baseline_mode=mode,
     interpretation='No treatment effects estimated; candidate list requires incident validation')
 except Exception as e:
  rc=2;status['failure']=dict(status='FAILED',message=str(e));(pub/'ERROR.txt').write_text(traceback.format_exc());log('FAILED: '+str(e))
 finally:
  status['runtime_seconds']=time.monotonic()-began;bundle(attempt,desktop,status,cfg);lock.close()
 return rc

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--project',default='/Volumes/XT_Pro/lichess_kindness');p.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
 p.add_argument('--workers',type=int,default=4);p.add_argument('--memory',default='6GB');p.add_argument('--top',type=int,default=30)
 p.add_argument('--preflight-only',action='store_true');p.add_argument('--skip-traffic',action='store_true');p.add_argument('--no-main-overlay',action='store_true')
 a=p.parse_args()
 if not 1<=a.workers<=10:p.error('workers must be 1–10')
 if not 1<=a.top<=100:p.error('top must be 1–100')
 return run(a)
if __name__=='__main__':sys.exit(main())
