"""Authenticated frozen frames; projected Parquet and bounded cached-feature work."""
from r9b_common import *
from iv_history import AsOf
import duckdb, shutil

def bind(project,parent):
    cfg=u.load(parent/'config.json')
    u.require(r.io.cfgsha(cfg)==R9_CONF,'Wrong R9 parent configuration')
    expected=u.load(PACKAGE/'evidence/r9_summary.json')
    u.require(u.load(parent/'report/summary.json')==expected,'R9 completed report changed')
    for rec in u.load(PACKAGE/'evidence/r9_report_manifest.json'):
        r.io.checked(parent/'report'/rec['path'],rec['sha256'],rec['bytes'])
    u.require(expected['status']=='R9_COMPLETE','R9 is not complete')
    u.require(abs(u.load(parent/'common_scale.json')['common_score_SD']-COMMON_SD)<1e-14,'Common SD changed')
    paths,binding,parts,reference,cutoff,base=r9_inputs.bind_baseline(project)
    saved=u.load(parent/'PREPARED_INPUTS_PRIVATE.json');s0=u.relocate(saved['S0'],project)
    r.io.checked(s0,u.sha(paths['S0']))
    r9_inputs.stage_file(parent/'scores_combined/S0.parquet',R9_CONF)
    expanded=project/author_history.EXPANDED_REL
    u.require(r.io.cfgsha(u.load(expanded/'config.json'))==author_history.EXPANDED_CONF,'Frozen expanded frame config changed')
    original=r9_inputs.stage_file(expanded/'analysis/all.parquet',author_history.EXPANDED_CONF)
    u.require(pq.ParquetFile(original).metadata.num_rows==7432712,'Frozen unspaced frame changed')
    eb=binding['environment']['config']['binding']
    for key in ('histories','futures'):eb[key]=[str(u.relocate(v,project)) for v in eb[key]]
    return dict(s0=str(s0),original=str(original),parts=parts,reference=str(reference),binding=binding,features=eb,parent=str(parent))

def prepare_source(bound,root,conf,memory):
    source=Path(bound['original']);ids=bound['binding']['author_ids']
    def build(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+u.parq([source]))
            clean='recipient_id NOT IN ('+','.join(map(str,ids))+') AND opponent_id NOT IN ('+','.join(map(str,ids))+')'
            names=set(pq.ParquetFile(source).schema_arrow.names)
            need=set(r.FIT_COLUMNS)-set(['environment_supported']+r.ENV+env_common.COMP_COLUMNS+env_common.ENTRY_COLUMNS)
            need|={'row_id','game_id','recipient_id','opponent_id','month_code','archive_start_ms','anchor_ms','spaced30','spaced90','first_recipient'}
            u.require(need<=names,'Frozen all-exposure frame lacks columns: '+str(sorted(need-names)))
            fields=sorted(need)
            n=r.io.copy(c,'SELECT '+','.join('"'+k+'"' for k in fields)+',TRUE previous_frame FROM a WHERE '+clean+' ORDER BY row_id',tmp/'source.parquet')
            c.execute('CREATE VIEW q AS SELECT * FROM '+u.parq([tmp/'source.parquet']))
            for shard in range(16):
                r.io.copy(c,'SELECT * FROM q WHERE recipient_id%16='+str(shard)+' ORDER BY row_id',tmp/f'outcome_{shard:02}.parquet')
            return dict(original_rows=7432712,author_clean_rows=n,author_exposure_removals=7432712-n,
                original_spacing_preserved=True,no_replacement=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[source])[0]

def outcome_jobs(bound,prep,root,conf):
    b=bound['features'];jobs=[]
    definition=cache.definition('R9b_frozen_rows_clean_outcomes_v1',dict(parent=R9_CONF,authors=bound['binding']['author_ids'],
        histories=b['history_conf'],futures=b['main_conf']),[Path(fast.__file__)])
    for s in range(16):
        histories=[str(Path(p)/f'{s:02}.parquet') for p in b['histories']]
        futures=[str(Path(p)/f'{s:02}.parquet') for p in b['futures']]
        for paths,key in [(histories,'history_conf'),(futures,'main_conf')]:
            for path in paths:r9_inputs.stage_file(Path(path),b[key])
        job=dict(queries=str(prep/f'outcome_{s:02}.parquet'),authors=bound['binding']['author_ids'],memory=3.,memory_gb=4.5,
            conf=conf,histories=histories,futures=futures,output=str(root/'outcomes'/f'{s:02}'))
        jobs.append(cache.attach(job,root/'feature_cache','outcomes',definition,s))
    return jobs

def assemble_source(bound,prep,jobs,root,conf,memory):
    src=prep/'source.parquet';outs=[Path(j['output'])/'outcomes.parquet' for j in jobs]
    def build(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+u.parq([src]));c.execute('CREATE VIEW o AS SELECT * FROM '+u.parq(outs))
            counts=[f'{name}_{days}' for days in (30,90) for name in ('fair','kind','disconnect','receipt','claim')]
            for key in counts+['y','reached']:
                u.require(c.execute('SELECT count(*) FROM a JOIN o USING(row_id) WHERE a.'+key+' IS DISTINCT FROM o.original_'+key).fetchone()[0]==0,'Old expanded feature replay failed: '+key)
            n=pq.ParquetFile(src).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM a JOIN o USING(row_id)').fetchone()==(n,n),'Expanded history join identity failed')
            replace=counts+['y','reached']
            columns='a.* EXCLUDE('+','.join(replace)+'),'+','.join('o.'+k for k in replace)
            r.io.copy(c,'SELECT '+columns+' FROM a JOIN o USING(row_id) ORDER BY row_id',tmp/'all.parquet')
            c.execute('CREATE VIEW fresh AS SELECT * FROM '+u.parq([tmp/'all.parquet']))
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq([bound['s0']]))
            check=counts+['received','y','reached','archive_start_ms','anchor_ms','recipient_id','opponent_id','pre_games_30d']
            u.require(c.execute('SELECT count(*),count(DISTINCT fresh.row_id) FROM fresh JOIN s USING(row_id)').fetchone()==(2682329,2682329),'Expanded frame lost S0 rows')
            u.require(c.execute('SELECT count(*) FROM fresh JOIN s USING(row_id) WHERE '+' OR '.join('fresh.'+k+' IS DISTINCT FROM s.'+k for k in check)).fetchone()[0]==0,'S0/expanded cleaned feature bridge failed')
            u.require(c.execute('SELECT count(*) FROM fresh WHERE spaced90').fetchone()[0]==2682329,'90-day selection no longer matches S0')
            return dict(rows=n,S0_features_reproduced=True,old_original_features_reproduced=True,features_checked=check)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[src,bound['s0']]+outs)[0]/'all.parquet'

def query_shards(source,root,conf):
    cols=['row_id','recipient_id','opponent_id','month_code']
    def build(tmp):
        schema=pq.ParquetFile(source).schema_arrow;schema=pa.schema([schema.field(k) for k in cols])
        writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd') for s in range(16)]
        try:
            for batch in pq.ParquetFile(source).iter_batches(columns=cols,batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([batch]).cast(schema);h=r.num.user_hash(r.io.arr(t,'opponent_id'))%np.uint64(16)
                for s,w in enumerate(writers):
                    mask=h==s
                    if mask.any():w.write_table(t.filter(pa.array(mask)))
        finally:
            for w in writers:w.close()
        return dict(rows=pq.ParquetFile(source).metadata.num_rows)
    return r.stable_stage(root,conf,build,[source])[0]

def alltime(h,q,reference):
    n=len(q['row_id']);cuts=np.full(n,np.iinfo(np.int64).max,np.int64)
    ji=AsOf([h['j']],h['t'],[q['opponent_id']],cuts)
    pi=AsOf([h['j'],h['i']],h['t'],[q['opponent_id'],q['recipient_id']],cuts)
    counts=ji.count-pi.count;wins=ji.sums(h['y'])-pi.sums(h['y'])
    first=pi.order[pi.starts] if len(pi.order) else np.array([],int)
    breadth=AsOf([h['j'][first]],h['t'][first],[q['opponent_id']],cuts).count-(pi.count>0)
    mapping,audit=r9_scores.reference_map(reference,r9_scores.event_month(h['t']))
    rf=(r.num.user_hash(q['recipient_id'])%np.uint64(4)).astype(int);pred=np.zeros(n)
    for fold in np.unique(rf):
        weights,_=r9_scores.donor_weights(h,reference,fold,mapping);use=rf==fold
        value=ji.sums(weights)-pi.sums(weights);pred[use]=value[use]
    ex=np.divide(pred,counts,out=np.full(n,np.nan),where=counts>0)
    raw=np.divide(wins,counts,out=np.full(n,np.nan),where=counts>0)
    u.require(np.all((counts>=0)&(breadth>=0)&(breadth<=counts)),'Invalid donor totals')
    return dict(n=counts,counterparts=breadth,expected=ex,adjusted=raw-ex),audit

def donor_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        chunks=[]
        for rec in job['parts']:
            r.io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
            d=r.arrays(r.io.read(rec['path'],['j','i','t','y','arm','cell','fair']))
            use=d['arm'].astype(bool)&~np.isin(d['j'],job['authors'])&~np.isin(d['i'],job['authors'])
            u.require(np.array_equal(d['fair'][use].astype(bool),(d['cell'][use]//100>=2)),'Competitive donor classification differs')
            chunks.append({k:d[k][use] for k in ('j','i','t','y','cell')})
        h={k:np.concatenate([d[k] for d in chunks]) for k in chunks[0]};del chunks,d
        q=r.arrays(r.io.read(job['queries']));ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        out=dict(row_id=q['row_id']);audit=[]
        for label,mask in [('A',np.ones(len(h['j']),bool)),('competitive',h['cell']//100>=2),('noncompetitive',h['cell']//100<2)]:
            hh=h if label=='A' else {k:v[mask] for k,v in h.items()}
            score,fallback=alltime(hh,q,ref);out.update({k+'_'+label:v for k,v in score.items()})
            # Independent direct oracle including every pair exclusion and own-month model.
            error=0.
            for ix in np.unique(np.linspace(0,len(q['row_id'])-1,min(12,len(q['row_id'])),dtype=int)):
                m=(hh['j']==q['opponent_id'][ix])&(hh['i']!=q['recipient_id'][ix])
                sub={k:v[m] for k,v in hh.items()};mapping,_=r9_scores.reference_map(ref,r9_scores.event_month(sub['t']))
                fold=int(r.num.user_hash(np.array([q['recipient_id'][ix]]))[0]%np.uint64(4))
                pred,_=r9_scores.donor_weights(sub,ref,fold,mapping)
                u.require(score['n'][ix]==m.sum() and score['counterparts'][ix]==len(np.unique(sub['i'])),'Donor count oracle failed')
                if m.any():
                    error=max(error,abs(score['adjusted'][ix]-float(np.mean(sub['y']-pred))))
                    u.require(error<2e-10,'Donor-month score oracle failed')
            audit.append(dict(score=label,donor_rows=len(hh['j']),queries=len(q['row_id']),oracle_max_error=error,fallback=fallback))
        r.io.table(tmp/'scores.parquet',pa.table(out));r.io.js(tmp/'audit.json',audit)
        return dict(queries=len(q['row_id']),scores=3)
    return r.stable_stage(Path(job['output']),job['conf'],build,[j['path'] for j in job['parts']]+[job['queries'],job['reference']])[1]

def combine_scores(jobs,bound,source,root,conf,memory):
    paths=[Path(j['output'])/'scores.parquet' for j in jobs];old=Path(bound['parent'])/'scores_combined/S0.parquet'
    def build(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW q AS SELECT row_id FROM '+u.parq([source]));c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(paths))
            n=pq.ParquetFile(source).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT s.row_id) FROM s JOIN q USING(row_id)').fetchone()==(n,n),'Donor score identity failed')
            u.require(c.execute('SELECT count(*) FROM s WHERE n_A<5 OR NOT isfinite(adjusted_A)').fetchone()[0]==0,'Score A support changed')
            c.execute('CREATE VIEW old AS SELECT * FROM '+u.parq([old]))
            for k in ['n_A','counterparts_A','expected_A','adjusted_A']:
                delta=c.execute('SELECT max(abs(s.'+k+'-old.'+k+')) FROM s JOIN old USING(row_id)').fetchone()[0]
                u.require(delta is not None and delta<2e-10,'Score A differs from certified R9: '+k)
            r.io.copy(c,'SELECT * FROM s ORDER BY row_id',tmp/'scores.parquet')
            return dict(rows=n,S0_score_A_reproduced=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,paths+[old,source])[0]/'scores.parquet'

def env_attempt(job):
    try:return dict(ok=True,result=r.env_rates.chronology_job(job))
    except duckdb.OutOfMemoryException as e:return dict(ok=False,message=str(e))

def environment(bound,source,root,conf,memory,workers):
    import r7_inputs
    old=Path(bound['parent'])/'environment/combined_rates/rates.parquet'
    r9_inputs.stage_file(old,R9_CONF)
    req,info=r7_inputs.missing_requests([source],old,root/'requests',conf,memory-2)
    rates=[old]
    if info['missing_requests']:
        b=bound['binding'];e=Path(b['environment']['root']);ec=b['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not (folder/'_DONE.json').exists():continue
            path=r9_inputs.stage_file(folder/'events.parquet',ec);m=u.load(folder/'_DONE.json')
            panels.append(dict(path=str(path),minimum=m['minimum'],maximum=m['maximum']))
        jobs,scan=r.env_rates.chronology_jobs(b['source']['chron'],info['windows'],panels,req,root/'parts',conf,3.)
        for job in jobs:job.update(authors=b['author_ids'],memory=3.,memory_gb=4.5)
        result=runtime.mapped(env_attempt,jobs,min(workers,2),memory,'Missing ENV histories (bounded 3 GB workers)',50,60)
        retry=[dict(job,memory=8.,memory_gb=9.) for job,ans in zip(jobs,result) if not ans['ok']]
        if retry:
            ans=runtime.mapped(env_attempt,retry,1,memory,'Serial ENV memory retries',15,60)
            u.require(all(x['ok'] for x in ans),'ENV serial retry exceeded 8 GB; return stopped log')
        fresh,_=r.env_rates.combine(req,[j['output'] for j in jobs],[p['path'] for p in panels],root/'fresh',conf,memory-2,1)
        rates.append(fresh/'rates.parquet')
    def union(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            return dict(rows=r.io.copy(c,' UNION ALL '.join('SELECT * FROM '+u.parq([p]) for p in rates),tmp/'rates.parquet'))
        finally:r.finish_connection(c,tmp/'spill')
    rate=r.stable_stage(root/'combined',conf,union,rates)[0]/'rates.parquet'
    dest,_=r.env_rates.attach(source,rate,root/'attached',conf,memory-2)
    return dest/'model.parquet',info

def act_features(bound,project,root,conf,memory):
    a=u.load(PACKAGE/'evidence/r5_parent.json');parent=project/a['parent_relative_root']
    u.require(r.io.cfgsha(u.load(parent/'config.json'))==a['parent_key'],'R5 dose-source config differs')
    r.io.checked(parent/'report/REPORT_MANIFEST.json',a['parent_report_manifest_sha256'])
    files=[]
    for folder in sorted((parent/'months').iterdir()):
        if not (folder/'_DONE.json').exists():continue
        done=u.load(folder/'_DONE.json');u.require(done['key']==a['parent_key'],'R5 dose month key differs')
        rec=next(x for x in done['files'] if x['path']=='dose.parquet')
        p=folder/'dose.parquet';r.io.checked(p,rec['sha256'],rec['signature']['bytes']);files.append(p)
    u.require(len(files)==24,'Need the 24 authenticated R5 dose partitions')
    def build(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW d AS SELECT * FROM '+u.parq(files));c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq([bound['s0']]))
            keys=['game_id','recipient_id','opponent_id','received','y','reached','archive_start_ms','anchor_ms']
            u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM d JOIN s USING(row_id)').fetchone()==(2682329,2682329),'Act-and-result row join failed')
            u.require(c.execute('SELECT count(*) FROM d JOIN s USING(row_id) WHERE '+' OR '.join('d.'+k+' IS DISTINCT FROM s.'+k for k in keys)).fetchone()[0]==0,'Act-and-result frozen outcome or identity differs')
            columns=['row_id','giver_cost','recipient_benefit','giver_rd','recipient_rd','board_cp','ply','giver_clock','recipient_clock','chooser_color']
            r.io.copy(c,'SELECT '+','.join(columns)+' FROM d ORDER BY row_id',tmp/'features.parquet')
            return dict(rows=2682329,identity_outcome_bridge=True,source_key=a['parent_key'])
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,files+[bound['s0']])[0]/'features.parquet'
