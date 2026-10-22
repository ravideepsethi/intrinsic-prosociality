"""Bind explicitly reviewed parents. Never select a newest run or live journal."""
from common import *

def bind(project,work):
    auth=read(PACKAGE/'authority/parents.json');conf=auth['config_sha256']
    phase=Path(project)/'derived/replication/run2_phase25_analysis_v120_PRIVATE'/conf[:12]
    cfg=read(phase/'config.json')
    if digest(cfg)!=conf or cfg['code_sha256']!=auth['upstream_package_manifest_sha256']:
        raise RuntimeError('The phase-25 configuration/producer is not the reviewed parent')
    authenticate(phase/'report/summary.json',work,auth['summary_sha256'])
    if read(phase/'report/summary.json')['status']!='PHASE_025_AVAILABLE_CASE_ANALYSIS_COMPLETE':
        raise RuntimeError('Phase-25 analysis is incomplete')
    feature=stage_input(phase/'assembled','features.parquet',conf,work)
    source=read(phase/'INPUTS_PRIVATE.json');ids=source['author_ids']
    if set(ids)!=set(AUTHORS) or len(set(ids.values()))!=2 or min(ids.values())<0:
        raise RuntimeError('Author IDs are unresolved or ambiguous')
    require_columns(feature,BASE+['entry_eligible','complete90','previous_frame','status','recipient_username',
        'opponent_username','matched_main','recipient_disconnect_main','recipient_fair_arm_main','author_game'])
    # Parent configuration pins the immutable metadata stage receipt.
    ph=cfg['phase'];phroot=relocate(project,ph['root']);metadata=relocate(project,ph['metadata'])
    authenticate(metadata.parent.parent/'ANALYSIS_INPUTS_PRIVATE.json',work,ph['manifest_sha256'])
    rel=str((metadata.parent/'_DONE.json').relative_to(phroot))
    authenticate(metadata.parent/'_DONE.json',work,ph['receipts'][rel])
    mr=read(metadata.parent/'_DONE.json');members={r['path']:r for r in mr['files']}
    if (metadata.parent/'empty_metadata.parquet').is_file():
        paths=sorted((metadata.parent/'by_month').glob('month=*/*.parquet'))
    else: paths=[metadata]
    if not paths:raise RuntimeError('No immutable winner metadata found')
    metas=[]
    for p in paths:
        rel=str(p.relative_to(metadata.parent))
        if rel not in members:raise RuntimeError('Metadata partition not bound by receipt: '+rel)
        r=members[rel];metas.append(dict(path=str(p),sha256=r['sha256'],bytes=r['bytes']))
    main=read(PACKAGE/'authority/pool_main.json')
    mainroot=Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    live=read(mainroot/'_SUCCESS.json')
    for k in ('status','main_predicate','contract_sha256','code_sha256','observed_screen_certified','literal_immediate_rematches_certified'):
        if live.get(k)!=main[k]:raise RuntimeError('Certified main authority differs: '+k)
    if live['report_zip_sha256']!=main['report_sha256']:raise RuntimeError('Certified main report changed')
    by={r['month']:r for r in live['panel_outputs']}
    if len(by)!=24:raise RuntimeError('Certified panel inventory changed')
    for r in main['panel_outputs']:
        if any(by.get(r['month'],{}).get(k)!=r[k] for k in ('relative_path','rows','size_bytes','sha256')):
            raise RuntimeError('Certified panel inventory changed')
    panels=[dict(r,path=str(mainroot/r['relative_path'])) for r in main['panel_outputs']]
    if len(panels)!=24 or [r['month'] for r in panels]!=list(MONTHS):raise RuntimeError('Wrong month inventory')
    source_by={str(relocate(project,r['path'])):r for r in source['panels']}
    if set(source_by)!=set(r['path'] for r in panels):raise RuntimeError('Phase/main input lineages differ')
    for r in panels:
        if source_by[r['path']]['sha256']!=r['sha256']:raise RuntimeError('Panel checksum lineage mismatch')
    # Larger receipt cohort is used only for secondary descriptive dose models.
    ec=auth['environment_config_sha256']
    env=Path(project)/'derived/replication/run2_environment_diagnostics_v100_PRIVATE'/ec[:12]
    if digest(read(env/'config.json'))!=ec:raise RuntimeError('Wrong reviewed environment configuration')
    authenticate(env/'report/summary.json',work,auth['environment_summary_sha256'])
    if read(env/'report/summary.json')['status']!='ENVIRONMENT_DIAGNOSTICS_COMPLETE':
        raise RuntimeError('Environment reconstruction is incomplete')
    receipt=stage_input(env/'iv_assembled','receipt_iv.parquet',ec,work)
    require_columns(receipt,BASE+['received'])
    binding=dict(phase=str(phase),phase_conf=conf,environment=str(env),environment_conf=ec,
        feature=str(feature),receipt=str(receipt),metadata=metas,panels=panels,author_ids=ids,
        input_binding_sha256=sha(phase/'INPUTS_PRIVATE.json'),feature_sha256=sha(feature),receipt_sha256=sha(receipt))
    saved=Path(work)/'binding_PRIVATE.json'
    if saved.exists() and digest(read(saved))!=digest(binding):
        raise RuntimeError('Previously bound inputs changed; refusing stale checkpoint reuse')
    write(saved,binding);return binding
