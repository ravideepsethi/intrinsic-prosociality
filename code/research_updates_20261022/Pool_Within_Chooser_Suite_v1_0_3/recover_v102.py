#!/usr/bin/env python3
"""Authenticate the returned v102 run, reuse valid estimates, rerun only S4."""
from __future__ import annotations
import argparse
import csv
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='1'
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
import fe_suite as fe
import parallel_fe as parallel
import run_suite as original
from vendor import wave1_common as auth

ROOT=Path(__file__).resolve().parent
SOURCE_SHA='e9bce31cbd75c7021850611912837a10060a98fe535982b220cc2a39073bb1ef'
SOURCE_TAG='20260917T002432Z_12243'
SOURCE_FINGERPRINT='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30'
PASSED_STATES=['A_additive','S1_state_stage','S2_plus_clocks','S3_full']


def verify_manifest(root):
    with (root/'REPORT_FILE_HASHES.tsv').open() as stream:
        manifest=list(csv.DictReader(stream,delimiter='\t'))
    recorded=set()
    for row in manifest:
        p=(root/row['relative_path']).resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file():raise ValueError('Invalid report manifest path')
        if p.stat().st_size!=int(row['bytes']) or auth.sha256_file(p)!=row['sha256']:
            raise ValueError(f'Report manifest failed: {row["relative_path"]}')
        recorded.add(p)
    actual={p.resolve() for p in root.rglob('*') if p.is_file() and p.name!='REPORT_FILE_HASHES.tsv'}
    # Nested manifests are themselves covered by the outer manifest.
    actual={p.resolve() for p in root.rglob('*') if p.is_file()}-{(root/'REPORT_FILE_HASHES.tsv').resolve()}
    if actual!=recorded:raise ValueError('Unmanifested or duplicate report files')
    return len(manifest)


def authenticate_returned(destination):
    original.extract_checked(ROOT/'evidence/RETURNED_V102.zip',destination,SOURCE_SHA)
    source=destination/('POOL_WITHIN_CHOOSER_SUITE_RESULTS_v102_'+SOURCE_TAG)
    count=verify_manifest(source)
    if json.loads((source/'SAMPLE_LINEAGE.json').read_text())['fingerprint']!=SOURCE_FINGERPRINT:
        raise ValueError('Returned run has wrong sample fingerprint')
    meta=json.loads((source/'MODEL_DESIGN.json').read_text())
    if meta['rows']!=41534331:raise ValueError('Returned run has wrong row count')
    for group in ['states','weighting','speed_fe','patron']:
        checks=pq.read_table(source/group/'numerical_checks.parquet').to_pylist()
        good=[r for r in checks if group!='states' or r['model'] in PASSED_STATES]
        if len(good)!=(4 if group=='states' else 1):raise ValueError('Missing completed model checks')
        for r in good:
            for k in ('score_error','score_vs_moments_error','normal_equation_error'):
                if not np.isfinite(r[k]) or r[k]>1e-7:raise ValueError(f'Cannot reuse {r["model"]}: {k}')
    ledger=json.loads((source/'RUN_LEDGER.json').read_text())
    for group in ['weighting','speed_fe','patron']:
        if not any(r['analysis']==group and r['action']=='NEW_ESTIMATES_COMPLETE' for r in ledger['modules']):
            raise ValueError(f'Cannot reuse incomplete {group}')
    return source,meta,count


def recover_completed_states(source,meta,out):
    """Export the saved v102 estimates; do not pretend they are newly fitted."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with np.load(source/'states/moments.npz') as z:
        S=z['S'];terms=z['terms'].tolist();counts=json.loads(str(z['counts']))
    diagnostics={r['model']:r for r in pq.read_table(source/'states/numerical_checks.parquet').to_pylist()}
    fitted=[]
    for model in PASSED_STATES:
        with np.load(source/'states'/(model+'_covariance.npz')) as z:
            names=z['terms'].tolist();beta=z['beta_pp']/100;cov=z['cov_pp2']/10000
        ix=np.array([terms.index(t)+1 for t in names]);G=S[np.ix_(ix,ix)];b=S[ix,0]
        f=fe.solve(G,b)
        np.testing.assert_allclose(f['beta'],beta,atol=1e-8,rtol=1e-8)
        if not np.isfinite(cov).all():raise ValueError('Nonfinite saved covariance')
        np.testing.assert_allclose(cov,cov.T,atol=1e-12,rtol=1e-10)
        sse=float(S[0,0]-2*np.dot(beta,b)+np.dot(beta,G@beta))
        f.update(name=model,terms=names,beta=beta,cov=cov,counts=counts,fe='chooser',weight='opportunity',
          score_error=diagnostics[model]['score_error'],normal_error=diagnostics[model]['normal_equation_error'],
          within_r2=1-sse/S[0,0])
        fitted.append(f)
        for p in (source/'states').glob(model+'_*'):
            shutil.copy2(p,out/p.name)
    fe.export(fitted,meta,out)
    fe.csv_write(out/'numerical_checks.csv',[diagnostics[n] for n in PASSED_STATES])
    fe.json_write(out/'ORIGIN.json',{'action':'VERIFIED_SAVED_V102_ESTIMATES_EXPORTED',
      'models':PASSED_STATES,'source_archive_sha256':SOURCE_SHA,
      'note':'Saved coefficients/covariances unchanged. S4 is rerun separately.'})
    return fitted


def locate_cache(project,meta,explicit=None):
    candidates=[explicit.expanduser().resolve()] if explicit else sorted(
      (project/'derived/replication/within_chooser_suite_v102_PRIVATE').glob(SOURCE_TAG+'_*/common_model_PRIVATE.parquet'))
    for path in candidates:
        if path.is_file() and pq.ParquetFile(path).metadata.num_rows==meta['rows']:
            if auth.sha256_file(path)==meta['cache_sha256']:return path
    raise FileNotFoundError('The SHA-verified v102 common_model_PRIVATE.parquet was not found. '
      'Keep the v102 private work directory on XT_Pro. If moved, pass --cache /absolute/path/common_model_PRIVATE.parquet. '
      'Recovery will not substitute another sample or silently rebuild it.')


def run(args):
    started=time.monotonic();original.verify_package()
    project=args.project_root.expanduser().resolve()
    if not project.is_dir():raise FileNotFoundError(f'Mount the project drive: {project}')
    workers=min(args.workers,os.cpu_count() or 1)
    base=project/'derived/replication/within_chooser_suite_v103_PRIVATE';base.mkdir(parents=True,exist_ok=True)
    tag=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+str(os.getpid())
    private=Path(tempfile.mkdtemp(prefix=tag+'_',dir=base))
    public=private/('POOL_WITHIN_CHOOSER_SUITE_RESULTS_v103_'+tag);public.mkdir()
    timing=[];modules=[];failures=[]
    fe.log(f'Targeted S4 recovery: approximately 3–6 minutes, allow 10; {workers} workers, one numerical thread each. Setup time is additional.')
    fe.log(f'Private work directory: {private}')
    try:
        source,meta,entries=authenticate_returned(private/'returned_source')
        cache=locate_cache(project,meta,args.cache)
        cache_stat=(cache.stat().st_size,cache.stat().st_mtime_ns)
        timing.append({'phase':'authentication','seconds':time.monotonic()-started})
        fe.json_write(public/'SOURCE_AUTHENTICATION.json',{'source_archive_sha256':SOURCE_SHA,
          'manifest_entries_verified':entries,'cache_sha256':meta['cache_sha256'],
          'rows':meta['rows'],'sample_fingerprint':SOURCE_FINGERPRINT})
        # Preserve the exact previous ledger/audits under an explicit provenance directory.
        provenance=public/'v102_provenance';provenance.mkdir()
        for name in ['RUN_LEDGER.json','RUNTIME_RECEIPT.json','ENVIRONMENT.json','states_FAILED.json']:
            shutil.copy2(source/name,provenance/name)
        shutil.copytree(source/'states',provenance/'states')
        for p in source.iterdir():
            if p.is_file() and (p.suffix in ('.parquet','.csv') or p.name in
              ['MODEL_DESIGN.json','SAMPLE_LINEAGE.json','PATRON_SOURCE.json']):shutil.copy2(p,public/p.name)
        for name in ['completed_analyses','weighting','speed_fe','patron']:
            shutil.copytree(source/name,public/name)
            modules.append({'analysis':name,'action':'VERIFIED_UNCHANGED_V102_RESULTS'})
        fits=recover_completed_states(source,meta,public/'states')
        modules.append({'analysis':'states_A_S1_S2_S3','action':'VERIFIED_SAVED_V102_ESTIMATES_EXPORTED'})
        paths,receipt=parallel.shards(cache,private/'shards',workers)
        fe.json_write(public/'PARQUET_PARTITIONS.json',receipt)
        timing.append({'phase':'chooser_partitioning','seconds':receipt['seconds']})
        t0=time.monotonic()
        try:
            with parallel.pool(workers) as executor:
                exact=parallel.fit_group(paths,meta,public/'exact_ply_recovery','exact_ply_recovery',executor,args.batch_size)
            if exact[0]['counts']!=fits[0]['counts']:raise ValueError('S4 recovery changed the sample')
            fe.export(exact,meta,public/'exact_ply_recovery')
            fe.export(fits+exact,meta,public/'states')
            old=pq.read_table(public/'states/numerical_checks.parquet').to_pylist()
            new=pq.read_table(public/'exact_ply_recovery/numerical_checks.parquet').to_pylist()
            fe.csv_write(public/'states/numerical_checks.csv',old+new)
            modules.append({'analysis':'S4_exact_early_ply','action':'NEW_ESTIMATES_COMPLETE'})
        except Exception as exc:
            failures.append('S4_exact_early_ply')
            fe.json_write(public/'S4_FAILED.json',{'error':str(exc),'traceback':traceback.format_exc()})
            modules.append({'analysis':'S4_exact_early_ply','action':'FAILED','reason':str(exc)})
            fe.log(f'S4 recovery did not pass: {exc}. Diagnostic archive will be written.')
        timing.append({'phase':'exact_ply_recovery','seconds':time.monotonic()-t0})
        if (cache.stat().st_size,cache.stat().st_mtime_ns)!=cache_stat or auth.sha256_file(cache)!=meta['cache_sha256']:
            raise ValueError('Certified cache changed during recovery')
        outcome='COMPLETE' if not failures else 'PARTIAL_REQUIRES_REVIEW'
        fe.json_write(public/'RUN_LEDGER.json',{'status':outcome,'modules':modules,'failed_or_blocked':failures})
        fe.json_write(public/'_SUCCESS.json' if not failures else public/'_PARTIAL.json',{
          'status':outcome,'rows':meta['rows'],'source_fingerprint':SOURCE_FINGERPRINT,
          'cache_hash_verified_before_and_after':True,'network_requests':0,'private_rows_in_archive':False})
        fe.json_write(public/'ENVIRONMENT.json',{'python':sys.version,'platform':platform.platform(),
          'numpy':np.__version__,'scipy':scipy.__version__,'pyarrow':pa.__version__,
          'workers':workers,'blas_threads_per_worker':1})
        fe.json_write(public/'RUNTIME_RECEIPT.json',{'seconds_before_archiving':time.monotonic()-started,
          'workers':workers,'phase_seconds':timing,'scope':'Recovery only; previous run timing under v102_provenance'})
        fe.csv_write(public/'runtime.csv',timing)
        code=public/'executed_package';code.mkdir()
        for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
            _,name=line.split('  ',1);p=code/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
        shutil.copy2(ROOT/'SHA256SUMS.txt',code/'SHA256SUMS.txt')
        (public/'READ_FIRST.md').write_text('Status: '+outcome+'\n\n'
          'Only S4 was rerun. A/S1/S2/S3 were exported from validated saved v102 coefficients and covariances. '
          'Weighting, chooser-by-speed, Patron, rating, and recipient-FE results are authenticated copies.\n\n'
          'Main combined state table: states/TABLE.md and states/contrasts.parquet. '
          'S4 original diagnostics are under v102_provenance; new diagnostics under exact_ply_recovery. '
          'Read RUN_LEDGER.json. An unidentified contrast is not zero.\n')
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
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--cache',type=Path)
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--batch-size',type=int,default=32768)
    args=p.parse_args()
    if not 1<=args.workers<=10 or args.batch_size<16:p.error('workers must be 1..10 and batch-size >=16')
    sys.exit(run(args))


if __name__=='__main__':main()
