"""Adapters leave the published model/design/estimation functions unchanged."""
from util import *
import sys,ast,inspect,concurrent.futures as cf,multiprocessing as mp

def load_stage(stage):
    require(stage in ('r11','merit'),'Unknown stage')
    path=ROOT/'vendor'/stage
    # Every production stage has its own interpreter, including spawned workers.
    if 'common' in sys.modules:
        require(Path(sys.modules['common'].__file__).resolve().parent==path,'Mixed legacy module namespaces')
    sys.path.insert(0,str(path))
    import common,design,prepare,estimate,report
    return common,design,prepare,estimate,report

def project(t):
    common,design,prepare,estimate,report=load_stage(t['stage'])
    r=t['record'];require(signature(r['path'])==r['signature'],'Source changed since launch authentication')
    # The launch hashes each source once. Guard the same inode/size/times here;
    # do not scan the identical full-width file again just to calculate its hash.
    original=prepare.sha
    def checked_sha(p):
        if Path(p).resolve()==Path(r['path']).resolve():
            require(signature(p)==r['signature'],'Authenticated source changed');return r['sha256']
        return original(p)
    prepare.sha=checked_sha
    try:
        task=dict(source=r['path'],output=t['output'],month=r['month'],rows=r['rows'],expected_sha256=r['sha256'],key=t['key'],memory=t['memory'],memory_gb=t['memory'])
        result=prepare.project_month(task)
        require(signature(r['path'])==r['signature'],'Source changed during projection')
        return result
    finally:prepare.sha=original

def bucket(t):
    common,design,prepare,estimate,report=load_stage(t['stage'])
    return estimate.task(t) if t['stage']=='r11' else estimate.run_bucket(t)

def mapped(fn,tasks,workers,label):
    started=time.monotonic();result=[];durations=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        futures=[pool.submit(fn,t) for t in tasks]
        try:
            for f in cf.as_completed(futures):
                r=f.result();result.append(r)
                if r.get('seconds',0)>0:durations.append(r['seconds'])
                n=len(result)
                # Print every completion for 24 monthly files, every eighth chooser shard.
                if len(tasks)<=24 or n%8==0 or n==len(tasks):
                    estimate=sum(durations)/len(durations)*(len(tasks)-n)/workers/60 if durations else 0
                    log(f'{label}: {n}/{len(tasks)} complete; approximate stage ETA {estimate:.1f} min')
        except BaseException:
            for f in futures:f.cancel()
            raise
    return result

def bind_r11(prepare,design,census):
    # The historical producer hard-coded the original census. Rebind exactly
    # these constants to independently recomputed new-input counts; no disabled gate.
    bindings={41534331:census['opportunities'],570091:census['grants'],3224173:census['choosers'],15207423:census['competitive'],419463:census['competitive_grants']}
    class Bind(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is int and node.value in bindings:return ast.copy_location(ast.Constant(bindings[node.value]),node)
            return node
    for name in ('raw_summaries','partition'):
        tree=Bind().visit(ast.parse(inspect.getsource(getattr(prepare,name))));ast.fix_missing_locations(tree)
        exec(compile(tree,str(ROOT/'vendor/r11/prepare.py'),'exec'),prepare.__dict__)
    expected=[dict(position=design.POSITIONS[r['position_code']],stage=design.STAGES[r['stage_code']],opportunities=r['opportunities'],grants=r['grants']) for r in census['board_stage_cells']]
    old=prepare.load
    prepare.load=lambda p:expected if Path(p).name=='EXPECTED_BOARD_STAGE.json' else old(p)
    return bindings

def run_stage(config,stage):
    import numpy as np,pyarrow.parquet as pq
    common,design,prepare,estimate,report=load_stage(stage)
    out=Path(config['run'])/'PRIVATE/stages'/stage;(out/'report').mkdir(parents=True,exist_ok=True)
    auth=config['auth'];counts=config['census'];key=digest([config['id'],stage])
    records=auth['records'];paths=[out/'PRIVATE/projected'/f'{r["month"]}.parquet' for r in records]
    task=[dict(stage=stage,record=r,output=str(p),key=key,memory=min(1.5,(config['memory_gb']-1)/4)) for r,p in zip(records,paths)]
    results=mapped(project,task,min(4,config['workers']),'Project '+stage)
    require(sum(r['n'] for r in results)==counts['opportunities'] and sum(r['grants'] for r in results)==counts['grants'],'Projection count mismatch')
    table(out/'report/monthly_validation.csv',results)
    if stage=='r11':save(out/'report/CENSUS_BINDINGS.json',bind_r11(prepare,design,counts))
    with heartbeat(stage+': input summaries and chooser partitions'):
        validation=prepare.raw_summaries(paths,out,min(4,config['workers']),config['memory_gb'])
        require(validation['choosers']==counts['choosers'],'Projected chooser count differs')
        validation['author_accounts_retained']=False
        part=prepare.partition(paths,out,config['shards'],min(4,config['workers']),config['memory_gb'],key)
    by={}
    for r in part['files']:
        b=int(Path(r['relative']).parts[0].split('=')[1]);by.setdefault(b,[]).append(out/'PRIVATE/by_chooser'/r['relative'])
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in files) for files in by.values())
    if stage=='r11':
        _,names,indices=design.design(design.dummy());_,mnames=design.moments_design(design.dummy())
        per=(largest*8*(4*len(names)+4*len(mnames)+40)+200_000_000)/2**30
        specs=None
    else:
        specs=design.specifications();per=(largest*8*(4*80+70)+200_000_000)/2**30
    require(per<config['memory_gb']-.75,'Largest chooser shard exceeds memory; increase --shards')
    workers=max(1,min(config['workers'],int((config['memory_gb']-.75)/max(.5,per))))
    save(out/'report/RESOURCE_PLAN.json',dict(workers=workers,estimated_worker_gib=per,largest_partition_rows=largest,memory_budget_gb=config['memory_gb'],shards=len(by),single_numerical_thread=True))
    log(f'{stage}: {workers} worker processes, estimated {per:.2f} GiB each; {len(by)} chooser-complete partitions')
    fits=None;fitkey=None
    for phase in (1,2):
        task=[];moment_paths=[]
        for b,files in sorted(by.items()):
            p=out/f'PRIVATE/moments/phase{phase}_{b:04d}.npz';moment_paths.append(p)
            t=dict(stage=stage,bucket=b,files=list(map(str,files)),out=str(p),key=digest([key,phase,b,fitkey]),phase=phase)
            if stage=='r11':
                if phase==2:t['fit']=fits
            else:
                t['specs']=specs
                if phase==2:t['fits']=fits
            task.append(t)
        mapped(bucket,task,workers,stage+': '+('regression moments' if phase==1 else 'cluster covariance'))
        if phase==1:
            if stage=='r11':
                fits=estimate.fit_first(moment_paths,names,indices,mnames)
                require((fits['n'],fits['g'])==(counts['opportunities'],counts['choosers']),'Fitted main census differs')
                fitkey=digest({k:v['beta'].tolist() for k,v in fits['fits'].items()})
            else:
                fits=estimate.aggregate_first(moment_paths,specs)
                require(fits[0]['n']==counts['competitive_late'],'Continuous primary sample count differs')
                fitkey=digest([f['beta'].tolist() for f in fits])
    with heartbeat(stage+': exporting contrasts and covariance'):
        if stage=='r11':
            covs=report.write_report(out,fits,estimate.combine(moment_paths))
            rows=[]
            for col in design.COLS:
                m=report.Model(col,fits,covs[col])
                for k,label in enumerate(design.POSITIONS):rows.append(m.row('A_adjusted_rate',label,m.rate('position',k),group='position',unit='percent'))
                for hi,lo in [(1,0),(2,1),(3,2),(4,3),(4,0)]:
                    rows.append(m.row('A_adjusted_difference',design.POSITIONS[hi]+' minus '+design.POSITIONS[lo],m.rate('position',hi)-m.rate('position',lo),group='position'))
            allrows=rows+report.make_rows(fits,covs)[0]
            table(out/'report/tab_main.csv',[r for r in allrows if r['column']=='column1' and r['panel'] in ('A_adjusted_rate','A_adjusted_difference','B_region','B_rebound','B_baseline','B_ratio','C_gap','C_difference')])
            table(out/'report/tab_app_main_spec.csv',allrows)
            spec=read(out/'report/SPECIFICATION.json');spec.update(sample=f"{counts['opportunities']} material-restricted author-excluded opportunities",author_accounts='excluded in both roles',all_games='Not rerun; factual chronology unchanged',position_interpretation='tab_main.csv uses standardized rates and joint-covariance adjacent differences. Raw beta diagnostics remain separately labeled.')
            save(out/'report/SPECIFICATION.json',spec)
            # Do not export legacy prose claiming the old sample or retained authors.
            for p in (out/'report').glob('*.md'):p.unlink()
            for p in (out/'report').glob('*.tex'):p.unlink()
        else:
            # The handoff asks for figure data for the author's re-export.
            report.plot=lambda *a:None
            meats=estimate.aggregate_meat(moment_paths,specs)
            report.write_report(out,specs,fits,meats,validation)
            extra=[]
            for j,(s,f,M) in enumerate(zip(specs,fits,meats)):
                if s['name'] not in ('primary_competitive_late','full_range_late'):continue
                V=estimate.coefficient_cov(f,M)
                for hi,lo in ([(300,100),(500,300)] if s['name']=='primary_competitive_late' else [(-100,-300),(300,100)]):
                    delta=report.contrast_vector(s,f,dict(cp=lo),dict(cp=hi))
                    extra.append(dict(model=s['name'],contrast=f'{hi} minus {lo}',N=f['n'],choosers=f['g'],**report.comparison(delta,f,V)))
            table(out/'report/additional_covariance_contrasts.csv',extra)
            import pandas as pd
            selected=[]
            for name,kind in [('adjusted_profiles','profile'),('planned_contrasts','contrast'),('additional_covariance_contrasts','additional_contrast')]:
                d=pd.read_csv(out/'report'/f'{name}.csv');d['result_kind']=kind;selected.append(d)
            table(out/'report/tab_app_merit_continuous.csv',pd.concat(selected,ignore_index=True))
            # Every coefficient name, matrix and model-specific sample is exported.
    save(out/'report/CENSUS.json',validation)
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);p.add_argument('--stage',choices=['r11','merit'],required=True);a=p.parse_args()
    run_stage(read(a.config),a.stage)
