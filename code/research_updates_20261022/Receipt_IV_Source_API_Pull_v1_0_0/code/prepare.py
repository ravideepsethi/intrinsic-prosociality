"""Freeze only the reviewed unresolved IDs; never regenerate game histories."""
import os, shutil, uuid
from common import *

def stage_receipt(ready,root,project,auth):
    path=root/'_DONE.json'
    rr=[r for r in ready['receipts'] if relocate(r['path'],project).resolve()==path.resolve()]
    if len(rr)!=1:raise RuntimeError('Expected stage receipt is not uniquely bound by READY')
    checked(path,rr[0],auth)
    return load(path)

def output_entry(done,name):
    rr=[r for r in done['files'] if r['path']==name]
    if len(rr)!=1:raise RuntimeError('Expected output is not uniquely bound by its receipt')
    return rr[0]

def prepare(project,work,threads):
    root=project/'derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE'
    ready_path=root/'READY_FOR_IV_COHORT_ASSEMBLY_PRIVATE.json';ready=load(ready_path)
    if ready.get('code_signature')!=COHORT_CODE or ready.get('status')!='MEMBERSHIP_AND_PAIR_EXCLUDED_SCORE_INPUTS_READY':
        raise RuntimeError('The reviewed completed cohort extension is required')
    auth=work/'authentication';source_root=relocate(ready['source_root'],project)
    done=stage_receipt(ready,source_root,project,auth)
    source=source_root/'source_by_game_PRIVATE.parquet'
    source_snap=checked(source,output_entry(done,source.name),auth)
    targets=[r for r in done['inputs'] if Path(r['path']).name=='targets_PRIVATE.parquet']
    if len(targets)!=1:raise RuntimeError('Authenticated target metadata is ambiguous')
    target=relocate(targets[0]['path'],project);target_snap=checked(target,targets[0],auth)
    membership_root=relocate(ready['membership_root'],project)
    mdone=stage_receipt(ready,membership_root,project,auth)
    membership={}
    for month in MONTHS:
        rel=f'membership/month={month}/membership_PRIVATE.parquet'
        membership[month]=checked(membership_root/rel,output_entry(mdone,rel),auth)
    contract=dict(version=VERSION,code_signature=code_signature(),cohort_code=COHORT_CODE,
        endpoint=ENDPOINT,params=PARAMS,batch_size=BATCH_SIZE,months=list(MONTHS),expected=EXPECTED,
        source=source_snap,target=target_snap,membership=membership,
        cohort_ready_path=str(ready_path),cohort_ready_sha256=sha(ready_path),
        known_main_rows_before=mdone['result']['known_main_rows'],
        scope='Only reviewed active-opportunity IDs with unresolved matchmaking source; not the full incident denominator')
    # Stamps authenticate local reads but are not part of the semantic identity.
    frozen=dict(contract)
    frozen['source']={k:v for k,v in source_snap.items() if k!='stamp'}
    frozen['target']={k:v for k,v in target_snap.items() if k!='stamp'}
    frozen['membership']={m:{k:v for k,v in r.items() if k!='stamp'} for m,r in membership.items()}
    binding=digest(frozen);planroot=work/'plan';receipt_path=planroot/'_DONE.json'
    if receipt_path.is_file():
        plan=load(receipt_path)
        if plan['binding']!=binding:raise RuntimeError('Existing API plan has different inputs or code; preserve it')
        for r in plan['files']:checked(planroot/r['path'],r,auth)
        log('Reused frozen API target plan')
        return planroot,plan,contract
    if planroot.exists():raise RuntimeError('Existing target plan lacks a completion receipt')
    tmp=work/('plan.partial_'+uuid.uuid4().hex);tmp.mkdir()
    c=connection(tmp,threads)
    try:
        c.execute('CREATE VIEW s AS SELECT * FROM '+scan(source))
        c.execute('CREATE VIEW t AS SELECT * FROM '+scan(target))
        c.execute("CREATE TEMP TABLE wanted AS SELECT game_id,month FROM s WHERE source_status='missing'")
        counts=dict(c.execute('SELECT month,count(*) FROM wanted GROUP BY 1').fetchall())
        if counts!=EXPECTED:raise RuntimeError('Unresolved source counts differ from the reviewed run')
        paths=[];all_counts=[]
        for month in MONTHS:
            p=tmp/(month+'.parquet')
            q=f'''SELECT t.game_id,t.month,t.utc_ms,t.api_created_at_ms,t.expected_winner
              FROM t JOIN wanted w USING(game_id,month) WHERE t.month={lit(month)} ORDER BY t.game_id'''
            c.execute('COPY ('+q+') TO '+lit(p)+' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 120000)')
            actual=c.execute('SELECT count(*),count(DISTINCT game_id) FROM '+scan(p)).fetchone()
            if actual!=(EXPECTED[month],EXPECTED[month]):raise RuntimeError('Target join is not one-to-one')
            bad=c.execute("SELECT count(*) FROM "+scan(p)+" WHERE NOT regexp_full_match(game_id,'[A-Za-z0-9]{8}') OR utc_ms IS NULL OR (expected_winner IS NOT NULL AND expected_winner NOT IN ('white','black'))").fetchone()[0]
            if bad:raise RuntimeError('Target metadata is invalid')
            paths.append(p);all_counts.append(dict(month=month,rows=actual[0],batches=(actual[0]+299)//300))
        write_json(tmp/'INPUT_CONTRACT_PRIVATE.json',frozen)
        c.close();c=None;shutil.rmtree(tmp/'spill',ignore_errors=True)
        files=[receipt(p,tmp) for p in sorted(tmp.iterdir()) if p.is_file()]
        plan=dict(binding=binding,files=files,counts=all_counts,total_ids=sum(EXPECTED.values()),
                  total_batches=sum(r['batches'] for r in all_counts))
        write_json(tmp/'_DONE.json',plan);os.replace(tmp,planroot)
        log(f"Frozen {plan['total_ids']:,} IDs in {plan['total_batches']:,} requests of at most 300 IDs")
        return planroot,plan,contract
    finally:
        if c is not None:c.close()

def target_batches(path):
    pending=[];index=0
    for a in pq.ParquetFile(path).iter_batches(batch_size=30000,use_threads=False):
        pending.extend(a.to_pylist())
        while len(pending)>=BATCH_SIZE:
            rows,pending=pending[:BATCH_SIZE],pending[BATCH_SIZE:]
            yield index,rows;index+=1
    if pending:yield index,pending
