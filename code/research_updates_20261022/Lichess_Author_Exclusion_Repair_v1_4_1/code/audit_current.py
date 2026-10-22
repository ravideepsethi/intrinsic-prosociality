"""Verify existing author-excluded results without repeating historical scans.

Every family runs in a separate process to isolate its original module names.
An audit never manufactures an author-included comparison.
"""
from engine import *
import argparse

def unique(values,label):
    values=list(values);require(len(values)==1,'Expected one '+label+'; found '+str(len(values)));return values[0]

def pinned_report(expected,actual):
    expected,actual=Path(expected),Path(actual);count=0
    require(actual.is_dir(),'Completed report unavailable: '+str(actual))
    for p in expected.rglob('*'):
        if p.is_file():
            other=actual/p.relative_to(expected)
            require(other.is_file() and sha(p)==sha(other),'Completed report changed/missing: '+str(other));count+=1
    require(count>0,'Empty pinned report');return count

def author_ids(args,out):
    sys.path.insert(0,str(ROOT/'vendor/stakes/code'))
    import prepare
    ids=prepare.author_ids(args.project,out/'PRIVATE')
    require(set(ids)==set(AUTHORS),'Author identity list differs')
    return ids

def audit_zero(paths,left,right,ids,out,args):
    c=db(out/'PRIVATE/spill_audit',max(1,args.memory_gb-2),args.workers)
    try:
        names=','.join(str(int(v)) for v in ids)
        n,bad=c.execute('SELECT count(*),count(*) FILTER(WHERE '+ident(left)+' IS NULL OR '+ident(right)+' IS NULL OR '+ident(left)+' IN ('+names+') OR '+ident(right)+' IN ('+names+')) FROM '+scan(paths)).fetchone()
        require(bad==0,'Author/missing identity survives in audited analytical rows')
        return int(n)
    finally:c.close()

def reputation(args,out):
    base=args.project/'derived/replication/reputation_v100_PRIVATE'
    old=unique(base.glob('1d4e350c2249*'),'completed reputation cache')
    files=pinned_report(ROOT/'evidence/reputation',old/'report')
    ids=author_ids(args,out)
    sys.path.insert(0,str(ROOT/'vendor/reputation/code'))
    import core
    feature=unique(old.glob('features/*/analysis.parquet'),'reputation feature table')
    receipt=core.cached(feature.parent);require(receipt is not None,'Unsealed reputation features')
    n=audit_zero([feature],'j','i',ids.values(),out,args)
    design=read(old/'DESIGN_FREEZE.json')
    require(design==read(ROOT/'evidence/reputation/DESIGN.json'),'Reputation design changed')
    require(set(design['account_policy']['exclude'])==set(AUTHORS),'Reputation exclusions differ')
    # Both-party exclusion also holds for broad all-source repayment opportunities.
    broad=list((old/'broad_projection').glob('*/panel.parquet'))
    require(len(broad)==24,'Incomplete broad repayment input inventory')
    for path in broad:require(core.cached(path.parent) is not None,'Unsealed repayment input')
    returns=audit_zero(broad,'j','i',ids.values(),out,args)
    return dict(status='EXISTING_AUTHOR_EXCLUDED_RESULT_VERIFIED',rows=n,return_rows=returns,
        report_files=files,source_history_scan_seconds=read(old/'report/SUMMARY.json')['elapsed_seconds'],
        prediction='Already fitted after exclusion; sample/folds/predictions unchanged',
        fresh_included_comparison='NOT_AVAILABLE',scope='one-in-five reputation and repayment; does not clear one-in-fifty first-repeat regression')

def stakes(args,out):
    evidence=ROOT/'evidence/stakes/Win_Premium_Stakes_Report'
    candidates=[]
    for p in (args.project/'output/win_premium_stakes_v100').glob('*/RUN_TIME.json'):
        if sha(p)==sha(evidence/'RUN_TIME.json'):candidates.append(p.parent)
    report=unique(candidates,'completed stakes report');files=pinned_report(evidence,report)
    old=args.project/'derived/replication/win_premium_stakes_v100_PRIVATE'/report.name
    ids=author_ids(args,out)
    require(read(old/'author_ids_PRIVATE.json')['author_ids']==ids,'Stakes numeric IDs changed')
    outputs=[];receipts=sorted((old/'history').glob('*/*/_DONE.json'))
    require(len(receipts)==135,'Stakes speed/month history receipt inventory changed')
    for rp in receipts:
        r=read(rp)
        for f in r['permanent_files']:
            path=verify(f)
            if path.parent==old/'analysis':outputs.append(path)
    require(len(set(outputs))==120,'Stakes analysis table inventory incomplete')
    n=audit_zero(outputs,'user_id','opponent_id',ids.values(),out,args)
    require(n==read(evidence/'RUN_TIME.json')['opportunities'],'Stakes row count changed')
    return dict(status='EXISTING_AUTHOR_EXCLUDED_RESULT_VERIFIED',rows=n,report_files=files,
        source_history_scan_seconds=read(evidence/'RUN_TIME.json')['elapsed_seconds'],
        reference_population='Original producer excludes both authors before monthly active-account ECDF',
        factual_rating_history_preserved=True,fresh_included_comparison='NOT_AVAILABLE')

def iv_current(args,out):
    sys.path.insert(0,str(ROOT/'vendor/iv_primary'))
    import primary_inputs as pi,primary_common as pc
    a=argparse.Namespace(project=args.project,r12_root=args.project/'derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3',
                         r9_root=None,comparison_root=None,workers=args.workers,memory_gb=args.memory_gb)
    old=args.project/'derived/replication/alltime_iv_primary_v100_PRIVATE/cf6b3d8b4d65'
    files=pinned_report(ROOT/'evidence/iv_primary/report',old/'report')
    # The unchanged original binder verifies R12/R9/R9b reports and receipts,
    # donor/state-reference identities, the primary frame, and primary score bytes.
    bound=pi.bind(a,out,digest([POLICY,sha(__file__)]))
    ids=bound['bound']['binding']['author_ids']
    require(len(set(ids))==2,'IV author IDs unresolved')
    n=audit_zero([bound['primary']],'recipient_id','opponent_id',ids,out,args)
    expected=read(ROOT/'evidence/iv_primary/report/cache_authentication.json')
    require(n==expected['primary_rows'] and sha(bound['primary'])==expected['primary_frame_sha256'] and sha(bound['primary_scores'])==expected['primary_score_sha256'],'IV primary differs from completed report')
    r9=Path(bound['bound']['parent']);donor_n=source_n=0
    # R9 does not retain a second copy of the cleaned donor rows. Recompute
    # its exact admission counts from authenticated source partitions and bind
    # them to all 16 completed score receipts; do not invent a donor cache path.
    parts=bound['bound']['parts'];names=','.join(map(str,ids))
    c=db(out/'PRIVATE/spill_donors',args.memory_gb-2,args.workers)
    try:
        for s in range(16):
            selected=[r for r in parts if r['shard']==s];require(bool(selected),'Missing donor shard')
            for r in selected:
                require(sha(r['path'])==r['sha256'],'Donor source changed')
            folder=r9/'scores'/f'{s:02}'
            config='4028bf3e185783a17679ed3d5fee5b376028f37141e1e5ce09b93b068a6a6e0b'
            pi.frozen.r9_inputs.stage_file(folder/'scores.parquet',config)
            pi.frozen.r9_inputs.stage_file(folder/'summary.json',config)
            info=read(folder/'summary.json')
            total,clean=c.execute('SELECT count(*),count(*) FILTER(WHERE arm AND j NOT IN ('+names+') AND i NOT IN ('+names+')) FROM '+scan([r['path'] for r in selected])).fetchone()
            require(total==info['source_rows'] and clean==info['eligible_author_clean_donor_rows'],'R9 author-clean donor counts differ from completed scores')
            donor_n+=int(clean);source_n+=int(total)
    finally:c.close()
    require(source_n==47587020,'R9 donor source census changed')
    scale=read(r9/'common_scale.json')['common_score_SD']
    require(abs(scale-pc.SD)<1e-14,'R9 reference SD changed')
    return dict(status='CURRENT_PRIMARY_AND_DONOR_LINEAGE_VERIFIED',primary_rows=n,donor_rows=donor_n,
        report_files=files,score_SD=scale,score_scale_origin='R9 author-excluded primary residual score SD; fixed across later cohorts',
        state_reference='Authenticated clean.npy from original author-excluded nuisance producer',
        donor_audit='Original completed score receipts plus exact author-clean admission counts rebuilt from authenticated source partitions; scores not refitted',
        fresh_included_comparison='NOT_RUN',scope='Current all-time IV primary and original binding; not a blanket audit of every historical IV analysis')

def local_inventory(args,out):
    """Metadata only: find remaining producers without exporting source or data."""
    roots=[args.project/'replication_package/code',args.project/'scripts',args.project/'code',Path.home()/'Desktop/Lichess_Desktop']
    needles=['266399','266_399','266,399','state_persistence','persistence_by_state','10.953','4.462']
    hits=[]
    for root in roots:
        if not root.is_dir():continue
        for p in root.rglob('*.py'):
            if any(part.startswith(('Lichess_Author_Exclusion_Reestimate','author_exclusion_python')) for part in p.parts):continue
            if p.stat().st_size>2_000_000:continue
            content=p.read_text(errors='replace')
            matched=[s for s in needles if s in content]
            if matched:hits.append({'search_root':str(root),'relative_path':str(p.relative_to(root)),'sha256':sha(p),'matched_terms':matched})
    write(out/'report/LOCAL_PRODUCER_LOCATIONS.json',hits)
    return dict(status='INVENTORY_ONLY',matches=len(hits),content_exported=False)

def framework(args,out):
    """Audit the completed F tables; later manuscript regressions stay pending."""
    sys.path.insert(0,str(ROOT/'vendor/framework/code'))
    import fw_common as fw
    run=args.project/'derived/replication/framework_tests_v101_PRIVATE/5c1254207382'
    config=read(run/'CONFIGURATION.json');key=fw.digest(config)
    require(key.startswith(run.name) and config['version']=='1.0.1','Framework configuration differs')
    pinned_report(ROOT/'evidence/framework/report',run/'report')
    files=pinned_report(ROOT/'evidence/framework/F/report',run/'F/report')
    reuse=read(run/'REUSE_PRIVATE.json');parent=Path(reuse['parent'])
    require(parent.name=='bb37d1b1d1a3','Unexpected framework parent')
    oldkey=fw.digest(read(parent/'CONFIGURATION.json'))
    require(oldkey==reuse['parent_key'],'Framework parent identity changed')
    rows=read(parent/'INPUTS_PRIVATE.json');require([r['month'] for r in rows]==MONTHS,'Framework month inventory differs')
    authority=module('framework_main_authority',ROOT/'vendor/wave1/runner/common.py').authenticate_sample(
        args.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',verify_hashes=False,hash_workers=1)
    original={r['month']:r for r in authority['month_records']}
    paths=[]
    for r in rows:
        source=original[r['month']]
        require(r['source_sha256']==source['expected_sha256'] and sha(source['path'])==r['source_sha256'],'Framework source differs')
        folder=parent/'input'/r['month'];p=folder/'data.parquet'
        require(Path(r['path']).resolve()==p.resolve(),'Framework projection moved')
        require(fw.completed(folder,fw.digest([oldkey,r['month'],r['source_sha256']])),'Framework projection unsealed')
        paths.append(p)
    # Resolve IDs from this main-panel namespace, not from a different dictionary.
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        cols=[]
        for role in ('chooser','disconnected'):
            cols.append('SELECT DISTINCT lower(trim('+role+'_username_norm)) AS author_name,'+role+'_user_id AS author_id FROM '+scan([r['path'] for r in original.values()])+' WHERE lower(trim('+role+'_username_norm)) IN ('+','.join(map(q,AUTHORS))+')')
        identities=c.execute(' UNION '.join(cols)).fetchall()
    finally:c.close()
    ids={a:{int(i) for n,i in identities if n==a} for a in AUTHORS}
    require(all(len(v)<=1 for v in ids.values()),'Ambiguous main-panel author identity')
    numeric=set().union(*ids.values());require(bool(numeric),'No main-panel author identity resolved')
    n=audit_zero(paths,'chooser','opponent',numeric,out,args)
    require(n==41534331-sum(r['removed'] for r in rows),'Framework source count differs')
    require(fw.completed(parent/'accounts',fw.digest([oldkey,'accounts'])),'Framework account aggregation unsealed')
    require(fw.completed(parent/'F/raw',fw.digest([oldkey,'raw',999])),'Raw persistence result unsealed')
    require(fw.completed(run/'F/adjustment',fw.digest([key,'combine_saved_scores'])),'Adjusted account aggregation unsealed')
    require(fw.completed(run/'F/adjusted',fw.digest([key,'adjusted',999])),'Adjusted persistence result unsealed')
    return dict(status='EXISTING_FRAMEWORK_PERSISTENCE_VERIFIED',rows=n,report_files=files,
        scope='Framework F raw and adjusted persistence, thresholds 4/10/20 and its coverage/forward-rate tables',
        fresh_included_comparison='NOT_AVAILABLE',
        manuscript_gap='Later threshold-1, four-group transitions and speed-adjusted regressions require their exact producer; not cleared by this audit')

def mechanism(args,out):
    """Reuse only if exact eligible input rows are invariant to the exclusion."""
    old=args.project/'derived/replication/mechanism_separation_v100_PRIVATE'
    report=args.project/'derived/replication/mechanism_rd_audit_resume_v101_PRIVATE/public_results'
    reference=read(ROOT/'evidence/mechanism/reference.json')
    require(read(old/'RUN_IDENTITY.json')['package_sha256']==reference['source_package_sha256'],'Mechanism source package differs')
    files=pinned_report(ROOT/'evidence/mechanism/report',report)
    paths=[]
    for month in MONTHS:
        p=old/'analysis'/(month+'.parquet');rec=read(p.with_suffix('.json'))['output']
        require(p.stat().st_size==rec['size'] and sha(p)==rec['sha256'],'Mechanism input changed')
        paths.append(p)
    ids=author_ids(args,out);names=','.join(str(i) for i in ids.values())
    c=db(out/'PRIVATE/spill_mechanism',args.memory_gb-2,args.workers)
    try:
        rows=c.execute('SELECT state,count(*) AS "rows",sum(y)::BIGINT grants,count(DISTINCT chooser) accounts,count(*) FILTER(WHERE chooser IS NULL OR opponent IS NULL OR chooser IN ('+names+') OR opponent IN ('+names+')) author_rows FROM '+scan(paths)+" WHERE regular IS TRUE AND state IN ('equal','losing') GROUP BY state ORDER BY state").fetchdf()
    finally:c.close()
    require(set(rows.state)=={'equal','losing'},'Missing mechanism state')
    for row in rows.itertuples():
        expected=reference['states'][row.state]
        require((row.rows,row.grants,row.accounts)==(expected['n'],expected['grants'],expected['accounts']),'Mechanism population differs from reviewed results')
    table(out/'report/eligible_input_census',rows)
    # If any author event qualifies, the old fits cannot pass through this audit.
    # The report will request an actual refit rather than relabeling old output.
    unchanged=int(rows.author_rows.sum())==0
    return dict(status='EXACT_ELIGIBLE_INPUTS_UNCHANGED_BY_EXCLUSION' if unchanged else 'AUTHOR_ROWS_PRESENT_REFIT_REQUIRED',
        author_rows=int(rows.author_rows.sum()),report_files=files,eligible_rows=int(rows.rows.sum()),
        scope='Regular-player equal/losing conditional-logit models, their RD<=110 restrictions, time folds and standardization subsets',
        implication='All full, capped, training, validation and standardization rows unchanged' if unchanged else 'Cannot reuse these mechanism coefficients as author-excluded',
        factual_activity_history_preserved=True,coefficients_refitted=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--family',choices=['reputation','stakes','iv_current','framework','mechanism','local_inventory'],required=True)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11);args=p.parse_args()
    out=args.run/'PRIVATE/current_audits'/args.family
    (out/'PRIVATE').mkdir(parents=True,exist_ok=True);(out/'report').mkdir(exist_ok=True)
    with heartbeat('Audit '+args.family):result=globals()[args.family](args,out)
    write(args.run/'report/current_audits'/(args.family+'.json'),result)
    if args.family=='local_inventory':shutil.copy2(out/'report/LOCAL_PRODUCER_LOCATIONS.json',args.run/'report/current_audits/LOCAL_PRODUCER_LOCATIONS.json')
    log(args.family+': '+result['status'])
if __name__=='__main__':main()
