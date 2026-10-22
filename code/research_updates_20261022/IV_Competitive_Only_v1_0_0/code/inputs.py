from common import *
import shutil

def authenticate(project,workers):
    base=project/EXPANDED_REL
    if not (base/'analysis/spaced90.parquet').is_file():
        raise RuntimeError('PRIVATE_PRODUCTION_INPUTS_NOT_AVAILABLE: '+str(base/'analysis/spaced90.parquet'))
    if io.cfgsha(io.load(base/'config.json'))!=EXPANDED_CONF:raise RuntimeError('Headline configuration changed')
    io.checked(base/'analysis/spaced90.parquet',SPACED_SHA,295180899)
    if pq.ParquetFile(base/'analysis/spaced90.parquet').metadata.num_rows!=2682330:raise RuntimeError('Headline N changed')
    authority=io.load(ROOT/'evidence/authority.json')
    io.checked(base/'report/_DONE.json',authority['expanded_receipt_sha256'])
    if io.complete(base/'comparison',EXPANDED_CONF) is None:raise RuntimeError('Original comparison incomplete')
    comparison=base/'comparison/comparison.parquet'
    if pq.ParquetFile(comparison).metadata.num_rows!=1661563:raise RuntimeError('Original comparison frame changed')
    prior=io.load(ROOT/'evidence/prior_authority.json')
    linepath=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'lineage_PRIVATE.json'
    io.checked(linepath,prior['comparison_lineage_sha256']);line=io.load(linepath)
    parts=[]
    for s,entries in enumerate(line['projections']):
        for r in entries:parts.append(dict(r,path=str(relocate(project,r['path'])),shard=s))
    if len(parts)!=384 or sum(r['rows'] for r in parts)!=47587020 or {(r['month'],r['shard']) for r in parts}!={(m,s) for m in MONTHS for s in range(16)}:
        raise RuntimeError('Historical projection lineage changed')
    with cf.ThreadPoolExecutor(max_workers=workers) as pool,io.heartbeat('Authenticating saved historical Parquets'):
        list(pool.map(lambda r:io.checked(r['path'],r['sha256'],r['bytes']),parts))
    pilot=project/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/prior['iv_run']
    success=io.load(pilot/'_SUCCESS.json')
    if success['config_sha256']!=prior['iv_config_sha256'] or success['report_zip_sha256']!=prior['iv_report_sha256']:raise RuntimeError('Historical model authority changed')
    deltas=[]
    for m in MONTHS:
        d=pilot/'projection'/('month='+m);r=io.load(d/'_COMPLETE.json')
        if r['config_sha256']!=prior['iv_config_sha256']:raise RuntimeError('Reference configuration changed')
        e=next(v for v in r['files'] if v['path']=='reference_deltas.npz');p=d/e['path']
        io.checked(p,e['sha256'],e['bytes']);deltas.append(str(p))
    lineage=[{k:r[k] for k in ('month','shard','sha256','rows')} for r in parts]
    indexdef=dict(kind='monthly_lag7_score_sufficient_statistics_v1',source=dict(parts=lineage,cutoffs=[int(v)-7*DAY for v in STARTS]),
                  code={n:io.sha(ROOT/'evidence/index_source'/n) for n in ('performance_histories.py','performance_cache.py')})
    idxconf=io.cfgsha(indexdef)
    existing=project/'derived/replication/run2_feature_cache_v1_PRIVATE/score_index'/idxconf
    return dict(spaced=str(base/'analysis/spaced90.parquet'),comparison=str(comparison),parts=parts,deltas=deltas,
        index_conf=idxconf,index_root=str(existing),lineage_sha=prior['comparison_lineage_sha256'],
        comparison_sha=io.sha(comparison),spaced_sha=SPACED_SHA)

def reproduce(d,name,expected):
    family='iv' if name=='main90_pooled' else 'ordinary'
    r=oldstats.estimate(d,dict(name=name,family=family,rich=True,repeat=False,fe=False,balance=False))
    for actual in r['estimates']:
        target=next(x for x in expected if x['specification']==name and x['estimator']==actual['estimator'] and x.get('outcome')==actual.get('outcome'))
        if actual['n']!=target['n'] or actual['row_set_sha256']!=target['row_set_sha256']:raise RuntimeError('Frozen row set changed: '+name)
        for k in ('coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp','partial_first_stage_R2'):
            if target.get(k) is not None and not np.isclose(actual.get(k,np.nan),target[k],rtol=2e-7,atol=2e-9):raise RuntimeError('Frozen result not reproduced: '+name+' '+k)
        if 'AR95_intervals_pp' in target:
            if len(actual.get('AR95_intervals_pp',[]))!=len(target['AR95_intervals_pp']):raise RuntimeError('Frozen AR topology changed')
            for x,y in zip(actual['AR95_intervals_pp'],target['AR95_intervals_pp']):
                for a,b in zip(x,y):
                    if isinstance(b,str):
                        if a!=b:raise RuntimeError('Frozen AR endpoint changed')
                    elif not np.isclose(a,b,rtol=2e-7,atol=2e-9):raise RuntimeError('Frozen AR endpoint changed')
    return r

def prepare(source,root,conf,expected=None):
    def build(tmp):
        names=pq.ParquetFile(source['spaced']).schema_arrow.names
        cols=MODEL_COLS+['received','speed']
        if not set(cols)<=set(names):raise RuntimeError('Required headline fields unavailable: '+str(set(cols)-set(names)))
        d=arrays(io.read(source['spaced'],cols));logic.row_digest(d['row_id'])
        for k in ('received','y','reached'):
            if not np.isin(d[k],[0,1]).all():raise RuntimeError('Invalid binary headline field')
        if np.any(d['y']&~d['reached']):raise RuntimeError('Kindness without a later choice')
        c=arrays(io.read(source['comparison']));keep,_=logic.entry_mask(c,90)
        keep &= c['ordinary_narrow'].astype(bool)&c['complete90'].astype(bool)
        p={k:c[k][keep] for k in MODEL_COLS};del c
        if expected is not None:
            rv=reproduce(d,'main90_pooled',expected);rp=reproduce(p,'ordinary90_placebo',expected)
            io.js(tmp/'reproduction.json',dict(status='ORIGINAL_IV_AND_PLACEBO_REPRODUCED',IV=rv,placebo=rp))
        else:io.js(tmp/'reproduction.json',dict(status='SYNTHETIC_FIXTURE_NOT_PRODUCTION'))
        io.table(tmp/'iv.parquet',pa.table(d));io.table(tmp/'placebo.parquet',pa.table(p))
        query={k:np.r_[d[k],p[k]] for k in ['row_id','recipient_id','opponent_id','archive_start_ms','month_code']+SCORE_COLS}
        query['qid']=np.arange(len(d['row_id'])+len(p['row_id']),dtype=np.int64)
        query['cohort']=np.r_[np.zeros(len(d['row_id']),np.int8),np.ones(len(p['row_id']),np.int8)]
        q=pa.table(query);shards=num.user_hash(query['opponent_id'])%np.uint64(16)
        for s in range(16):io.table(tmp/f'query_{s:02}.parquet',q.filter(pa.array(shards==s)))
        return dict(iv_rows=len(d['row_id']),placebo_rows=len(p['row_id']))
    return stable(root,conf,build,[source['spaced'],source['comparison']])

def reference(source,root,conf):
    def build(tmp):
        n=s=None
        for p in source['deltas']:
            with np.load(p,allow_pickle=False) as z:
                if n is None:n=z['n'].copy();s=z['s'].copy()
                else:n+=z['n'];s+=z['s']
        if n.shape!=(2,25,4,4,500):raise RuntimeError('Frozen reference shape changed')
        np.save(tmp/'original.npy',num.expanding_reference(n[:,:24],s[:,:24]),allow_pickle=False)
        return dict(method='algebraic reconstruction of original frozen full-state reference',authors_removed=False)
    return stable(root,conf,build,source['deltas'])

def build_index(job):
    existing=Path(job['existing'])
    if (existing/'_DONE.json').is_file():
        r=io.complete(existing,job['index_conf'])
        if r is None:raise RuntimeError('Incomplete reusable index')
        return dict(path=str(existing),reused=True)
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            cuts=[int(v)-7*DAY for v in STARTS]
            bucket='CASE '+' '.join(f'WHEN t<{v} THEN {k}' for k,v in enumerate(cuts))+' ELSE 24 END'
            source=io.parq(job['parts'])
            bad=c.execute('SELECT count(*) FROM '+source+' WHERE arm AND (cell IS NULL OR cell<0 OR cell>=500)').fetchone()[0]
            if bad:raise RuntimeError('Unknown board state in eligible historical decisions')
            c.execute('CREATE TEMP TABLE aggregated AS SELECT j,i,cell,'+bucket+' AS bucket,count(*)::BIGINT n,sum(y::BIGINT)::BIGINT wins FROM '+source+f' WHERE arm AND t<{cuts[-1]} GROUP BY j,i,cell,bucket')
            c.execute('CREATE TEMP TABLE people AS SELECT j,row_number() OVER(ORDER BY j)-1 AS j_index FROM (SELECT DISTINCT j FROM aggregated)')
            c.execute('CREATE TEMP TABLE pairs AS SELECT j,i,j_index,row_number() OVER(ORDER BY j,i)-1 AS pair_index FROM (SELECT DISTINCT j,i FROM aggregated) JOIN people USING(j)')
            io.copy(c,'SELECT j FROM people ORDER BY j_index',tmp/'people.parquet')
            io.copy(c,'SELECT j,i,j_index FROM pairs ORDER BY pair_index',tmp/'pairs.parquet')
            n=io.copy(c,'SELECT bucket,pair_index,j_index,cell,n,wins FROM aggregated JOIN pairs USING(j,i) ORDER BY bucket,pair_index,cell',tmp/'events.parquet')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return dict(aggregated_rows=n,author_included=True)
    p,_=stable(job['output'],job['index_conf'],build,job['parts'])
    return dict(path=str(p),reused=False)

class SplitIndex:
    def __init__(self,path):
        path=Path(path);self.h=arrays(io.read(path/'events.parquet'))
        self.people=io.arr(io.read(path/'people.parquet'),'j');self.pairs=arrays(io.read(path/'pairs.parquet'))
        self.keys=np.empty(len(self.pairs['j']),dtype=[('v0','<i8'),('v1','<i8')]);self.keys['v0']=self.pairs['j'];self.keys['v1']=self.pairs['i']
        self.folds=(num.user_hash(self.people)%np.uint64(4)).astype(int)
        if np.any((self.h['cell']<0)|(self.h['cell']>=500)):raise RuntimeError('Invalid historical state cell')
        if np.any(np.diff(self.h['bucket'])<0):raise RuntimeError('Unsorted score index')
    def score(self,qj,qi,month,model,part):
        stop=np.searchsorted(self.h['bucket'],month,side='right');h={k:v[:stop] for k,v in self.h.items()}
        band=h['cell']//100
        mask={'all':np.ones(stop,bool),'comp':band>=2,'non':band<2,'worse':band==0}[part]
        j=h['j_index'][mask];p=h['pair_index'][mask];n=h['n'][mask];wins=h['wins'][mask];cell=h['cell'][mask]
        njp=len(self.people);npp=len(self.keys)
        jn=np.bincount(j,weights=n,minlength=njp).astype(np.int64);pn=np.bincount(p,weights=n,minlength=npp).astype(np.int64)
        js=np.bincount(j,weights=wins,minlength=njp);ps=np.bincount(p,weights=wins,minlength=npp)
        qp=np.empty(len(qj),dtype=self.keys.dtype);qp['v0']=qj;qp['v1']=qi
        ij=num.lookup(self.people,qj);ip=num.lookup(self.keys,qp)
        count=num.take_zero(jn,ij)-num.take_zero(pn,ip);grants=num.take_zero(js,ij)-num.take_zero(ps,ip)
        breadth=np.bincount(self.pairs['j_index'],weights=pn>0,minlength=njp).astype(np.int64)
        breadth=num.take_zero(breadth,ij)-(num.take_zero(pn,ip)>0)
        expected=np.full(len(qj),np.nan);raw=expected.copy();good=count>0;raw[good]=grants[good]/count[good]
        qrf=(num.user_hash(qi)%np.uint64(4)).astype(int);qjf=(num.user_hash(qj)%np.uint64(4)).astype(int)
        for rf in range(4):
            use=(qrf==rf)&good
            if not use.any():continue
            valid=np.isfinite(model[:,rf,:]).all(axis=1)
            v=np.where(valid[self.folds[j]],model[self.folds[j],rf,cell],0.)*n
            jm=np.bincount(j,weights=v,minlength=njp);pm=np.bincount(p,weights=v,minlength=npp)
            use &= valid[qjf];expected[use]=(num.take_zero(jm,ij)[use]-num.take_zero(pm,ip)[use])/count[use]
        if np.any(count<0)|np.any(grants<0)|np.any(grants>count):raise RuntimeError('Invalid pair-excluded history')
        return dict(n=count,grants=grants.astype(np.int64),expected=expected,counterparts=breadth,z=raw-expected)

def score_job(job):
    def build(tmp):
        q=arrays(io.read(job['query']));idx=SplitIndex(job['index'])
        model=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        n=len(q['qid']);out={k:q[k] for k in ('qid','row_id','cohort','opponent_id','recipient_id','month_code')}
        for k in SPLIT_COLS:out[k]=np.zeros(n,np.int64) if k.endswith(('_n','_grants','_counterparts')) else np.full(n,np.nan)
        maximum=0.;identity=0.
        for m in np.unique(q['month_code']):
            ix=np.flatnonzero(q['month_code']==m);args=(q['opponent_id'][ix],q['recipient_id'][ix],int(m),model[0,int(m)])
            allsc=idx.score(*args,'all');comp=idx.score(*args,'comp');non=idx.score(*args,'non');worse=idx.score(*args,'worse')
            for k,old in [('n','n_7d'),('z','adjusted_7d'),('expected','expected_7d'),('counterparts','counterparts_7d')]:
                if not np.allclose(allsc[k],q[old][ix],rtol=1e-10,atol=2e-11,equal_nan=True):raise RuntimeError('Frozen pooled history not reproduced: '+old)
                valid=np.isfinite(allsc[k])&np.isfinite(q[old][ix])
                if valid.any():maximum=max(maximum,float(abs(allsc[k][valid]-q[old][ix][valid]).max()))
            if not np.array_equal(allsc['n'],comp['n']+non['n']) or not np.array_equal(allsc['grants'],comp['grants']+non['grants']):raise RuntimeError('History partition fails')
            reconstructed=np.nan_to_num(comp['z'])*comp['n']+np.nan_to_num(non['z'])*non['n']
            if not np.allclose(allsc['z']*allsc['n'],reconstructed,atol=1e-8,rtol=1e-10):raise RuntimeError('Residual-sum partition fails')
            if len(ix):identity=max(identity,float(abs(allsc['z']*allsc['n']-reconstructed).max()))
            for tag,v in [('comp',comp),('non',non)]:
                for k,a in v.items():out[tag+'_'+k][ix]=a
            out['non_clearly_worse_n'][ix]=worse['n']
        out['comp_supported5']=(out['comp_n']>=5)&np.isfinite(out['comp_z'])
        out['comp_supported3']=(out['comp_n']>=3)&np.isfinite(out['comp_z'])
        out['non_supported5']=(out['non_n']>=5)&np.isfinite(out['non_z'])
        io.table(tmp/'scores.parquet',pa.table(out))
        return dict(rows=n,pooled_max_absolute_error=maximum,residual_sum_identity_max_absolute_error=identity)
    return stable(job['output'],job['conf'],build,[job['query'],job['reference']])[1]

def assemble(prepared,scorepaths,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scorepaths))
            if c.execute('SELECT count(*)-count(DISTINCT qid) FROM s').fetchone()[0]:raise RuntimeError('Duplicate score query')
            for tag,cohort in [('iv',0),('placebo',1)]:
                c.execute('CREATE OR REPLACE VIEW d AS SELECT * FROM '+io.parq([prepared/(tag+'.parquet')]))
                sql='SELECT d.*,'+','.join('s.'+k for k in SPLIT_COLS)+f' FROM d JOIN s USING(row_id) WHERE s.cohort={cohort} ORDER BY d.row_id'
                n=io.copy(c,sql,tmp/(tag+'.parquet'))
                if n!=pq.ParquetFile(prepared/(tag+'.parquet')).metadata.num_rows:raise RuntimeError('Score join changes frozen row count')
            # Private CSV is streamed by DuckDB; it is not an analysis input or public report.
            c.execute('COPY (SELECT * FROM s ORDER BY qid) TO '+io.lit(tmp/'01_scores_PRIVATE.csv')+' (HEADER,DELIMITER \',\')')
            io.copy(c,'SELECT * FROM s ORDER BY qid',tmp/'01_scores_PRIVATE.parquet')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return dict(author_included=True,no_rows_reselected=True)
    return stable(root,conf,build,list(scorepaths)+[prepared/'iv.parquet',prepared/'placebo.parquet'])
