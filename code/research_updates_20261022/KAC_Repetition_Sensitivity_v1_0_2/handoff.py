"""Reuse reviewed v1.0.0 checkpoints without changing their bytes or metadata."""
from util import *
import fcntl


def authority():return load(ROOT/'authority/repetition_parent.json')


def parent_root(project):
    return Path(project)/'output/kac_repetition_sensitivity_v100'/authority()['parent_run']


def lock_reviewed(project):
    parent=parent_root(project);auth=authority()
    actual=load(parent/'report/CONFIG.json')
    for name in ('version','package_sha','project','amendment_sha'):
        require(actual.get(name)==auth['parent_config'][name],'Reviewed repetition configuration changed')
    require(sha(ROOT/'authority/repetition_parent_manifest.json')==actual['package_sha'],
        'Reviewed repetition package manifest changed')
    handles=[]
    diagnostic=Path(project)/'output/kac_history_identity_diagnostic_v100/f307aab0156f7aff'
    recent=latest_root(project)
    actual_recent=load(recent/'report/CONFIG.json');a101=load(ROOT/'authority/v101_run.json')
    require(all(actual_recent.get(k)==v for k,v in a101['config'].items()),'Reviewed v1.0.1 configuration changed')
    require(sha(ROOT/'authority/v101_manifest.json')==a101['config']['package_sha'],
        'Reviewed v1.0.1 package manifest changed')
    for folder in (parent,diagnostic,recent):
        require(folder.is_dir(),'Reviewed repetition/identity output is missing')
        h=(folder/'RUN.lock').open('a')
        try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Related repetition/diagnostic job is still running') from None
        handles.append(h)
    ref=ROOT/'authority/identity_diagnostic'
    for p in sorted(ref.rglob('*.json')):
        if p.name=='PACKAGE_MANIFEST.json':continue
        target=diagnostic/'report'/p.relative_to(ref)
        require(target.is_file() and sha(target)==sha(p),'Reviewed identity diagnostic report changed')
    for month in ('2024-08','2024-09','2024-10','2024-11'):
        p=ROOT/'authority/december_failure/history_integrity'/f'{month}.json'
        require(sha(recent/'report/history_integrity'/p.name)==sha(p),'Reviewed completed-month report changed')
    return handles


def latest_root(project):
    return Path(project)/'output/kac_repetition_sensitivity_v101'/load(ROOT/'authority/v101_run.json')['run']


def prepare_latest(cat,run,key,budget,io_workers,memory):
    """Reuse the old ten months plus four newly completed and reviewed months."""
    previous=prepare(cat,run,key,budget,io_workers,memory)
    project=Path(load(Path(run)/'report/CONFIG.json')['project'])
    parent=parent_root(project);recent=latest_root(project)
    old_key=load(ROOT/'authority/v101_run.json')['key']
    # The first ten v101 histories are references to the independently pinned
    # v100 outputs. Authenticate their entire chain before the four new months.
    prior=recent/'PRIVATE/history/initial'
    initial=load(prior/'_DONE.json')
    require(initial['key']==old_key and initial['files']==load(parent/'PRIVATE/history/initial/_DONE.json')['files'],
        'v101 initial state differs from reviewed parent')
    for month in ['2023-10']+[m for m in MONTHS if m<='2024-07']:
        old=recent/'PRIVATE/history'/month;rec=load(old/'_DONE.json')
        records=[r for r in cat['chronology'] if r['month']==month]
        expected=digest([old_key,month,sha(prior/'_DONE.json'),[r['stat'] for r in records]])
        require(rec['key']==expected and rec['files']==load(parent/'PRIVATE/history'/month/'_DONE.json')['files'],
            'v101 inherited checkpoint chain changed')
        prior=old
    report=load(Path(run)/'report/CHECKPOINT_REUSE.json')
    for month in ('2024-08','2024-09','2024-10','2024-11'):
        old=recent/'PRIVATE/history'/month;new=Path(run)/'PRIVATE/history'/month
        review=ROOT/'authority/december_failure/history_integrity'/f'{month}.json'
        saved=recent/'report/history_integrity'/review.name
        require(saved.is_file() and sha(saved)==sha(review),'Completed-month integrity report changed')
        evidence=load(review)
        require(evidence['status']=='PASS' and evidence['written_original_focal_multiset_differences']==0,
            'Completed month lacks passing integrity evidence')
        records=[r for r in cat['chronology'] if r['month']==month];rec=load(old/'_DONE.json')
        require(len(rec['sources'])==len(records),'New completed-month source inventory changed')
        for source,r in zip(rec['sources'],records):
            require(source['path']==r['path'] and source['stat']==r['stat'],'New completed-month source changed')
        require(rec['focal_rows']==evidence['focal_rows'],'Completed focal count differs from report')
        old_k=digest([old_key,month,sha(prior/'_DONE.json'),[r['stat'] for r in records]])
        new_k=digest([key,month,sha(previous/'_DONE.json'),[r['stat'] for r in records]])
        adopt(old,new,old_k,new_k)
        dest=Path(run)/'report/history_integrity'/review.name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(review,dest)
        prior,previous=old,new;report['history_months'].append(month)
        log(month+': verified completed history reused')
    report.update(first_month_to_build='2024-12',recent_parent_run=recent.name,
        recent_parent_partial_sha256=load(ROOT/'authority/v101_run.json')['partial_zip_sha256'])
    js(Path(run)/'report/CHECKPOINT_REUSE.json',report)
    return previous


def adopt(old,out,old_key,new_key):
    """Checked symbolic references preserve the existing output inodes too."""
    old=Path(old);out=Path(out)
    rec=load(old/'_DONE.json');require(rec['key']==old_key,'Parent checkpoint key changed: '+str(old))
    if (out/'_DONE.json').is_file():
        require(cached(out,new_key),'New checkpoint unavailable');return
    before=snapshot(old/'_DONE.json')
    files=[]
    for row in rec['files']:
        rel=Path(row['path']);require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe checkpoint member')
        p=old/rel;stamp=snapshot(p)
        require(p.is_file() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],
            'Parent checkpoint damaged: '+str(p))
        require(snapshot(p)==stamp,'Parent checkpoint changed while checking')
        dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        temp=dest.with_name(dest.name+'.partial_'+uuid.uuid4().hex)
        os.symlink(str(p.resolve()),temp);os.replace(temp,dest)
        require(snapshot(p)==stamp and snapshot(dest)==stamp,'Checkpoint reference changed source metadata')
        files.append(row)
    require(snapshot(old/'_DONE.json')==before,'Parent receipt changed')
    extra={k:v for k,v in rec.items() if k not in ('key','files','adopted_from')}
    js(out/'_DONE.json',dict(key=new_key,files=files,**extra,adopted_from=dict(
        directory=str(old),key=old_key,receipt_sha256=sha(old/'_DONE.json'),
        method='checked read-only symbolic references; existing output bytes and metadata preserved')))


def prepare(cat,run,key,budget,io_workers,memory):
    """Authenticate dependencies before referencing the ten completed histories."""
    run=Path(run);project=Path(load(run/'report/CONFIG.json')['project'])
    parent=parent_root(project);old_key=authority()['parent_key']
    reference=ROOT/'authority/identity_diagnostic'
    expected=load(reference/'STATUS.json')
    require(expected['status']=='DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED' and expected['failing_focal_rows']==0
        and expected['months_checked']==15 and expected['focal_rows_checked']==26073431,
        'Identity diagnostic does not authorize this implementation-only resume')
    files=[]
    for r in cat['main']['month_records']:
        old=parent/'PRIVATE/focal'/r['month'];rec=load(old/'_DONE.json')
        require(rec['source']['sha256']==r['expected_sha256'] and rec['source']['path']==str(r['path'])
            and snapshot(r['path'])==rec['source']['stat'],'Certified focal source changed')
        dest=run/'PRIVATE/focal'/r['month']
        adopt(old,dest,digest([old_key,r['expected_sha256']]),digest([key,r['expected_sha256']]))
        files.append(dest/'rows.parquet')
    # Unlike the first run, explicitly authenticate the entire needed-chooser set.
    # A difference blocks reuse: counts/carries might have omitted those accounts.
    threads,_=slots(budget,min(io_workers,budget));c=db(run/'PRIVATE/spill_needed',memory,threads)
    old_needed=parent/'PRIVATE/needed.parquet';old_stamp=snapshot(old_needed)
    try:
        c.execute('CREATE TEMP TABLE canonical AS SELECT DISTINCT chooser FROM '+scan(files))
        copy(c,'SELECT chooser FROM canonical ORDER BY chooser',run/'PRIVATE/needed.parquet')
        c.execute('CREATE TEMP TABLE prior_needed AS SELECT chooser FROM '+scan(old_needed))
        count=c.execute('SELECT count(*),count(DISTINCT chooser),count(*) FILTER(WHERE chooser IS NULL) FROM canonical').fetchone()
        prior=c.execute('SELECT count(*),count(DISTINCT chooser),count(*) FILTER(WHERE chooser IS NULL) FROM prior_needed').fetchone()
        missing=copy(c,'SELECT chooser FROM canonical EXCEPT SELECT chooser FROM prior_needed',run/'PRIVATE/needed_missing_in_parent.parquet')
        extra=copy(c,'SELECT chooser FROM prior_needed EXCEPT SELECT chooser FROM canonical',run/'PRIVATE/needed_extra_in_parent.parquet')
        result=dict(canonical_rows=count[0],canonical_distinct=count[1],canonical_nulls=count[2],
            parent_rows=prior[0],parent_distinct=prior[1],parent_nulls=prior[2],
            missing_from_parent=missing,extra_in_parent=extra,parent_needed_sha256=sha(old_needed))
        js(run/'report/NEEDED_CHOOSER_CHECK.json',result)
        expected_accounts=cat['main']['authority']['choosers']
        require(count==(expected_accounts,expected_accounts,0) and prior==count and missing==extra==0,
            'Needed chooser set differs; no completed histories reused. See NEEDED_CHOOSER_CHECK.json')
    finally:c.close();shutil.rmtree(run/'PRIVATE/spill_needed',ignore_errors=True)
    require(snapshot(old_needed)==old_stamp,'Parent needed set changed')
    uncertain=parent/'PRIVATE/uncertain_prefix';ur=load(uncertain/'_DONE.json')
    expected_source=load(ROOT/'authority/diagnostic/KEY_AND_TIME.json')['source_sha256']
    require(ur['source']['sha256']==expected_source and snapshot(ur['source']['path'])==ur['source']['stat'],
        'Reviewed June record source changed')
    checked(ur['source']['path'],expected_source)
    adopt(uncertain,run/'PRIVATE/uncertain_prefix',digest([old_key,expected_source]),digest([key,expected_source]))
    # Prefix outputs are not consumed again; authenticate their source bindings
    # and configuration before using the already-aggregated initial carry.
    prefix=[r for r in cat['chronology'] if r['month']<'2023-10']
    for r in prefix:
        rec=load(parent/'PRIVATE/prefix'/(r['speed']+'_'+r['month'])/'_DONE.json')
        old_k=digest([old_key,r])
        if r['path']==ur['source']['path']:
            old_k=digest([old_key,r,sha(uncertain/'_DONE.json'),'valid_timestamp_history'])
        require(rec['key']==old_k and rec['source']['path']==r['path'] and rec['source']['stat']==r['stat'],
            'Prefix dependency changed')
    for name in ('UNCERTAINTY.json','TIMESTAMP_AUDIT.json'):
        shutil.copyfile(parent/'report'/name,run/'report'/name)
    inventory=load(reference/'PARENT_CHECKPOINTS.json')['months']
    completed=[r for r in inventory if r['completion_receipt_present']]
    require([r['month'] for r in completed]==['2023-10']+[m for m in MONTHS if m<='2024-07'],
        'Reviewed completed history inventory changed')
    old_previous=parent/'PRIVATE/history/initial';new_previous=run/'PRIVATE/history/initial'
    adopt(old_previous,new_previous,old_key,key)
    adopted=[]
    for item in completed:
        month=item['month'];old=parent/'PRIVATE/history'/month;new=run/'PRIVATE/history'/month
        require(sha(old/'_DONE.json')==item['receipt_sha256'],'Reviewed history receipt changed')
        records=[r for r in cat['chronology'] if r['month']==month]
        rec=load(old/'_DONE.json')
        require(len(rec['sources'])==len(records),'History source inventory changed')
        for source,r in zip(rec['sources'],records):
            require(source['path']==r['path'] and source['stat']==r['stat'],'Completed history source changed')
        old_k=digest([old_key,month,sha(old_previous/'_DONE.json'),[r['stat'] for r in records]])
        new_k=digest([key,month,sha(new_previous/'_DONE.json'),[r['stat'] for r in records]])
        adopt(old,new,old_k,new_k)
        old_previous,new_previous=old,new;adopted.append(month)
        log(month+': verified completed history reused')
    js(run/'report/CHECKPOINT_REUSE.json',dict(parent_run=parent.name,
        focal_months=len(files),history_months=adopted,first_month_to_build='2024-08',
        initial_carry_reused=True,prefix_source_bindings_checked=len(prefix),
        unused_prefix_output_data_rehashed=False,completed_history_output_hashes_verified=True,
        completed_history_bytes_and_metadata_preserved=True,
        diagnostic_result_sha256='3d6f18a22fbe9ee3aa6664675f89f6f41cdaf762c2475b0cc6f70e2aad56417d'))
    return new_previous
