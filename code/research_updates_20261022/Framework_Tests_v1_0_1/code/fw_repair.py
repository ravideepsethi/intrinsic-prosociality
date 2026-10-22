"""Read-only reuse of a certified v1.0.0 run; new calculations have new identities."""
from fw_common import *
import shutil

PARENT_PACKAGE='e487733c25ae95159e0fdb256da56d9b76901bc3fd1447f4dc5c3b91eba48b38'
REPAIR_STAGES=['F_adjusted','E_iv','B','D','B_profiles','B_logit']

def copy_checked(source,destination):
    source=Path(source);destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():require(sha(destination)==sha(source),'Retained file differs: '+str(destination))
    else:shutil.copy2(source,destination)

def prepare(a,run,key):
    parent=a.reuse_framework_root.resolve();conf=load(parent/'CONFIGURATION.json');oldkey=digest(conf)
    require(conf.get('version')=='1.0.0' and conf.get('package_sha256')==PARENT_PACKAGE,'Reuse requires the original authenticated Framework Tests v1.0.0 package')
    require(oldkey[:12]==parent.name,'Parent run directory/configuration mismatch')
    require(conf['project']==str(a.project_root.resolve()),'Reuse project differs from parent')
    status=load(parent/'report/STATUS.json');paths=load(parent/'PATHS_PRIVATE.json')
    require(status['run_id']==parent.name,'Parent status/configuration mismatch')
    records=load(parent/'INPUTS_PRIVATE.json')
    require(len(records)==24,'Parent is missing monthly projections')
    with heartbeat('Verify saved projections and unchanged sources'):
      for r in records:
        require(completed(parent/'input'/r['month'],digest([oldkey,r['month'],r['source_sha256']])),'Missing monthly projection checkpoint')
      require(completed(parent/'accounts',digest([oldkey,'accounts'])),'Missing raw account aggregation checkpoint')
    expected_panels=[str(parent/'input'/m/'data.parquet') for m in MONTHS]
    require([str(Path(p).resolve()) for p in paths['panels']]==expected_panels,'Unexpected parent panel paths')
    require(Path(paths['accounts']).resolve()==parent/'accounts/accounts_F_state_year.parquet','Unexpected raw account path')
    require(sum(pq.ParquetFile(p).metadata.num_rows for p in paths['panels'])==41534331-sum(r['removed'] for r in records),'Parent panel count differs')
    inherited={}
    # Only unaffected public results are retained. B and D are re-estimated.
    authorities=[('A',parent/'A/final',digest([oldkey,'A'])),
      ('F_raw',parent/'F/raw',digest([oldkey,'raw',999])),
      ('C',parent/'C/final',digest([oldkey,'C']))]
    for name,folder,ck in authorities:
        require(completed(folder,ck),'Missing completed '+name+' checkpoint')
    for name in ('A','A3','C','E_matched','F_raw'):
        old=status['stages'].get(name,{})
        require(old.get('execution')=='FINISHED','Cannot retain unfinished '+name)
        inherited[name]=dict(old,reused_from=parent.name)
    # Bind every retained public file to the uploaded report's byte manifest.
    manifest=load(ROOT/'evidence/parent_result_manifest.json')
    for rec in manifest:
        rel=rec['path'].removeprefix('results/')
        if not rec['path'].startswith('results/'):continue
        allowed=(rel.startswith(('A/report/','A3/report/','C/report/','C/exposure/report/')) or
          rel.startswith('E/report/tabE') and not rel.startswith('E/report/tabE2') or
          rel.startswith('F/report/') or rel.startswith('report/source_counts'))
        if not allowed:continue
        src=parent/rel;require(src.is_file() and sha(src)==rec['sha256'],'Parent report changed: '+rel)
        copy_checked(src,run/rel)
    copy_checked(parent/'A/flagged_chooser_names_PRIVATE.json',run/'A/flagged_chooser_names_PRIVATE.json')
    save(run/'REUSE_PRIVATE.json',dict(parent=str(parent),parent_key=oldkey,paths=paths))
    save(run/'PATHS_PRIVATE.json',dict(panels=paths['panels'],accounts=paths['accounts'],parts=[]))
    save(run/'report/REPAIR_SCOPE.json',dict(parent_run=parent.name,
      retained=list(inherited),reestimated=REPAIR_STAGES,
      invalidated=['All v1.0.0 B coefficients, profiles, logit and the B-based D trigger'],
      raw_persistence='Unaffected: raw account cells aggregate all monthly files before correlation.',
      fixes=['One complete physical file per account bucket',
        'Sum partial residual counts/sums before adjusted persistence',
        'Validate S0 follow-up with the original timestamp rule',
        'Whiten conditional-logit design and verify exact Newton stationarity']))
    return inherited

def complete_parts(a,run,key):
    reuse=load(run/'REUSE_PRIVATE.json');parent=Path(reuse['parent']);paths=reuse['paths']
    work=run/'partitions';pk=digest([key,'whole_accounts'])
    if completed(work,pk):return sorted(work.glob('accounts/bucket_*.parquet'))
    with heartbeat('Verify original partition fragments'):
        require(completed(parent/'partitions',digest([reuse['parent_key'],'parts'])),'Uncertified original fragments')
    from fw_inputs import consolidate_buckets
    return consolidate_buckets(paths['parts'],paths['panels'],work,pk,a.memory_gb)

def adjusted(a,run,key):
    reuse=load(run/'REUSE_PRIVATE.json');parent=Path(reuse['parent']);oldkey=reuse['parent_key']
    work=run/'F/adjustment';ck=digest([key,'combine_saved_scores'])
    if completed(work,ck):return work/'adjusted_accounts.parquet'
    source=parent/'F/adjustment';expected=digest([oldkey,'nuisance'])
    with heartbeat('Verify saved nuisance fits and residual scores'):
        require(completed(source,expected),'Original adjusted scores incomplete; cannot reuse them')
    from fw_adjust import combine_scores
    original=source/'adjusted_accounts.parquet'
    output=combine_scores([original],work/'adjusted_accounts.parquet',a.memory_gb)
    for p in (source/'report').glob('*'):copy_checked(p,work/'report'/p.name)
    certify(work,ck,[original,source/'_DONE.json']);return output

def history(a,run,key):
    reuse=load(run/'REUSE_PRIVATE.json');parent=Path(reuse['parent']);oldkey=reuse['parent_key']
    work=parent/'E/history'
    with heartbeat('Verify saved recipient histories'):
        require(completed(work,digest([oldkey,'full_history_earliest'])),'Recipient-history cache is incomplete')
    return work/'earliest.parquet'
