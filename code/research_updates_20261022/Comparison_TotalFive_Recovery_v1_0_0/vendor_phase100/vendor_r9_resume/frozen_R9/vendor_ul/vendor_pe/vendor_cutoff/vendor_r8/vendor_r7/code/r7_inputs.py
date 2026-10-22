"""Bind completed runs; extend ENV only for previously unrequested pair/months."""
from r7_common import *
from performance_runtime import Runtime

def completed_file(root,relative,conf):
    p=Path(root)/relative
    env_common.checked_stage_files(p.parent,conf,[p.name])
    return p

def authenticate(project,env_root=None,phase_root=None):
    binding={}
    for name,explicit,rel in [('environment',env_root,env_common.OUTPUT_REL),
                             ('phase50',phase_root,'derived/replication/run2_phase50_analysis_v100_PRIVATE')]:
        evidence=ROOT/'evidence'/name;summary=io.load(evidence/'summary.json');conf=summary['config_sha256']
        root=Path(explicit).expanduser().resolve() if explicit else project/rel/conf[:12]
        if not root.is_dir():raise RuntimeError('Completed '+name+' run is required: '+str(root))
        config=io.load(root/'config.json')
        if io.cfgsha(config)!=conf:raise RuntimeError('Wrong '+name+' configuration')
        io.checked(root/'report/summary.json',io.sha(evidence/'summary.json'))
        binding[name]=dict(root=str(root),conf=conf,config=config)
    e=Path(binding['environment']['root']);ec=binding['environment']['conf']
    f=Path(binding['phase50']['root']);fc=binding['phase50']['conf']
    paths=dict(original=completed_file(e,'iv_queries/original.parquet',ec),
       receipt=completed_file(e,'environment_prepared/receipt_original_author_clean/model.parquet',ec),
       entry=completed_file(f,'split/entry_new_phase50.parquet',fc),
       ordinary=completed_file(f,'split/ordinary_new_phase50.parquet',fc),
       entry_comp=completed_file(f,'entry_comp_prepared/new_phase50.parquet',fc),
       ordinary_comp=completed_file(f,'secondary_prepared/new_phase50.parquet',fc),
       rates=completed_file(e,'rates/rates.parquet',ec))
    counts={'original':2682330,'receipt':2682329,'entry':7371688,'ordinary':4764089}
    for k,n in counts.items():
        if pq.ParquetFile(paths[k]).metadata.num_rows!=n:raise RuntimeError('Frozen row count changed: '+k)
    source=binding['environment']['config']['binding']['source']
    # Source paths can move only with the named project root, preserving their suffix.
    for category in ('chron','panels'):
        for record in source[category]:
            record['path']=str(upstream.relocate(project,record['path']))
    binding['source']=source
    binding['author_ids']=binding['environment']['config']['binding']['author_ids']
    binding['paths']={k:str(v) for k,v in paths.items()}
    return binding

def add_competitive(src,cs,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([src]));c.execute('CREATE VIEW b AS SELECT * FROM '+io.parq([cs]))
            if c.execute('SELECT count(*)-count(DISTINCT row_id) FROM b').fetchone()[0]:raise RuntimeError('Duplicate competitive row IDs')
            if c.execute('SELECT count(*) FROM b ANTI JOIN a USING(row_id)').fetchone()[0]:raise RuntimeError('Competitive rows outside frozen frame')
            for key in ('recipient_id','opponent_id','archive_start_ms'):
                if c.execute('SELECT count(*) FROM a JOIN b USING(row_id) WHERE a.'+key+' IS DISTINCT FROM b.'+key).fetchone()[0]:
                    raise RuntimeError('Competitive join identity mismatch: '+key)
            fields='a.*,'+','.join('b.'+k for k in env_common.COMP_COLUMNS)
            n=io.copy(c,'SELECT '+fields+' FROM a LEFT JOIN b USING(row_id) ORDER BY a.row_id',tmp/'model.parquet')
            if n!=pq.ParquetFile(src).metadata.num_rows:raise RuntimeError('Competitive attachment changed rows')
            return dict(rows=n)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[src,cs])[0]/'model.parquet'

def missing_requests(inputs,oldrates,root,conf,memory):
    req,info=env_rates.requests(inputs,root/'all',conf,memory)
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([req/'requests.parquet']))
            c.execute('CREATE VIEW b AS SELECT * FROM '+io.parq([oldrates]))
            if c.execute('SELECT count(*) FROM (SELECT person,partner,month_code,count(*) n FROM b GROUP BY ALL HAVING n<>1)').fetchone()[0]:
                raise RuntimeError('Duplicate archived ENV keys')
            n=io.copy(c,'SELECT a.* FROM a ANTI JOIN b USING(person,partner,month_code) ORDER BY person,partner,month_code',tmp/'requests.parquet')
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([tmp/'requests.parquet']))
            io.copy(c,'SELECT DISTINCT person FROM q ORDER BY person',tmp/'people.parquet')
            io.copy(c,'SELECT DISTINCT person,partner FROM q ORDER BY person,partner',tmp/'pairs.parquet')
            io.table(tmp/'windows.parquet',io.read(req/'windows.parquet'))
            return dict(missing_requests=n,all_requests=info['request_rows'],windows=info['windows'])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root/'missing',conf,build,[req/'requests.parquet',oldrates])

def prepare_environment(binding,root,conf,memory,workers,runtime):
    paths={k:Path(v) for k,v in binding['paths'].items()};e=Path(binding['environment']['root']);ec=binding['environment']['conf']
    entry=add_competitive(paths['entry'],paths['entry_comp'],root/'entry_scores',conf,memory-1)
    ordinary=add_competitive(paths['ordinary'],paths['ordinary_comp'],root/'ordinary_scores',conf,memory-1)
    req,info=missing_requests([entry,ordinary],paths['rates'],root/'requests',conf,memory-1)
    ratepaths=[paths['rates']]
    if info['missing_requests']:
        panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if '.partial_' in folder.name or not folder.is_dir():continue
            p=completed_file(e,str(folder.relative_to(e)/'events.parquet'),ec);r=io.load(folder/'_DONE.json')
            panels.append(dict(path=str(p),minimum=r['minimum'],maximum=r['maximum']))
        if not panels:raise RuntimeError('Completed ENV numerator event caches unavailable')
        wm=max(.5,(memory-2)/workers)
        jobs,scan=env_rates.chronology_jobs(binding['source']['chron'],info['windows'],panels,req,root/'rate_parts',conf,wm)
        for job in jobs:job['authors']=binding['author_ids']
        io.js(root/'rate_scan_plan.json',dict(scan,reused_requests=info['all_requests']-info['missing_requests'],new_requests=info['missing_requests']))
        runtime.mapped(env_rates.chronology_job,jobs,workers,'ENV missing pair/month counts from local chronology')
        fresh,_=env_rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'new_rates',conf,memory-1,workers)
        ratepaths.append(fresh/'rates.parquet')
    def union(tmp):
        c=io.conn(tmp/'spill',memory-1,1)
        try:
            q=' UNION ALL '.join('SELECT * FROM '+io.parq([p]) for p in ratepaths)
            c.execute('CREATE VIEW r AS '+q)
            if c.execute('SELECT count(*) FROM (SELECT person,partner,month_code,count(*) n FROM r GROUP BY ALL HAVING n<>1)').fetchone()[0]:raise RuntimeError('Overlapping old/new ENV requests')
            n=io.copy(c,'SELECT * FROM r ORDER BY person,partner,month_code',tmp/'rates.parquet')
            return dict(rows=n)
        finally:finish_connection(c,tmp/'spill')
    rates=stable_stage(root/'combined_rates',conf,union,ratepaths)[0]/'rates.parquet'
    attached={'S0_original':paths['original'],'S0':paths['receipt']}
    for name,src in [('F50',entry),('O50',ordinary)]:
        dest,_=env_rates.attach(src,rates,root/name,conf,memory-1);attached[name]=dest/'model.parquet'
    return attached

def support_report(paths):
    rows=[]
    for sample,path in paths.items():
        if sample=='S0_original':continue
        cols=['row_id','environment_supported','complete','games','comp_n_7d','comp_adjusted_7d','comp_expected_7d']+ENV
        d=arrays(io.read(path,cols));s=np.asarray(d['environment_supported'],bool);complete=np.asarray(d['complete'],bool);games=np.asarray(d['games'],float)
        if not np.array_equal(s,complete&(games>0)):raise RuntimeError('ENV support encoding changed')
        if any(not np.isfinite(d[k][s]).all() for k in ENV):raise RuntimeError('Missing supported ENV values')
        counts=[('supported',s),('incomplete_window',~complete),('complete_zero_other_opponent_denominator',complete&(games==0)),
                ('missing_or_invalid_history',complete&~np.isfinite(games))]
        if sum(int(m.sum()) for _,m in counts)!=len(s):raise RuntimeError('ENV exclusion reasons fail to partition rows')
        for reason,m in counts:
            rows.append(dict(sample=sample,reason=reason,n=int(m.sum()),share=float(m.mean()),
                row_set_sha256=design.row_digest(d['row_id'][m]) if m.any() else None))
        rows.append(dict(sample=sample,reason='competitive_supported',n=int(comp_mask(d).sum())))
        rows.append(dict(sample=sample,reason='competitive_and_environment_supported',n=int((comp_mask(d)&s).sum())))
    return rows
