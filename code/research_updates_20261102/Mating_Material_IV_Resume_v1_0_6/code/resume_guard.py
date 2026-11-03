"""Authenticate the reviewed partial run without rebuilding completed stages."""
from bootstrap import *

BASE_PACKAGE_HASH='fcc1e08e1e3b1f50f21aa57f32137d2890d9df95f6e6e7214f55371ec944784c'
EXPECTED_CONF='12093d55b7ee9f737696982b8ebaef7b0706c27adc4fb12482a99aabf985d482'


def verify_cache_history(current,baseline):
    # Cache acquisition adds attempts; the reviewed failed attempt remains evidence.
    identity=('configuration','target_sha256','approved_games','endpoint',
              'historical_offline_hold','analytical_network','original_audit_reused','private_rows_exported')
    require(all(current.get(k)==baseline.get(k) for k in identity),
            'Metadata acquisition scope or identity changed since review')
    old=baseline['attempts'];new=current.get('attempts',[])
    require(len(new)>=len(old) and new[:len(old)]==old,
            'Reviewed metadata request history was changed or removed')


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
        if path.as_posix()=='comparisons/METADATA_CACHE_COMPLETION.json':
            require(p.is_file(),'Metadata acquisition history is missing')
            verify_cache_history(read(p),read(authority/'METADATA_CACHE_COMPLETION_V104.json'))
            checked+=1
            continue
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
                'old_chron_cache/PRIVATE/chronology/features.parquet',
                'PRIVATE/locally_eligible/queries.parquet'):
        c.check_stage(run/'comparisons'/rel,conf)
    from metadata_cache import cached_plan
    cached_plan(a,run/'comparisons',conf,read(run/'comparisons/PRIVATE/BINDING90.json'))
    validate_saved_frames(run,conf)
    record=dict(execution_repair='1.0.6',baseline_configuration=conf,
        baseline_package_manifest_sha256=BASE_PACKAGE_HASH,
        repair_package_manifest_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),
        completed_public_files_verified=checked,completed_stages_skipped=old['completed'],
        fixes=['partitioned_environment_cache_agreement_and_priority',
               'partitioned_missing_environment_requests_and_corrections',
               'partitioned_environment_lookup_then_streaming_attachment',
               'aggregate_reader_buffer_cap_for_128_partitions'],
        inherited_completed_repairs=['REPAIR_V101.json','REPAIR_V102.json','REPAIR_V103.json','REPAIR_V104.json','REPAIR_V105.json'],
        no_completed_statistical_results_recomputed=True,analytical_network=False,
        metadata_cache_acquisition='Already complete; no acquisition or reconciliation is run',
        completed_history_shards_reused=16,streaming_left_batch_rows=65536,
        streaming_right_buffer_rows_per_shard=8192,
        maximum_right_row_group_rows=65536,
        maximum_total_right_row_group_rows=1048576,
        environment_partitions=128,
        new_completed_substeps_reused=['history_attachment','factual_volume90','roles24','labels90'],
        oversized_right_row_groups_normalized_sequentially=True,
        expected_remaining_hours=[2,3],runtime_is_provisional=True)
    save(run/'report/REPAIR_V106.json',record)
    log(f'Resume verified: {checked} completed public files, material inputs, primary frame and estimates unchanged.')
    return record


def validate_saved_frames(run,conf):
    """Require the reviewed metadata, histories, factual volume, roles and labels."""
    cr=run/'comparisons'
    for name in ('queries.parquet','metadata.parquet','dispositions.parquet'):
        c.check_stage(cr/'PRIVATE/metadata_complete'/name,conf)
    resolution=read(cr/'report/METADATA_HOLD_RESOLUTION.json')
    require(resolution['status']=='RESOLVED' and resolution['configuration']==conf
            and resolution['new_unresolved_rows']==0,'Metadata reconciliation is not complete')
    count=0
    for k in range(16):
        query=cr/'PRIVATE/behavior_queries90'/f'outcome_{k:02}.parquet'
        result=cr/'PRIVATE/behavior90/outcomes'/f'{k:02}'/'outcomes.parquet'
        c.check_stage(query,conf);c.check_stage(result,conf)
        require(rows(query)==rows(result),'Saved history shard changed its row count')
        count+=rows(result)
    require(count==rows(cr/'PRIVATE/metadata_complete/queries.parquet'),
            'Saved history shards do not cover the completed comparison metadata')
    for rel in ('PRIVATE/behavior_combined90/features.parquet',
                'PRIVATE/factual_volume_90/plan/known.parquet',
                'PRIVATE/factual_volume_90/plan/missing.parquet',
                'PRIVATE/factual_volume_90/combined/source.parquet',
                'PRIVATE/labeled90/model.parquet','PRIVATE/labeled90/counts.json'):
        c.check_stage(cr/rel,conf)
    for k in range(24):c.check_stage(cr/'PRIVATE/roles'/f'{k:02}'/'roles.parquet',conf)
    for rel in ('PRIVATE/behavior_combined90/features.parquet',
                'PRIVATE/factual_volume_90/combined/source.parquet','PRIVATE/labeled90/model.parquet'):
        require(rows(cr/rel)==count,'Saved comparison frame row count changed: '+rel)
    expected=read(ROOT/'authority/iv_batch_partial/VOLUME_90_V105.json')
    plan=cr/'PRIVATE/factual_volume_90/plan'
    require(rows(plan/'known.parquet')==expected['reused'] and
            rows(plan/'missing.parquet')==expected['missing'] and count==expected['total'],
            'Saved factual volume coverage differs from the reviewed run')
    require(read(cr/'PRIVATE/labeled90/counts.json')==
            read(ROOT/'authority/iv_batch_partial/ENTRY_LABEL_COUNTS_V105.json'),
            'Saved entry labels changed since review')
