"""Authenticate completed frames, replay baseline, and extend frozen ENV caches."""
from r9_common import *
import r7_inputs as upstream_inputs
import ul_models

def bind_baseline(project,explicit=None):
    paths,binding,parts,reference,cutoff,pe=old.authenticate(project)
    root=Path(explicit) if explicit else project/'derived/replication/iv_leave_pair_out_v100_PRIVATE'/BASE_CONF[:12]
    expected=u.load(ROOT/'evidence/baseline/summary.json')
    u.require(u.load(root/'report/summary.json')==expected,'Baseline completed report changed')
    u.require(expected['completed_new_models']==14 and expected['progress_percent']==100,'Baseline not complete')
    for rec in u.load(ROOT/'evidence/baseline/REPORT_MANIFEST.json'):
        r.io.checked(root/'report'/rec['path'],rec['sha256'],rec['bytes'])
    cfg=u.load(root/'config.json')
    u.require(cfg['conf']==BASE_CONF and cfg['reference_sha256']==u.sha(reference),'Baseline configuration/reference changed')
    for name in ('S0','F50'):stage_file(root/'scores_combined'/(name+'.parquet'),BASE_CONF)
    stage_file(root/'ordinary_scores/scores.parquet',BASE_CONF)
    # Resolve every chronology source against the supplied project root.
    for category in ('chron','panels'):
        for rec in binding['source'][category]:rec['path']=str(u.relocate(rec['path'],project))
    binding['environment']['root']=str(u.relocate(binding['environment']['root'],project))
    return {k:Path(v) for k,v in paths.items()},binding,parts,reference,cutoff,root

def phase_candidates(project,desktop):
    roots=set()
    for pointer in desktop.glob('*PHASE*100*LATEST_PRIVATE.json'):
        value=u.load(pointer)
        for key in ('root','analysis_root'):
            if value.get(key):roots.add(u.relocate(value[key],project))
    rep=project/'derived/replication'
    for path in rep.glob('run2_phase*analysis*_PRIVATE/*/report/summary.json'):
        if u.load(path).get('phase_percent')==100:roots.add(path.parent.parent)
    for path in rep.glob('run2_phase*analysis*_PRIVATE/*/split/entry_new_phase100.parquet'):
        if (path.parent/'_DONE.json').exists() and (path.parent/'ordinary_new_phase100.parquet').exists():roots.add(path.parent.parent)
    return sorted(roots)

def bind_phase(project,desktop,explicit=None):
    candidates=[Path(explicit).expanduser().resolve()] if explicit else phase_candidates(project,desktop)
    complete=[]
    for p in candidates:
        report=u.load(p/'report/summary.json')
        frame_ready=all((p/'split'/n).exists() for n in ('_DONE.json','entry_new_phase100.parquet','ordinary_new_phase100.parquet'))
        if report.get('phase_percent')==100 and frame_ready:
            complete.append(p)
    u.require(len(complete)<=1,'Multiple completed Phase 100 analyses: specify --comparison-root to bind one')
    if explicit and not complete:
        u.require(u.load(Path(explicit)/'report/summary.json').get('phase_percent')==75,
                  'Explicit comparison root is not a completed Phase 75/100 analysis')
    phase=100 if complete else 75
    root=complete[0] if complete else (Path(explicit) if explicit else
        project/'derived/replication/run2_phase75_analysis_v101_PRIVATE'/PHASE75_CONF[:12])
    report=u.load(root/'report/summary.json');conf=report['config_sha256']
    u.require(report['phase_percent']==phase,'Comparison phase differs')
    config=u.load(root/'config.json')
    u.require(r.io.cfgsha(config)==conf,'Comparison configuration hash differs')
    if phase==75:
        u.require(report['status'].endswith('ANALYSIS_COMPLETE'),'Reviewed Phase 75 analysis incomplete')
        u.require(report==u.load(ROOT/'evidence/phase75/summary.json'),'Phase 75 differs from reviewed report')
        manifest=u.load(ROOT/'evidence/phase75/REPORT_MANIFEST.json')
    else:
        # Completed frame stages are sufficient: do not wait for unrelated Phase 100 fits.
        stage_file(root/'split/bridge.json',conf)
        bridge=u.load(root/'split/bridge.json')
        u.require(bridge.get('checks') and all(x.get('game_identity_and_all_features_reproduced') is True for x in bridge['checks']),
                  'Phase 100 frames lack the frozen-feature bridge certificate; do not silently fall back to Phase 75')
        base_config=u.load(project/'derived/replication/run2_phase75_analysis_v101_PRIVATE'/PHASE75_CONF[:12]/'config.json')
        u.require(r.io.cfgsha(base_config)==PHASE75_CONF,'Reviewed Phase 75 configuration missing for Phase 100 rule comparison')
        for key in ('local_plan','specifications','authors'):
            u.require(config.get(key)==base_config.get(key) and key in base_config,'Phase 100 frame definition changed: '+key)
        # The public report may still change while unrelated models run. Bind
        # immutable config + completed split receipt instead, never that live report.
        manifest=[]
    for rec in manifest:r.io.checked(root/'report'/rec['path'],rec['sha256'],rec['bytes'])
    paths={};digests={}
    for name,family in [('F','entry'),('O','ordinary')]:
        key=family+'_new_phase'+str(phase)
        p=stage_file(root/'split'/(key+'.parquet'),conf)
        accounting=report['sample_accounting'] if phase==75 else u.load(root/'split/bridge.json')['sample_counts']
        want=accounting[key]
        n=pq.ParquetFile(p).metadata.num_rows
        u.require(n==want['rows'],'Comparison frame count changed')
        digest=r.design.row_digest(col(p,'row_id'))
        digests[name]=digest
        if 'row_set_sha256' in want:u.require(digest==want['row_set_sha256'],'Comparison row digest changed')
        if phase==75:u.require(n==({'F':11057763,'O':7146627}[name]),'Wrong Phase 75 frame')
        paths[name]=p
    return paths,dict(phase_percent=phase,configuration_sha256=conf,frame_rows={k:pq.ParquetFile(v).metadata.num_rows for k,v in paths.items()},frame_row_sha256=digests,
        immutable_frame_receipt_sha256=u.sha(root/'split/_DONE.json'),
        selection='completed Phase 100 frame stages at startup (independent of unrelated model completion)' if phase==100 else 'reviewed completed Phase 075 frames',
        phase100_snapshot_frozen_at_start=True),root

def verify_phase_source(phase_root,binding,parts):
    source=u.load(phase_root/'INPUTS_PRIVATE.json')
    ids=source['author_ids'];ids=list(ids.values()) if isinstance(ids,dict) else ids
    u.require(sorted(ids)==sorted(binding['author_ids']),'Comparison author identity binding differs')
    keys=('month','shard','sha256','rows')
    def lineage(records):return sorted([{k:v[k] for k in keys} for v in records],key=lambda v:(v['month'],v['shard']))
    u.require(lineage(source['parts'])==lineage(parts),'Comparison and receipt donor source lineages differ')
    u.require(sorted(v['sha256'] for v in source['panels'])==sorted(v['sha256'] for v in binding['source']['panels']),
              'Comparison and receipt prospective event sources differ')
    return dict(author_ids_matched=True,all_384_donor_parts_matched=True,prospective_panel_hashes_matched=True)

def replay_baseline(paths,base,material,root,conf,workers,memory):
    jobs=[]
    for level in old.LEVELS:
        for sample,kind in [('S0','iv'),('F50','entry'),('O50','ordinary')]:
            for screen in (('all','neutral') if sample=='S0' else ('all',)):
                name=f'{sample}__{screen}__all_time__{level}'
                score=base/('ordinary_scores/scores.parquet' if sample=='O50' else 'scores_combined/'+sample+'.parquet')
                jobs.append(ul_models.make_job(paths[sample],score,root/'fits'/name,conf,sample,kind,level,
                    screen,material if screen=='neutral' else None))
        for variant in ('all_time','before','after'):
            name=f'S0__timing_common__{variant}__{level}'
            jobs.append(ul_models.make_job(paths['S0'],base/'scores_combined/S0.parquet',root/'fits'/name,conf,
                'S0','iv',level,variant=variant,cohort='timing_common'))
    for job in jobs:
        src=base/'fits'/Path(job['output']).name
        old.prior.check_stage(src,BASE_CONF,['result.json','dependencies_PRIVATE.json'])
        for dep in u.load(src/'dependencies_PRIVATE.json'):
            # Paths are authenticated by their actual named inputs, not by a stale mount prefix.
            candidates=[job['input'],job['scores']]+([job['material']] if job['material'] else [])
            match=[p for p in candidates if Path(p).name==Path(dep['path']).name]
            u.require(len(match)==1,'Ambiguous baseline dependency')
            r.io.checked(match[0],dep['sha256'])
    runtime.mapped(ul_models.fit_job,jobs,workers,memory,'Step 0: reproduce all 14 frozen models',35,100)
    checks=[]
    for job in jobs:
        name=Path(job['output']).name
        check=assert_close(u.load(Path(job['output'])/'result.json'),u.load(base/'fits'/name/'result.json'),name)
        checks.append(dict(model=name,passed=True,**check))
    u.require(len(checks)==14,'Baseline model plan changed')
    r.io.js(root/'model_reproduction.json',checks)
    return checks

def verify_frame_bridge(new,oldpath,root,conf,memory):
    """Every prior game must survive with its frozen X0 inputs/outcomes intact."""
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+u.parq([new]))
            c.execute('CREATE VIEW b AS SELECT * FROM '+u.parq([oldpath]))
            bn=pq.ParquetFile(oldpath).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT a.game_id) FROM a JOIN b USING(game_id)').fetchone()==(bn,bn),
                      'Expanded comparison frame lost or duplicated old games')
            required=(['recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code','tc_base_s','tc_inc_s',
                'recipient_rating','opponent_rating','n_7d','counterparts_7d','expected_7d','adjusted_7d','pre_games_30d']+
                [f'{x}_{d}' for d in (30,90) for x in ('fair','kind','disconnect','receipt','claim')])
            # O has prospective outcomes; F need not have complete prospective outcomes.
            if 'ordinary' in new.name:required+=['y','reached']
            else:required+=['analysis_entry_90','recipient_disconnect_main','active_timeout']
            names=set(pq.ParquetFile(new).schema_arrow.names)
            u.require(set(required)<=names,'Expanded comparison frame misses frozen model columns')
            terms=[]
            for k in required:
                field=pq.ParquetFile(oldpath).schema_arrow.field(k)
                expr=f'a."{k}" IS DISTINCT FROM b."{k}"'
                if pa.types.is_floating(field.type):expr+=f' AND NOT coalesce(abs(a."{k}"-b."{k}")<=2e-10+1e-8*abs(b."{k}"),FALSE)'
                terms.append('('+expr+')')
            u.require(c.execute('SELECT count(*) FROM a JOIN b USING(game_id) WHERE '+' OR '.join(terms)).fetchone()[0]==0,
                      'Frozen features differ on old/new frame overlap')
            return dict(old_rows_checked=bn,frozen_features_checked=required,passed=True,row_ids_rebound=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[new,oldpath])[1]

def prepare_environment(paths,binding,root,conf,workers,memory):
    # This is a separate canonical-game scan for missing ENV keys, not another donor scan.
    # F50 moved to R7/entry_outcomes when Y was attached. O50 still points to
    # the original prepared ENV directory, which may belong to reviewed v1.0.0.
    oldrates=Path(paths['O50']).parent.parent/'combined_rates/rates.parquet'
    env_cache_conf=u.load(Path(paths['O50']).parent/'_DONE.json')['config_sha256']
    stage_file(oldrates,env_cache_conf)
    req,info=upstream_inputs.missing_requests([paths['F'],paths['O']],oldrates,root/'requests',conf,memory-2)
    ratepaths=[oldrates];scan={}
    if info['missing_requests']:
        e=Path(binding['environment']['root']);ec=binding['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not folder.is_dir() or not (folder/'_DONE.json').exists():continue
            p=stage_file(folder/'events.parquet',ec);meta=u.load(folder/'_DONE.json')
            panels.append(dict(path=str(p),minimum=meta['minimum'],maximum=meta['maximum']))
        u.require(len(panels)>0,'ENV numerator event caches missing')
        jobs,scan=r.env_rates.chronology_jobs(binding['source']['chron'],info['windows'],panels,req,root/'rate_parts',conf,1.)
        for j in jobs:j.update(authors=binding['author_ids'],memory_gb=1.6)
        runtime.mapped(r.env_rates.chronology_job,jobs,workers,memory,'Missing frozen ENV pair/month counts',60,70)
        rates,_=r.env_rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'fresh_rates',conf,memory-2,1)
        ratepaths.append(rates/'rates.parquet')
    def union(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW a AS '+' UNION ALL '.join('SELECT * FROM '+u.parq([p]) for p in ratepaths))
            u.require(c.execute('SELECT count(*)-count(DISTINCT (person,partner,month_code)) FROM a').fetchone()[0]==0,'Duplicate ENV keys')
            return dict(rows=r.io.copy(c,'SELECT * FROM a ORDER BY person,partner,month_code',tmp/'rates.parquet'))
        finally:r.finish_connection(c,tmp/'spill')
    rates=r.stable_stage(root/'combined_rates',conf,union,ratepaths)[0]/'rates.parquet'
    result=dict(paths)
    for sample in ('F','O'):
        dest,_=r.env_rates.attach(paths[sample],rates,root/sample,conf,memory-2);result[sample]=dest/'model.parquet'
    return result,dict(public(info),scan=scan,old_rates_reused=True)
