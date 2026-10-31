from util import *
from panel import prepare
from estimation import fit_models
from reporting import compare_reference,manuscript_tables
from inputs import guard
from cache_inputs import guard_cache
import shutil

def execute(auth,cache,run,key,workers,memory,shards,counts):
    timings={};started=time.monotonic()
    frames,audit=prepare(auth,cache,run,key,workers,memory)
    timings['frame_join']=time.monotonic()-started
    guard(auth);guard_cache(cache)
    reference=run/'PRIVATE/reference_fit';material=run/'PRIVATE/material_fit'
    started=time.monotonic()
    baseline=fit_models(frames/'reference.parquet',reference,digest([key,'reference']),workers,memory,shards)
    # Return aggregate reference evidence even if the reproduction gate stops.
    # No account identifiers or game rows are present in these model summaries.
    diagnostic=run/'report/reference_reproduction';diagnostic.mkdir(parents=True,exist_ok=True)
    for filename in ('coefficients.csv','planned_contrasts.csv','adjusted_profiles.csv',
                     'model_samples.csv','model_row_support.csv','coefficient_order.json','model_covariances.npz'):
        shutil.copy2(reference/'report'/filename,diagnostic/filename)
    reproduction=compare_reference(reference/'report',ROOT/'evidence/a2_reference',run/'report/REFERENCE_REPRODUCTION.csv')
    timings['reference_reproduction']=time.monotonic()-started
    log('All 53 archived responsibility models reproduced; fitting corrected material frame.')
    started=time.monotonic()
    new=fit_models(frames/'material.parquet',material,digest([key,'material']),workers,memory,shards)
    timings['material_regressions']=time.monotonic()-started
    # Aggregate-only CSV/JSON/NPZ outputs. Duplicated Parquet tables stay in PRIVATE.
    for p in sorted((material/'report').iterdir()):
        if p.is_file() and p.suffix in ('.csv','.json','.npz','.png'):
            shutil.copy2(p,run/'report'/p.name)
    shutil.copy2(frames/'SAMPLE_RECONCILIATION.csv',run/'report/SAMPLE_RECONCILIATION.csv')
    guard(auth);guard_cache(cache)
    summary=manuscript_tables(run/'report',ROOT/'evidence/a2_reference')
    save(run/'report/FEATURE_LINEAGE.json',dict(lineage=cache['lineage'],cache_files=len(cache['features']),
        target_sha256=cache['lineage']['target_sha256'],new_engine_evaluations=0,new_api_calls=0,
        cache_contract='Original target hash, repaired report hashes, original unit ID roster, overlay hashes and each repaired projection receipt key verified.'))
    return dict(sample=audit,regression_results=summary,reference_reproduction=reproduction,resource_plan=new['resource_plan']),timings
