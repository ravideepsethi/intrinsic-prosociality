"""R8-3(2): original natural spline, own/opponent clock controls by speed."""
from r8_util import *
import sys,gc,shutil,concurrent.futures,multiprocessing
sys.path.insert(0,str(ROOT/'vendor_merit'))
import common as mc
import prepare as mp
import design as md
import estimate as me
from source import pool_wave1_common as authority
from scipy.stats import norm

SPEED_LABELS=['ultrabullet_bullet','blitz','rapid','classical']
CLOCK_LABELS=['lt10pct','10to25pct','25to50pct','50to100pct','gt100pct','missing']

def clock_codes(clock,base):
    clock=np.asarray(clock,float);base=np.asarray(base,float)
    ok=np.isfinite(clock)&(clock>=0)&np.isfinite(base)&(base>0)
    ratio=np.divide(clock,base,out=np.zeros(len(clock)),where=ok)
    return np.where(~ok,5,np.select([ratio<.1,ratio<.25,ratio<.5,ratio<=1],[0,1,2,3],default=4)).astype(np.int8)

def select(d,s):
    a=md.select(d,s)
    if s['name']!='primary_competitive_late':
        require('author_game' in a,'Author-game bridge absent')
        a=a.loc[~a.author_game.astype(bool)].reset_index(drop=True)
    return a

def design(d,s):
    original=dict(s,controls='base');X,names,p,groups,ng=md.design(d,original)
    speed=np.maximum(d.speed_code.to_numpy(int)-1,0)
    cols=[X]
    if s['controls']=='clock_categories_by_speed':
        base=d.base.to_numpy(float) if 'base' in d else np.ones(len(d))*60
        for role in ('c','d'):
            code=clock_codes(d['clock_'+role],base)
            for g,label in enumerate(SPEED_LABELS):
                for j in (0,1,2,4,5):
                    cols.append(((speed==g)&(code==j)).astype(float)[:,None])
                    names.append('clock_'+role+'_'+CLOCK_LABELS[j]+':'+label)
    elif s['controls']=='clock_log_by_speed':
        for role in ('c','d'):
            clock=d['clock_'+role].to_numpy(float);ok=np.isfinite(clock)&(clock>=0)
            for g,label in enumerate(SPEED_LABELS):
                cols.append((np.log1p(np.where(ok,clock,0))*(speed==g))[:,None])
                cols.append(((~ok)&(speed==g)).astype(float)[:,None])
                names += ['log1p_clock_'+role+':'+label,'missing_clock_'+role+':'+label]
    return np.column_stack(cols),names,p,groups,ng

# The original two-pass estimator is unchanged. Only its deterministic design/selection callbacks differ.
me.design=design;me.select=select

def project(task):
    src=Path(task['source']);folder=Path(task['folder']);out=folder/'projection.parquet'
    key=digest([task['key'],task['month'],task['sha256'],stamp(src)])
    if verify_cached(folder,key):return str(out),load(folder/'census.json')
    require(sha(src)==task['sha256'],'Clock main-panel source SHA changed: '+task['month'])
    folder.mkdir(parents=True,exist_ok=True);c=conn(folder/'spill',task['memory'],1)
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+parq([src]))
        columns=set(pq.ParquetFile(src).schema_arrow.names)
        require({'tc_base_s','chooser_username_norm','disconnected_username_norm'}<=columns,'Clock or author source contract absent')
        require(c.execute('SELECT count(*) FROM src WHERE chooser_username_norm IS NULL OR disconnected_username_norm IS NULL OR chooser_user_id IS NULL').fetchone()[0]==0,'Clock author identity bridge contains missing values')
        sql=mp.projection_sql('src',task['month']).rsplit('FROM ',1)[0]
        sql+=f',tc_base_s::DOUBLE base,NOT ({author_predicate()}) AS author_game FROM src'
        c.execute('CREATE VIEW projected AS '+sql)
        counts=c.execute('''SELECT count(*) n,sum(y)::BIGINT grants,
          count(*) FILTER(WHERE board>=-100 AND ply>10) competitive_late,
          count(*) FILTER(WHERE author_game) author_game_rows,
          count(*) FILTER(WHERE author_game AND board>=-100 AND ply>10) author_game_competitive_late,
          count(*) FILTER(WHERE board>=-100 AND ply>10 AND (speed_code IS NULL OR y IS NULL OR cp IS NULL AND NOT mate)) invalid
          FROM projected''').fetchdf().to_dict('records')[0]
        require(counts['n']==task['rows'] and counts['invalid']==0,'Clock source row/semantics gate failed')
        tmp=out.with_name(out.name+'.partial')
        c.execute(f'COPY (SELECT * FROM projected WHERE board>=-100 AND ply>10) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD)')
        os.replace(tmp,out);save(folder/'census.json',counts)
    finally:c.close()
    certify(folder,key,[src]);return str(out),counts

def partitions(paths,work,key,shards,memory):
    folder=work/'chooser_complete';k=digest([key,shards])
    if verify_cached(folder,k):return load(folder/'partitions.json')
    folder.mkdir(parents=True,exist_ok=True)
    # A partial generation is never reused or mixed with another generation.
    target=folder/'by_chooser';tmp=folder/'by_chooser.partial'
    if tmp.exists():shutil.rmtree(tmp)
    if target.exists():
        # No _DONE receipt exists at this point. This is an uncommitted generated cache, never a certified source.
        shutil.rmtree(target)
    c=conn(folder/'spill',max(2,memory-2),1)
    try:
        with heartbeat('Partition competitive post-ply-10 rows by complete chooser'):
            c.execute(f'''COPY (SELECT *,((chooser%{shards}+{shards})%{shards})::INTEGER bucket FROM {parq(paths)})
              TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 65536)''')
    finally:c.close()
    os.replace(tmp,target)
    inventory=[]
    for d in sorted(target.glob('bucket=*')):
        files=sorted(d.glob('*.parquet'))
        inventory.append(dict(bucket=int(d.name.split('=')[1]),files=[str(p) for p in files],
            rows=sum(pq.ParquetFile(p).metadata.num_rows for p in files)))
    require(sum(r['rows'] for r in inventory)==11590459,'Frozen clock-model baseline rows changed')
    save(folder/'partitions.json',inventory);certify(folder,k,paths);return inventory

def bucket(task):
    no_network();folder=Path(task['folder']);out=folder/'moments.npz'
    k=digest([task['key'],task['phase'],task['bucket'],task['specs']])
    if verify_cached(folder,k):return str(out)
    folder.mkdir(parents=True,exist_ok=True);d=me.read_bucket(task['files']);result={}
    for j,s in enumerate(task['specs']):
        if task['phase']==1:
            m,_,_,_=me.moments(d,s)
            for name,val in m.items():result[f'm{j}_{name}']=val
        else:result[f'm{j}_meat']=me.meat(d,s,task['fits'][j])
    mc.npz(out,**result);certify(folder,k,task['files']);return str(out)

def pool_tasks(fn,tasks,workers,label):
    results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as ex:
        futures={ex.submit(fn,t):t for t in tasks};total=len(tasks)
        with heartbeat(label):
            for i,f in enumerate(concurrent.futures.as_completed(futures),1):
                results.append((futures[f],f.result()))
                if i==1 or i%16==0 or i==total:log(f'{label}: {i}/{total} checkpoints')
    return results

def fit_set(parts,specs,work,key,workers):
    tasks=[]
    for phase in (1,2):
        tasks=[dict(r,key=key,phase=phase,specs=specs,folder=str(work/f'pass{phase}'/str(r['bucket']))) for r in parts]
        if phase==2:
            for t in tasks:t['fits']=fits
        output=pool_tasks(bucket,tasks,workers,'Clocks '+work.name+f' pass {phase}')
        paths=[p for _,p in sorted(output,key=lambda pair:pair[0]['bucket'])]
        if phase==1:fits=me.aggregate_first(paths,specs)
        else:meats=me.aggregate_meat(paths,specs)
    return fits,meats

def comparison(fit,V,delta):
    ok=me.estimable(fit,delta);b=float(delta@fit['beta']) if ok else None
    var=float(delta@V@delta) if ok else None;se=math.sqrt(var) if var is not None and var>0 else None
    return dict(estimate_pp=b,se=se,lo=b-1.959963984540054*se if se else None,
        hi=b+1.959963984540054*se if se else None,p_value=float(2*norm.sf(abs(b/se))) if se else None,
        estimable=bool(ok),variance_supported=se is not None)

def contrasts(specs,fits,meats):
    rows=[]
    for s,f,M in zip(specs,fits,meats):
        V=me.coefficient_cov(f,M)
        for a,b in ((0,100),(100,300),(300,500)):
            delta=np.zeros(len(f['beta']));delta[:f['p']]=(md.counterfocal(s,dict(cp=b),1)-md.counterfocal(s,dict(cp=a),1))[0]
            rows.append(dict(model=s['name'],contrast=f'{b} minus {a}',**comparison(f,V,delta)))
    return rows

def run(a,work,key):
    no_network();report=work/'report';report.mkdir(parents=True,exist_ok=True)
    sample=authority.authenticate_sample(a.project_root/MAIN_REL,verify_hashes=False,hash_workers=1)
    require(sample['fingerprint']=='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30','Main sample fingerprint differs')
    # Projection is limited to two simultaneous one-thread DuckDB scans to protect external-disk I/O and memory.
    tasks=[dict(source=str(r['path']),month=r['month'],rows=r['rows'],sha256=r['expected_sha256'],key=key,
        folder=str(work/'projections'/r['month']),memory=max(.5,min(1.5,a.memory_gb/4))) for r in sample['month_records']]
    outputs=pool_tasks(project,tasks,min(2,a.workers),'Clock source projection')
    outputs.sort(key=lambda pair:pair[0]['month']);paths=[p for _,(p,_) in outputs];census=[r for _,(_,r) in outputs]
    require(sum(r['n'] for r in census)==41534331 and sum(r['competitive_late'] for r in census)==11590459,'Clock baseline census differs')
    table(report,'clock_source_census',census)
    parts=partitions(paths,work,key,256,a.memory_gb)
    # Parent and worker buffers coexist. Size conservatively from the largest complete-chooser partition.
    maxrows=max(r['rows'] for r in parts);per_worker=max(.60,maxrows*88*8*5/2**30+.35)
    workers=max(1,min(a.workers,10,len(parts),int(max(1,a.memory_gb-2)/per_worker)))
    save(report/'resource_policy.json',dict(requested_workers=a.workers,effective_workers=workers,
        largest_partition_rows=maxrows,estimated_GiB_per_worker=per_worker,working_budget_GiB=a.memory_gb,
        partition_count=256,BLAS_threads=1,hard_RSS_cap=False))
    baseline_spec=[dict(name='primary_competitive_late',kind='spline',sample='competitive_late',controls='base')]
    bk=digest([key,'baseline']);gate=work/'baseline_gate'
    if not verify_cached(gate,bk):
        fs,ms=fit_set(parts,baseline_spec,work/'baseline_fits',bk,workers)
        rows=contrasts(baseline_spec,fs,ms);archive=pd.read_csv(ROOT/'evidence/gradient_contrasts.csv')
        expected=archive.loc[archive.model=='primary_competitive_late'].set_index('contrast');checks=[]
        require(fs[0]['n']==11590459,'Clock baseline sample differs')
        for r in rows:
            for field in ('estimate_pp','se'):
                want=float(expected.loc[r['contrast'],field]);got=r[field]
                checks.append(dict(contrast=r['contrast'],field=field,expected=want,observed=got,
                    passed=got is not None and bool(np.isclose(got,want,rtol=3e-6,atol=2e-8))))
        table(gate,'reproduction',checks);require(all(x['passed'] for x in checks),'Clock baseline contrasts or chooser-cluster SEs failed reproduction')
        table(gate,'baseline_contrasts',rows);certify(gate,bk,paths)
    specs=[dict(name=n,kind='spline',sample='competitive_late',controls=c) for n,c in
        [('author_clean_baseline','base'),('author_clean_categories_by_speed','clock_categories_by_speed'),('author_clean_log_by_speed','clock_log_by_speed')]]
    fits,meats=fit_set(parts,specs,work/'author_clean_fits',digest([key,'author_clean']),workers)
    rows=contrasts(specs,fits,meats)
    for name in (s['name'] for s in specs):
        rr=[r for r in rows if r['model']==name];order=sorted([r for r in rr if r['p_value'] is not None],key=lambda r:r['p_value']);maximum=0.
        for i,r in enumerate(order):maximum=max(maximum,r['p_value']*(len(order)-i));r['Holm_p_three_contrasts']=min(1,maximum)
    table(report,'clock_gradient_contrasts',rows)
    terms=[];flows=[];matrices={}
    for s,f,M in zip(specs,fits,meats):
        V=me.coefficient_cov(f,M);k=len(f['beta'])
        matrices[s['name']+'__beta']=f['beta'];matrices[s['name']+'__covariance']=V
        flows.append(dict(model=s['name'],n=f['n'],choosers=f['g'],grants_rate_pct=f['mean_y'],rank=f['rank'],columns=k,
            singletons_retained=f['singletons'],never_grant_choosers_retained=f['never'],author_clean=True))
        for j,n in enumerate(f['names']):terms.append(dict(model=s['name'],term=n,**comparison(f,V,np.eye(k)[j])))
    require(all(f['n']==fits[0]['n'] for f in fits),'Missing clock values changed the estimation row set')
    table(report,'clock_coefficients',terms);table(report,'clock_models',flows);mc.npz(report/'clock_covariances.npz',**matrices)
    save(report/'clock_model_definitions.json',dict(specifications=specs,speed_groups=SPEED_LABELS,
        categorical_intervals=['[0,.10)','[.10,.25)','[.25,.50)','[.50,1.00] reference','(1.00,infinity)','missing'],
        ratio='last-observed own/opponent clock seconds divided by initial tc_base_s; increment time can produce ratio >1',
        missing='Negative/nonfinite clock or nonpositive/nonfinite initial base => missing category; absolute log-clock model requires only an observed nonnegative clock.',
        fixed_effects='chooser + original calendar-month, five speed codes, and stage controls',
        evaluation='raw nonmate cp; natural cubic boundary knots -100,600 and interior 0,100,300; finite >=600 and positive mate separate',
        inference='Chooser-cluster CR1 scores span all 24 months. Pointwise normal intervals. Conditional association; clocks are last observed readings, not exact disconnection-time clocks.'))
    save(report/'COMPLETION.json',dict(status='R8_CLOCK_CURRENT_DATA_COMPLETE',author_clean=True,
        baseline_reproduction_passed=True,network_requests=0,stockfish_searches=0,
        author_game_rows_removed=sum(r['author_game_rows'] for r in census),
        author_competitive_late_rows_removed=sum(r['author_game_competitive_late'] for r in census)))
    certify(work,key,[sample['success_path']]+[r['path'] for r in sample['month_records']])

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--key',required=True);p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--workers',type=int,default=10)
    a=p.parse_args();run(a,a.work,a.key)
