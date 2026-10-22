#!/usr/bin/env python3
"""Expand the frozen main-sample audience analysis using existing local caches."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time
import zipfile
from common import atomic_json, sha, log, now, write_csv
from panel import configure, verify_panel, validate_sample
from metadata import discover_profiles, load_profiles, load_directory
from analysis import PANEL_REL, STAGES, SCOPES, build_base, diagnostics, run_estimates
from report import write_report, plot

HERE=Path(__file__).resolve().parent

def execute(root,out,cache,threads=10,memory_gb=6,extras=None,
            panel_authority=None,metadata_authority=None):
    import duckdb
    if duckdb.__version__!='1.5.5': raise RuntimeError('Use the bundled duckdb==1.5.5 environment')
    custom_authority=panel_authority is not None or metadata_authority is not None
    authority=panel_authority or json.loads((HERE/'panel_authority.json').read_text())
    meta=metadata_authority or json.loads((HERE/'metadata_authority.json').read_text())
    if out.exists(): raise FileExistsError('Output already exists; use a fresh run directory')
    cache.mkdir(parents=True,exist_ok=True);os.chmod(cache,0o700)
    started=time.monotonic()
    with (cache/'run.lock').open('a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another expanded audience run is using this cache')
        log('Verifying the frozen panel and audited metadata; no Lichess/network data requests')
        paths=verify_panel(root/PANEL_REL,authority)
        profiles=discover_profiles(root,meta)
        out.mkdir(parents=True)
        code_hashes={p.name:sha(p) for p in sorted(HERE.glob('*.py'))}
        with tempfile.TemporaryDirectory(prefix='work_',dir=cache) as work:
            work=Path(work)
            db=duckdb.connect(str(work/'analysis.duckdb'))
            configure(db,threads,memory_gb,work/'spill')
            try:
                profile_info=load_profiles(db,profiles,work,meta)
                registry_info=load_directory(db,root,meta,extras)
                key=hashlib.sha256(json.dumps({'code':code_hashes,'panel':authority,'metadata':meta,
                  'registry':registry_info},sort_keys=True).encode()).hexdigest()[:20]
                private=cache/('panel_'+key);private.mkdir(parents=True,exist_ok=True)
                # Retain only derived account flags, without raw bio/channel contents.
                shutil.copy2(work/'profile_flags.parquet',private/'profile_flags.parquet')
                build_base(db,paths,authority['monthly_inputs'],private)
                qa=validate_sample(db,authority['expected_counts'])
                log(f"Main sample reproduced: {qa['opportunities']:,} opportunities; {qa['kind_draws']:,} kind draws")
                diagnostic=diagnostics(db)
                summary,estimates,contrasts,partition=run_estimates(db,qa,out)
                # Original either-player exclusion must agree unless the user supplies new positives.
                original_check='not_requested_in_synthetic_fixture'
                if 'original_primary_groups' in meta and extras is None:
                    observed={r['group']:r for r in summary if r['threshold']==2400 and
                      r['metadata_scope']=='all_available_metadata' and r['stage']=='01_elite_title_streamer'}
                    for name,expected in meta['original_primary_groups'].items():
                        for k,v in expected.items():
                            if observed.get(name,{}).get(k)!=v:
                                raise ValueError('Original audience exclusion failed exact reproduction: '+name+'/'+k)
                    original_check='exact_counts_reproduced'
                elif extras: original_check='additional_user_supplied_positives_present'
                payload={'status':'COMPLETE_WITH_MEASUREMENT_LIMITATIONS','version':'1.0.0',
                  'authority_scope':'synthetic_validation' if custom_authority else 'frozen_41534331_main_sample',
                  'completed_utc':now(),'elapsed_seconds':time.monotonic()-started,
                  'sample_qa':qa,'panel_sha256_verified':True,'original_audience_reproduction':original_check,
                  'panel_authority':authority,'metadata_authority':meta,'code_sha256':code_hashes,
                  'profiles':profile_info,'streamer_listing':registry_info,
                  'data_network_requests':0,'private_cache_directory':str(private),
                  'runtime':{'python':platform.python_version(),'duckdb':duckdb.__version__,
                    'threads':threads,'memory_gb':memory_gb},
                  'specification':{
                    'scope':'both players; raw plus chooser FE desert gradients',
                    'primary_rating_threshold':2400,'rating_sensitivities':[2200,2500],
                    'stages':STAGES,'metadata_scopes':SCOPES,
                    'FE':'kind_draw = chooser intercept + beta * competitive; separately within each exclusion group',
                    'additional_covariates':[],
                    'identifying_sample':'competitive and clearly-worse observations of chooser accounts present in both states within the subset',
                    'middle_eval_region':'included in overall kindness rates, excluded from desert contrasts',
                    'FE_weights':'n_competitive*n_clearly_worse/(n_competitive+n_clearly_worse)',
                    'FE_CR1':'G/(G-1)*(N-1)/(N-G-1); N and G refer to identifying chooser-state switchers',
                    'CI':'95% Student t with G-1 degrees of freedom; chooser-clustered',
                    'between_group_covariance':'shared chooser scores combined before squaring',
                    'audience_observed_at_decision':False,'causal_audience_effect_identified':False,
                    'equivalence_claims':False,'metadata_selection':'Patron acquisition oversampled granting accounts',
                    'metadata_timing':'post-panel; positive account proxies do not date audiences in panel games',
                    'unknown_policy':'absence of a positive flag is not proof of absent audience; profile and numeric TV coverage tabulated separately'},
                  'summary':summary,'estimates':estimates,'between_flag_groups':contrasts,
                  'exclusion_metadata_partition':partition,**diagnostic}
                atomic_json(out/'RESULTS.json',payload)
                write_csv(out/'between_flag_groups.csv',contrasts)
                write_csv(out/'exclusion_metadata_partition.csv',partition)
                for name,rows in diagnostic.items(): write_csv(out/(name+'.csv'),rows)
                write_report(out,payload)
                plot(out,payload)
            finally: db.close()
        code_dir=out/'executed_code';code_dir.mkdir()
        for p in HERE.iterdir():
            if p.is_file() and p.suffix in ('.py','.json','.md','.txt','.command','.sha256'):
                shutil.copy2(p,code_dir/p.name)
        files=sorted(p for p in out.rglob('*') if p.is_file())
        (out/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.relative_to(out).as_posix()+'\n' for p in files))
        atomic_json(out/'_SUCCESS.json',{'status':'EXPANDED_AUDIENCE_V100_COMPLETE',
          'completed_utc':now(),'results_sha256':sha(out/'RESULTS.json'),
          'manifest_sha256':sha(out/'SHA256SUMS.txt'),'private_rows_in_export':False})
        archive=out.with_suffix('.zip')
        if archive.exists(): raise FileExistsError(archive)
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file(): z.write(p,out.name+'/'+p.relative_to(out).as_posix())
        side=Path(str(archive)+'.sha256');side.write_text(sha(archive)+'  '+archive.name+'\n')
        log('EXPANDED_AUDIENCE_V100_COMPLETE')
        print(f'RESULT_ZIP={archive}\nRESULT_SHA256={side}',flush=True)
        return payload

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--threads',type=int,default=10)
    ap.add_argument('--memory-gb',type=int,default=6)
    ap.add_argument('--extra-streamers',type=Path)
    args=ap.parse_args()
    if not 1<=args.threads<=10 or args.memory_gb<2: ap.error('Use 1–10 threads and at least 2 GB')
    root=args.project_root.expanduser().resolve()
    if not root.is_dir(): raise FileNotFoundError('Mount XT_Pro or set the project root')
    cache=root/'derived/replication/audience_expanded_v100_PRIVATE'
    execute(root,args.out.expanduser().resolve(),cache,args.threads,args.memory_gb,args.extra_streamers)

if __name__=='__main__': main()
