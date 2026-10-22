#!/usr/bin/env python3
"""Read-only upstream binding, resumable offline audit, aggregate-only exports."""
from pathlib import Path
import argparse, concurrent.futures, csv, fcntl, hashlib, json, os, shutil, sys
import threading, time, traceback, zipfile
from datetime import datetime, timezone
from audit_core import (require, load, save, sha, connect, project_frames, build_accounts,
                        tabulate, parq, pq, duckdb)
PACKAGE=Path(__file__).resolve().parents[1]

def digest_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def utc(): return datetime.now(timezone.utc).isoformat()

def checked(path,digest,size=None):
    path=Path(path)
    require(path.is_file(),'Required input absent: '+str(path))
    require(size is None or path.stat().st_size==int(size),'Input size changed: '+str(path))
    require(sha(path)==digest,'Input SHA256 changed: '+str(path))
    return path

def relocate(path,project):
    p=Path(path).expanduser()
    if p.is_absolute():
        if p.is_relative_to(project):return p
        parts=p.parts
        require('lichess_kindness' in parts,'Cannot relocate path outside named project: '+str(p))
        return project.joinpath(*parts[parts.index('lichess_kindness')+1:])
    return project/p

def package_check():
    p=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        digest,name=line.split('  ',1);q=(PACKAGE/name).resolve()
        require(q.is_relative_to(PACKAGE),'Unsafe package path')
        checked(q,digest)
    return sha(p)

class Binding:
    def __init__(self,project,workers):
        self.project=project;self.records={};self.workers=min(workers,2)
    def add(self,role,path,digest,size=None):
        path=Path(path).resolve()
        require(path.is_relative_to(self.project),'Input is outside supplied project: '+role)
        require(path.is_file(),'Required input absent: '+str(path))
        size=path.stat().st_size if size is None else int(size)
        require(role not in self.records,'Duplicate input role')
        self.records[role]=dict(path=str(path),sha256=digest,bytes=size)
        return path
    def stage(self,role,path,conf=None):
        path=Path(path);receipt=path.parent/'_DONE.json';d=load(receipt)
        require(conf is None or d['config_sha256']==conf,'Wrong source stage configuration: '+role)
        recs=[r for r in d['files'] if r['path']==path.name]
        require(len(recs)==1,'Missing/ambiguous source stage receipt: '+role)
        r=recs[0];self.add(role+'_receipt',receipt,sha(receipt))
        return self.add(role,path,r['sha256'],r['bytes'])
    def verify(self):
        records=list(self.records.items());total=sum(r['bytes'] for _,r in records);done=0;start=time.monotonic()
        print(f'Authenticating {len(records)} local inputs ({total/2**30:.2f} GiB); two concurrent hash readers.',flush=True)
        def worker(item):
            role,r=item;checked(r['path'],r['sha256'],r['bytes']);return r['bytes']
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            for n,size in enumerate(pool.map(worker,records),1):
                done+=size
                if n%32==0 or n==len(records):
                    elapsed=time.monotonic()-start;eta=elapsed*(total-done)/done if done else 0
                    print(f'Input hashes {n}/{len(records)}; {done/2**30:.2f}/{total/2**30:.2f} GiB; hash ETA {eta/60:.1f} min',flush=True)
        return self.records

def bind(project,r9,r9b,workers,authority):
    b=Binding(project,workers)
    for name,root in [('R9',r9),('R9b',r9b)]:
        auth=authority[name]
        require(digest_json(load(root/'config.json'))==auth['config_sha256'],name+' configuration differs from reviewed run')
        b.add(name+'_config',root/'config.json',sha(root/'config.json'))
        b.add(name+'_report_manifest',root/'report/REPORT_MANIFEST.json',auth['report_manifest_sha256'])
        for r in auth['report_files']:
            b.add(name+'_report_'+r['path'],root/'report'/r['path'],r['sha256'],r['bytes'])
        d=load(root/'report/summary.json')
        require(d['status']==auth['status'] and d['progress_percent']==100,name+' is not the reviewed complete report')
    r=load(r9/'PREPARED_INPUTS_PRIVATE.json');s=load(r9b/'PREPARED_INPUTS_PRIVATE.json')
    b.add('R9_prepared_binding',r9/'PREPARED_INPUTS_PRIVATE.json',sha(r9/'PREPARED_INPUTS_PRIVATE.json'))
    b.add('R9b_prepared_binding',r9b/'PREPARED_INPUTS_PRIVATE.json',sha(r9b/'PREPARED_INPUTS_PRIVATE.json'))
    inputs={}
    for name in ['S0','F','O']:
        inputs[name]=b.stage(name,relocate(r[name],project),None if name=='S0' else authority['R9']['config_sha256'])
        score=r9/('ordinary_scores/scores.parquet' if name=='O' else 'scores_combined/'+name+'.parquet')
        inputs[name+'_scores']=b.stage(name+'_scores',score,authority['R9']['config_sha256'])
    for role,key in [('expanded','source'),('expanded_scores','scores')]:
        inputs[role]=b.stage(role,relocate(s[key],project),authority['R9b']['config_sha256'])
    a=authority['identity'];identity=project/a['root_rel'];check=identity/'report/dictionary_check.json'
    checked(check,a['check_sha256']);b.add('dictionary_check',check,a['check_sha256'])
    d=load(check);inputs['dictionary_column']=d['selected_explicit_ID_column']
    receipt=identity/'_COMPLETE.json';rr=load(receipt)
    require(rr['config_sha256']==a['config_sha256'],'Identity receipt configuration changed')
    b.add('identity_receipt',receipt,sha(receipt))
    records=[r for r in rr['files'] if r['path']=='dictionary_binding_PRIVATE.json']
    require(len(records)==1,'Identity binding receipt missing/ambiguous')
    p=checked(identity/'dictionary_binding_PRIVATE.json',records[0]['sha256'],records[0]['bytes'])
    b.add('dictionary_binding',p,records[0]['sha256'],records[0]['bytes'])
    dictionary=[];dictroot=(project/a['dictionary_rel']).resolve()
    for rec in load(p)['files']:
        path=relocate(rec['path'],project).resolve()
        if path.suffix=='.parquet' and path.is_relative_to(dictroot):
            dictionary.append(b.add('dictionary_'+str(len(dictionary)).zfill(4),path,rec['sha256'],rec['bytes']))
    require(dictionary and len(set(dictionary))==len(dictionary),'No unique verified dictionary shards')
    require(sum(pq.ParquetFile(p).metadata.num_rows for p in dictionary)==int(d['total_global_users']),'Global dictionary row count changed')
    inputs['dictionary']=dictionary
    a=authority['profiles'];plan=project/a['plan_rel']
    checked(plan/'plan_file_hashes.tsv',a['plan_manifest_sha256'])
    b.add('plan_success',plan/'_SUCCESS.json',a['plan_success_sha256'])
    b.add('plan_manifest',plan/'plan_file_hashes.tsv',a['plan_manifest_sha256'])
    with (plan/'plan_file_hashes.tsv').open(newline='') as f:manifest=list(csv.DictReader(f,delimiter='\t'))
    for role,name in [('chooser','chooser_summary_private.parquet'),('acquisition','acquisition_users_private.parquet'),('cell_diagnostics','matching_cell_diagnostics.tsv'),('plan_summary','plan_summary.json')]:
        matches=[r for r in manifest if r['path']==name]
        require(len(matches)==1,'Original plan manifest missing/ambiguous member: '+name)
        r=matches[0];inputs[role]=b.add(role,plan/name,r['sha256'],r['bytes'])
    inputs['snapshot']=b.add('snapshot',project/a['snapshot_rel'],a['snapshot_sha256'])
    records=b.verify()
    # Source pointers have now been authenticated; only fixed reviewed 75% frames are used.
    require(load(r9/'report/summary.json')['comparison_frame']['phase_percent']==75,'Expected frozen Phase 75 comparison frames')
    return inputs,records

def row_digest(c,path,where='TRUE'):
    # The existing reports use sorted little-endian int64 row-ID bytes.
    h=hashlib.sha256()
    reader=c.execute('SELECT row_id::BIGINT row_id FROM '+parq(path)+' WHERE '+where+' ORDER BY row_id').fetch_record_batch(131072)
    for batch in reader:
        values=batch.column(0).to_numpy(zero_copy_only=False)
        h.update(values.astype('<i8',copy=False).tobytes())
    return h.hexdigest()

def stage(root,name,conf,build):
    target=root/name;receipt=target/'_DONE.json'
    if target.exists():
        require(receipt.is_file(),'Incomplete final stage directory; inspect before rerunning: '+name)
        r=load(receipt);require(r['config_sha256']==conf,'Stage configuration differs: '+name)
        for item in r['files']:checked(target/item['path'],item['sha256'],item['bytes'])
        print('Reusing verified stage: '+name,flush=True);return target
    tmp=root/(name+'.partial')
    if tmp.exists():shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    result=build(tmp)
    spill=tmp/'spill'
    if spill.exists():shutil.rmtree(spill)
    records=[dict(path=str(p.relative_to(tmp)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(tmp.rglob('*')) if p.is_file()]
    save(tmp/'_DONE.json',dict(config_sha256=conf,completed_utc=utc(),result=result,files=records))
    os.replace(tmp,target)
    return target

PUBLIC_MEMBERS={
    'frames':['frame_checks.json','row_digest_checks.json'],
    'accounts':['original_sampling_cells.csv','profile_checks.json'],
    'tables':['READ_RESULTS.txt','readiness.json']+[name+ext for name in ['coverage_summary','coverage_status','weight_diagnostics','snapshot_lags','coverage_breakdowns','recipient_multiplicity'] for ext in ['.csv','.json']],
}

def export(root,desktop,conf,percent,status,provenance,error=None):
    # Whitelist only aggregate products; never recurse through private account files.
    public=root/'report';public.mkdir(exist_ok=True)
    for group,names in PUBLIC_MEMBERS.items():
        for name in names:
            p=root/group/name
            if (root/group/'_DONE.json').exists() and p.exists():shutil.copy2(p,public/name)
    save(public/'summary.json',dict(version='1.0.1',config_sha256=conf,progress_percent=percent,status=status,utc=utc(),
        regressions=0,api_requests=0,engine_searches=0,aggregate_only=True,error=error))
    save(public/'provenance.json',provenance)
    files=[p for p in sorted(public.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    save(public/'REPORT_MANIFEST.json',[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in files])
    name=f'PATRON_IV_COVERAGE_{conf[:12]}_{percent:03d}'+('_BLOCKED' if status=='BLOCKED' else '')+'.zip'
    destination=desktop/name;tmp=destination.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.iterdir()):z.write(p,arcname=p.name)
    os.replace(tmp,destination)
    destination.with_suffix('.zip.sha256').write_text(sha(destination)+'  '+destination.name+'\n')
    print('Aggregate report: '+str(destination),flush=True)
    return destination

class Progress:
    def __init__(self):
        self.start=time.monotonic();self.phase='binding and authentication';self.percent=0
        self.event=threading.Event();self.thread=threading.Thread(target=self.heartbeat,daemon=True)
    def begin(self):self.thread.start()
    def message(self):
        elapsed=time.monotonic()-self.start
        # Stage percentages are milestones, not byte-based forecasts. Estimates are explicitly provisional.
        total=max(300,elapsed/max(self.percent/100,.10)) if self.percent else max(600,elapsed*2)
        remaining=max(0,total-elapsed);next_remaining=remaining/max(1,(100-self.percent)/25)
        return f'{self.percent}% | {self.phase} | elapsed {elapsed/60:.1f}m | rough ETA next checkpoint {next_remaining/60:.1f}m; finish {remaining/60:.1f}m (provisional)'
    def heartbeat(self):
        while not self.event.wait(30):print(self.message(),flush=True)
    def mark(self,percent,phase):self.percent=percent;self.phase=phase;print(self.message(),flush=True)
    def close(self):self.event.set();self.thread.join()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--r9-root',type=Path);parser.add_argument('--r9b-root',type=Path)
    parser.add_argument('--workers',type=int,default=10);parser.add_argument('--memory-gb',type=float,default=11)
    args=parser.parse_args();require(1<=args.workers<=10 and 3<=args.memory_gb<=11,'Use 1–10 workers and 3–11 GiB')
    package_sha=package_check();authority=load(PACKAGE/'evidence/authority.json')
    project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project root is absent: '+str(project));desktop.mkdir(parents=True,exist_ok=True)
    auditbase=project/'derived/replication/patron_iv_coverage_v100_PRIVATE';auditbase.mkdir(parents=True,exist_ok=True)
    lock=(auditbase/'RUN.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another Patron coverage audit is already running')
    progress=Progress();progress.begin();percent=0;root=auditbase/('preflight_'+package_sha[:12]);root.mkdir(exist_ok=True)
    conf=package_sha;provenance={'package_manifest_sha256':package_sha,'source_authority_sha256':sha(PACKAGE/'evidence/authority.json')}
    try:
        r9=(args.r9_root or project/authority['R9']['root_rel']).resolve();r9b=(args.r9b_root or project/authority['R9b']['root_rel']).resolve()
        inputs,records=bind(project,r9,r9b,args.workers,authority)
        config=dict(package_manifest_sha256=package_sha,inputs=records,workers=args.workers,memory_gb=args.memory_gb)
        conf=digest_json(config);root=auditbase/conf[:12];root.mkdir(exist_ok=True)
        save(root/'config_PRIVATE.json',config)
        save(root/'INPUTS_PRIVATE.json',{k:([str(x) for x in v] if isinstance(v,list) else str(v)) for k,v in inputs.items()})
        provenance.update(input_files=[dict(role=k,sha256=v['sha256'],bytes=v['bytes']) for k,v in records.items()],
            duckdb_version=duckdb.__version__,pyarrow_version=__import__('pyarrow').__version__,
            source_R9_config=authority['R9']['config_sha256'],source_R9b_config=authority['R9b']['config_sha256'],
            frozen_comparison_phase=75,complete_input_authentication=True,
            frame_schemas={k:{'rows':pq.ParquetFile(inputs[k]).metadata.num_rows,
                             'fields':{field.name:str(field.type) for field in pq.ParquetFile(inputs[k]).schema_arrow}}
                           for k in ['S0','S0_scores','expanded','expanded_scores','F','F_scores','O','O_scores']},
            speed_definition='Certified R9b: searchsorted([180,480,1500], tc_base_s+40*tc_inc_s, side=right)')
        percent=25;export(root,desktop,conf,percent,'INPUTS_AUTHENTICATED',provenance);progress.mark(percent,'frame and Score A bridges')
        def frames_build(tmp):
            c=connect(tmp,args.workers,args.memory_gb)
            try:
                result=project_frames(c,inputs,tmp,authority['counts']);digests={}
                for key in ['S0','F','O']:
                    p=tmp/('expanded.parquet' if key=='S0' else key+'.parquet')
                    digests[key]=row_digest(c,p,'spaced90' if key=='S0' else 'TRUE')
                    require(digests[key]==authority['row_digests'][key],'Reviewed row-set digest differs: '+key)
                save(tmp/'row_digest_checks.json',digests);return result
            finally:c.close()
        frames=stage(root,'frames',conf,frames_build)
        percent=50;export(root,desktop,conf,percent,'FROZEN_FRAMES_VERIFIED',provenance);progress.mark(percent,'identity linkage and original sampling')
        def accounts_build(tmp):
            c=connect(tmp,args.workers,args.memory_gb)
            try:return build_accounts(c,inputs,frames,tmp,authority['counts'])
            finally:c.close()
        accounts=stage(root,'accounts',conf,accounts_build)
        percent=75;export(root,desktop,conf,percent,'IDENTITY_AND_SAMPLING_VERIFIED',provenance);progress.mark(percent,'coverage and weight tabulations')
        def tables_build(tmp):
            c=connect(tmp,args.workers,args.memory_gb)
            try:return tabulate(c,frames,accounts,tmp)
            finally:c.close()
        stage(root,'tables',conf,tables_build)
        percent=100;export(root,desktop,conf,percent,'COVERAGE_AUDIT_COMPLETE',provenance);progress.mark(percent,'complete')
        print('SUCCESS. Return the 100% aggregate ZIP, its SHA256 file, and the run log. Private Parquet files stay in the new project audit directory.',flush=True)
        return 0
    except Exception as e:
        traceback.print_exc()
        export(root,desktop,conf,percent,'BLOCKED',provenance,error={'type':type(e).__name__,'stage':progress.phase,'details':'See run log. No estimation was performed.'})
        return 1
    finally:progress.close();lock.close()

if __name__=='__main__':sys.exit(main())
