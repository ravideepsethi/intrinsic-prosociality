"""Authenticate the reviewed partial run without rebuilding completed stages."""
from bootstrap import *

BASE_PACKAGE_HASH='fcc1e08e1e3b1f50f21aa57f32137d2890d9df95f6e6e7214f55371ec944784c'
EXPECTED_CONF='12093d55b7ee9f737696982b8ebaef7b0706c27adc4fb12482a99aabf985d482'


def verify_reports(run,authority):
    # These completed results are never rewritten by either repaired branch.
    # Aggregate model/balance exports legitimately gain additional fits.
    mutable={'STATUS.json','COVERAGE.json','model_estimates.csv','balance_joint.csv'}
    checked=0
    for rec in read(authority/'REPORT_MANIFEST.json'):
        path=Path(rec['path'])
        if path.parts[0] not in ('receipt','comparisons'):continue
        if path.parts[0]=='receipt' and path.name in mutable:continue
        base=run/'report' if path.parts[0]=='receipt' else run/'comparisons/report'
        p=base/Path(*path.parts[1:])
        require(p.is_file() and p.stat().st_size==rec['bytes'] and sha(p)==rec['sha256'],
                'Completed result changed since review: '+str(p))
        checked+=1
    return checked


def verify_primary(result,expected):
    actual={r['term']:r for r in result['estimates']}
    for old in expected:
        new=actual[old['term']]
        for field in ('sample','n','recipients','row_set_sha256'):
            require(str(new[field])==old[field],'Primary identity changed: '+field)
        for field in ('coefficient','standard_error'):
            require(abs(float(new[field])-float(old[field]))<=1e-13,'Primary estimate changed: '+field)


def verify_resume(a,run,conf,state):
    require(conf==EXPECTED_CONF,'This repair is only for the reviewed material IV run')
    authority=ROOT/'authority/iv_batch_partial'
    old=read(authority/'STATUS.json')
    require(all(state.get(name,{}).get('status')=='COMPLETE' for name in old['completed']),
            'A previously completed stage is now missing; this resume will not silently rebuild it')
    checked=verify_reports(run,authority)
    auth=read(run/'PRIVATE/AUTHENTICATED.json')
    import material_inputs
    material_inputs.authenticate(a.material_manifest,read(ROOT/'authority/REVIEW.json'),min(a.workers,3))
    for rec in auth['donors']:verify(rec)
    guard(auth)
    frames=read(run/'PRIVATE/FRAMES90.json')
    for path in frames.values():c.check_stage(path,conf)
    primary=run/'PRIVATE/models/uniform_unspaced'
    for name in ('result.json','influence_PRIVATE.parquet'):c.check_stage(primary/name,conf)
    verify_primary(read(primary/'result.json'),read(authority/'PRIMARY.json'))
    require(read(run/'report/SUPPLEMENT_REPLAY.json')['passed'],'Supplement baseline replay did not pass')
    for rel in ('PRIVATE/supported/queries.parquet','PRIVATE/supported/scores.parquet',
                'old_chron_cache/PRIVATE/chronology/features.parquet'):
        c.check_stage(run/'comparisons'/rel,conf)
    record=dict(execution_repair='1.0.2',baseline_configuration=conf,
        baseline_package_manifest_sha256=BASE_PACKAGE_HASH,
        repair_package_manifest_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        completed_public_files_verified=checked,completed_stages_skipped=old['completed'],
        fixes=['bounded_chronology_reuse_join', 'bounded_chronology_eligibility_join',
               'per_range_checkpoints_and_streamed_ordered_assembly'],
        inherited_completed_repairs='REPAIR_V101.json',
        no_completed_statistical_results_recomputed=True,production_network=False,
        expected_remaining_hours=[2,4],runtime_is_provisional=True)
    save(run/'report/REPAIR_V102.json',record)
    log(f'Resume verified: {checked} completed public files, material inputs, primary frame and estimates unchanged.')
    return record
