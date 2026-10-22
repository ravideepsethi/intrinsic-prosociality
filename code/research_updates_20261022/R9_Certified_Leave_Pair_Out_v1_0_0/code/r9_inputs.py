"""Authenticate the old run and select immutable comparison frames at startup."""
from r9_common import *
import r7_inputs, env_rates

def bind_baseline(project,baseline=None):
    paths,binding,parts,ref,cutoff,pe=old.authenticate(project)
    base=Path(baseline) if baseline else project/'derived/replication/iv_leave_pair_out_v100_PRIVATE'/BASELINE[:12]
    expected=u.load(ROOT/'evidence/baseline/summary.json')
    u.require(u.load(base/'report/summary.json')==expected,'Baseline differs from authenticated final 14-model report')
    u.require(expected['completed_new_models']==14 and expected['configuration_sha256']==BASELINE,'Wrong baseline')
    for rec in u.load(ROOT/'evidence/baseline/REPORT_MANIFEST.json'):
        r.io.checked(base/'report'/rec['path'],rec['sha256'],rec['bytes'])
    config=u.load(base/'config.json')
    u.require(config['conf']==BASELINE and config['definition']==old.DEFINITION,'Baseline config differs')
    u.require(config['reference_sha256']==u.sha(ref),'Baseline state reference differs')
    for name in ('S0','F50'):certified(base/'scores_combined'/(name+'.parquet'),BASELINE)
    certified(base/'ordinary_scores/scores.parquet',BASELINE)
    jobs=u.load(base/'MODEL_PLAN_PRIVATE.json');u.require(len(jobs)==14,'Baseline model plan is incomplete')
    for j in jobs:
        folder=u.relocate(j['output'],project)
        u.require(folder.is_relative_to(base),'Baseline model path outside its run')
        certified(folder/'result.json',BASELINE)
    return paths,binding,parts,ref,cutoff,base,jobs

def select_frames(project,binding,parts,explicit=None):
    candidates=[]
    if explicit:candidates=[Path(explicit)]
    else:
        for parent in sorted((project/'derived/replication').glob('run2_phase100_analysis*_PRIVATE')):
            candidates += sorted(parent.glob('*/report/summary.json'))
        candidates=[p.parents[1] for p in candidates]
    usable=[]
    for p in candidates:
        s=u.load(p/'report/summary.json')
        frame_files=[p/'split'/name for name in ('entry_new_phase100.parquet','ordinary_new_phase100.parquet','_DONE.json')]
        if s.get('phase_percent')==100 and all(x.is_file() for x in frame_files):
            usable.append((p,s,100))
    u.require(len(usable)<=1,'Multiple completed Phase 100 frames; specify --phase-root explicitly')
    if not usable:
        p=Path(explicit) if explicit else project/'derived/replication/run2_phase75_analysis_v101_PRIVATE'/PHASE75[:12]
        s=u.load(p/'report/summary.json');u.require(s==u.load(ROOT/'evidence/phase75/summary.json'),'Phase 75 report differs from reviewed publication')
        usable=[(p,s,75)]
    p,s,percent=usable[0];conf=s['config_sha256']
    u.require(r.io.cfgsha(u.load(p/'config.json'))==conf,'Comparison configuration hash differs')
    for rec in u.load(p/'report/REPORT_MANIFEST.json'):r.io.checked(p/'report'/rec['path'],rec['sha256'],rec['bytes'])
    if percent==75:r.io.checked(p/'report/REPORT_MANIFEST.json',u.sha(ROOT/'evidence/phase75/REPORT_MANIFEST.json'))
    source=u.load(p/'INPUTS_PRIVATE.json')
    want=sorted((x['month'],x['shard'],x['sha256'],x['rows']) for x in parts)
    got=sorted((x['month'],x['shard'],x['sha256'],x['rows']) for x in source['parts'])
    u.require(got==want,'Phase frames use a different donor/input lineage')
    ids=source['author_ids'];ids=list(ids.values()) if isinstance(ids,dict) else ids
    u.require(set(ids)==set(binding['author_ids']),'Phase author exclusion identities differ')
    f=certified(p/'split'/f'entry_new_phase{percent}.parquet',conf)
    o=certified(p/'split'/f'ordinary_new_phase{percent}.parquet',conf)
    if percent==75:
        u.require(pq.ParquetFile(f).metadata.num_rows==11057763 and pq.ParquetFile(o).metadata.num_rows==7146627,'Frozen Phase 75 counts differ')
    else:
        u.require(pq.ParquetFile(f).metadata.num_rows>=11057763 and pq.ParquetFile(o).metadata.num_rows>=7146627,'Phase 100 smaller than frozen Phase 75')
        # The downstream phase's model fits need not be finished: R9 independently
        # verifies the full Phase 50 feature bridge before using these completed frames.
    return dict(F=f,O=o),dict(root=str(p),phase_percent=percent,config_sha256=conf,
        entry_rows=pq.ParquetFile(f).metadata.num_rows,ordinary_rows=pq.ParquetFile(o).metadata.num_rows,
        source_status=s['status'],unresolved_selected_rows=s.get('unresolved_selected_rows'),
        selected_at_startup=True,phase100_selected=percent==100,completed_immutable_frames=True)

def frame_checks(paths,authors,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1);report=[]
        try:
            for name in ('S0','F50','O50','F','O'):
                c.execute('CREATE OR REPLACE VIEW q AS SELECT * FROM '+u.parq([paths[name]]))
                n,unique,bad=c.execute('SELECT count(*),count(DISTINCT row_id),sum(recipient_id=opponent_id OR recipient_id IN ('+
                    ','.join(map(str,authors))+') OR opponent_id IN ('+','.join(map(str,authors))+')) FROM q').fetchone()
                u.require(n==unique and not bad,'Invalid or author-involved frame: '+name)
                report.append(dict(sample=name,rows=n,author_rows=0,unique_row_ids=True))
            # Phase-specific row IDs are rebound: bridge by game identity, never by row ID.
            for small,large in [('F50','F'),('O50','O')]:
                c.execute('CREATE OR REPLACE VIEW a AS SELECT * FROM '+u.parq([paths[small]]))
                c.execute('CREATE OR REPLACE VIEW b AS SELECT * FROM '+u.parq([paths[large]]))
                cols=set(pq.ParquetFile(paths[small]).schema_arrow.names)&set(pq.ParquetFile(paths[large]).schema_arrow.names)
                cols-=set(r.ENV+['row_id','original_row_id','environment_supported','complete','games','own','chooser','lo','hi']+r.env_common.COMP_COLUMNS)
                # Frozen traits, controls, outcomes and identity fields must all agree on archived games.
                cols=sorted(cols&set(r.FIT_COLUMNS+list(ul_scores.QUERY_TYPES)+['game_id','anchor_ms','y','reached']))
                u.require(c.execute('SELECT count(*) FROM a JOIN b USING(game_id)').fetchone()[0]==pq.ParquetFile(paths[small]).metadata.num_rows,'Phase 50 bridge rows missing/duplicated')
                conditions=[]
                schema=pq.ParquetFile(paths[small]).schema_arrow
                for k in cols:
                    x=f'a."{k}" IS DISTINCT FROM b."{k}"'
                    if pa.types.is_floating(schema.field(k).type):x+=' AND NOT (abs(a."'+k+'"-b."'+k+'")<=2e-10)'
                    conditions.append('('+x+')')
                u.require(c.execute('SELECT count(*) FROM a JOIN b USING(game_id) WHERE '+' OR '.join(conditions)).fetchone()[0]==0,'Frozen Phase 50 fields changed in larger frame')
                report.append(dict(sample=small+'_in_'+large,all_shared_model_fields_reproduced=True,fields=cols))
            c.execute('CREATE VIEW f AS SELECT * FROM '+u.parq([paths['F']]))
            c.execute('CREATE VIEW o AS SELECT * FROM '+u.parq([paths['O']]))
            n=pq.ParquetFile(paths['O']).metadata.num_rows
            u.require(c.execute('SELECT count(*) FROM o JOIN f USING(row_id)').fetchone()[0]==n,'Ordinary rows not an exact entry subset')
            cols=['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code','n_7d','expected_7d','adjusted_7d','counterparts_7d','complete90']
            u.require(c.execute('SELECT count(*) FROM o JOIN f USING(row_id) WHERE '+' OR '.join('o.'+k+' IS DISTINCT FROM f.'+k for k in cols)).fetchone()[0]==0,'Ordinary/entry identities or histories differ')
        finally:r.finish_connection(c,tmp/'spill')
        r.io.js(tmp/'checks.json',report);return dict(checks=report)
    return r.stable_stage(root,conf,build,list(paths.values()))[1]

def environment(paths,binding,project,root,conf,memory,workers):
    # Resolve the exact combined ENV cache used by the archived F50 attachment.
    dep=u.load(Path(paths['F50']).parent/'dependencies_PRIVATE.json')
    rp=[x for x in dep if Path(x['path']).name=='rates.parquet']
    u.require(len(rp)==1,'Cannot identify frozen F50 ENV cache')
    oldrates=u.relocate(rp[0]['path'],project);r.io.checked(oldrates,rp[0]['sha256'])
    req,info=r7_inputs.missing_requests([paths['F']],oldrates,root/'requests',conf,memory-2)
    ratepaths=[oldrates]
    if info['missing_requests']:
        e=u.relocate(binding['environment']['root'],project);ec=binding['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not folder.is_dir() or '.partial_' in folder.name:continue
            p=certified(folder/'events.parquet',ec);d=u.load(folder/'_DONE.json')
            panels.append(dict(path=str(p),minimum=d['minimum'],maximum=d['maximum']))
        u.require(bool(panels),'Certified ENV numerator caches unavailable')
        source=binding.get('source',binding['environment']['config']['binding']['source'])
        chron=[dict(v,path=str(u.relocate(v['path'],project))) for v in source['chron']]
        wm=max(.5,min(1.2,(memory-2)/max(1,workers)))
        jobs,scan=env_rates.chronology_jobs(chron,info['windows'],panels,req,root/'rate_parts',conf,wm)
        for j in jobs:j.update(authors=binding['author_ids'],memory_gb=wm+.35)
        runtime.mapped(env_rates.chronology_job,jobs,workers,memory,'Attach missing frozen-definition ENV histories',90,100)
        fresh,_=env_rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'new_rates',conf,memory-2,min(workers,4))
        ratepaths.append(fresh/'rates.parquet')
    def union(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW v AS '+' UNION ALL '.join('SELECT * FROM '+u.parq([p]) for p in ratepaths))
            u.require(c.execute('SELECT count(*)-count(DISTINCT (person,partner,month_code)) FROM v').fetchone()[0]==0,'Duplicate ENV keys')
            n=r.io.copy(c,'SELECT * FROM v ORDER BY person,partner,month_code',tmp/'rates.parquet')
            return dict(rows=n,missing_requests=info['missing_requests'])
        finally:r.finish_connection(c,tmp/'spill')
    rates=r.stable_stage(root/'combined',conf,union,ratepaths)[0]/'rates.parquet'
    attached={}
    for name in ('F','O'):
        attached[name]=env_rates.attach(paths[name],rates,root/name,conf,memory-2)[0]/'model.parquet'
    return attached,dict(new_pair_month_requests=info['missing_requests'],frozen_definition_preserved=True)

def ordinary_subset(source,scores,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq([scores]));c.execute('CREATE VIEW o AS SELECT row_id FROM '+u.parq([source]))
            n=r.io.copy(c,'SELECT s.* FROM s JOIN o USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            u.require(n==pq.ParquetFile(source).metadata.num_rows,'Ordinary score join changed rows');return dict(rows=n)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[source,scores])[0]/'scores.parquet'

def learning_flags(source,shards,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT row_id,recipient_id,archive_start_ms,fair_90 FROM '+u.parq([source]))
            c.execute('CREATE VIEW f AS SELECT * FROM '+u.parq(shards))
            u.require(c.execute('SELECT count(*)-count(DISTINCT person) FROM f').fetchone()[0]==0,'Duplicate chronology identities')
            n=r.io.copy(c,'SELECT q.row_id,coalesce(f.first_competitive_ms<q.archive_start_ms,false) AS experienced_full, q.fair_90>0 AS experienced_90 FROM q LEFT JOIN f ON q.recipient_id=f.person ORDER BY row_id',tmp/'flags.parquet')
            u.require(n==pq.ParquetFile(source).metadata.num_rows,'Learning join changed rows')
            c.execute('CREATE VIEW x AS SELECT * FROM '+u.parq([tmp/'flags.parquet']))
            u.require(c.execute('SELECT count(*) FROM x WHERE experienced_90 AND NOT experienced_full').fetchone()[0]==0,'Full chronology misses an archived 90-day competitive choice')
            return dict(rows=n,full_chronology_left_censored_at='2023-11-01',history_is_before_game_start=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[source]+shards)[0]/'flags.parquet'
