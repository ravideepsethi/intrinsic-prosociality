"""Reuse the completed included session models; refit only the excluded sample.

Both count scenarios and actual session histories are unchanged. This module
does not open the billions-of-games chronology archive or create new sessions.
"""
from engine import *
import fcntl,concurrent.futures as cf

def progress(run,phase,month=None):
    write(run/'report/SESSION_PROGRESS.json',{'phase':phase,'month':month})
    log('Session continuation: '+phase+(' '+month if month else ''))

def bind_history(args,old,shared):
    included=read(args.run/'PRIVATE/inputs/included_AUTH.json')
    excluded=read(args.run/'PRIVATE/inputs/excluded_AUTH.json')
    # Parent input fingerprints are held fixed; byte verification was refreshed
    # at the beginning of this launch by the continuation orchestrator.
    key=digest([included['fingerprint'],excluded['fingerprint'],sha(__file__),sha(ROOT/'SESSION_AUTHORITY.json')])
    done=shared/'DONE.json'
    if done.exists():
        z=read(done);require(z['key']==key,'Shared session input identity changed')
        same=z.get('verification_session')==os.environ.get('AUTHOR_EXCLUSION_SESSION')
        for r in z['files']:
            if same:require(signature(r['path'])==r['verified_signature'],'Session history changed in this launch')
            else:verify(r)
        if not same:
            for r in z['files']:r['verified_signature']=signature(r['path'])
            z['verification_session']=os.environ.get('AUTHOR_EXCLUSION_SESSION');write(done,z)
        return z
    targets=[]
    for m in ['2023-10']+MONTHS:
        root=old/'PRIVATE/history'/m;receipt=read(root/'_DONE.json')
        for name in (['sessions30.parquet'] if m=='2023-10' else ['sessions30.parquet','focal_history.parquet']):
            listed=[r for r in receipt['files'] if r['path']==name]
            require(len(listed)==1,'Unmanifested history file: '+name)
            targets.append({'path':str(root/name),**{k:listed[0][k] for k in ('sha256','bytes')}})
    progress(args.run,'authenticate completed history Parquets')
    def checked(r):verify(r);return record(r['path'])
    with heartbeat('Completed session history authentication'),cf.ThreadPoolExecutor(max_workers=min(4,args.workers)) as pool:
        files=list(pool.map(checked,targets))
    audits=[];c=db(shared/'spill',args.memory_gb,args.workers)
    try:
        for m in MONTHS:
            progress(args.run,'bind exact focal game identity',m)
            source=old/'PRIVATE/history'/m/'focal_history.parquet'
            i=MONTHS.index(m);original=included['month_records'][i];filtered=excluded['month_records'][i]
            c.execute('CREATE OR REPLACE VIEW history_focal AS SELECT * FROM '+scan(source))
            c.execute('CREATE OR REPLACE VIEW main_focal AS SELECT game_id,chooser_user_id,outcome_kind_draw FROM '+scan(original['path']))
            n,unique=c.execute('SELECT count(*),count(DISTINCT game_id) FROM history_focal').fetchone()
            require(n==unique==original['rows'],'Session focal coverage differs: '+m)
            mismatch=c.execute('SELECT count(*) FROM history_focal f FULL JOIN main_focal p USING(game_id) WHERE f.game_id IS NULL OR p.game_id IS NULL OR f.chooser IS DISTINCT FROM p.chooser_user_id OR f.y IS DISTINCT FROM p.outcome_kind_draw').fetchone()[0]
            require(mismatch==0,'Session history does not match certified main events: '+m)
            dest=shared/'excluded'/m/'focal_history.parquet';dest.parent.mkdir(parents=True,exist_ok=True)
            if filtered['rows']==n:
                # No games removed in this month, as certified by the parent panel bytes.
                if dest.is_symlink():require(dest.resolve()==source.resolve(),'History link changed')
                elif dest.exists():raise RuntimeError('Unexpected existing unchanged history output')
                else:dest.symlink_to(source.resolve())
            else:
                kept=copy(c,'SELECT f.* FROM history_focal f SEMI JOIN '+scan(filtered['path'])+' p USING(game_id)',dest)
                require(kept==filtered['rows'],'Session retained row coverage differs: '+m)
            files.append(record(dest));audits.append(dict(month=m,before=n,after=filtered['rows'],removed=n-filtered['rows']))
    finally:c.close()
    # Detect any source or output modification during the entire binding step.
    for r in files:require(signature(r['path'])==r['verified_signature'],'History changed during binding')
    z=dict(key=key,verification_session=os.environ.get('AUTHOR_EXCLUSION_SESSION'),files=files,audits=audits)
    write(done,z);return z

def run_session(args,auth,out):
    old=args.session_root or args.project/'output/kac_repetition_sensitivity_v102/15c45082092d80d9'
    require(old.is_dir(),'Completed session authority missing')
    handle=(old/'RUN.lock').open('a')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Original session producer is still running')
    try:
        progress(args.run,'authenticate completed session report')
        for name,h in {**read(ROOT/'SESSION_AUTHORITY.json')['report_files'],**read(ROOT/'SESSION_BASELINE_HASHES.json')}.items():
            p=old/'report'/name
            require(p.is_file() and sha(p)==h,'Completed session authority differs/missing: '+name)
        shared=args.run/'PRIVATE/session_history_reuse';shared.mkdir(parents=True,exist_ok=True)
        z=bind_history(args,old,shared)
        rows=[{**r,'after':r['before'],'removed':0} for r in z['audits']] if args.variant=='included' else z['audits']
        table(out/'report/history_reuse_audit',rows)
        paths=[]
        for m in ['2023-10']+MONTHS:
            folder=out/'PRIVATE/history'/m;folder.mkdir(parents=True,exist_ok=True)
            sources={'sessions30.parquet':old/'PRIVATE/history'/m/'sessions30.parquet'}
            if m!='2023-10':sources['focal_history.parquet']=(old/'PRIVATE/history' if args.variant=='included' else shared/'excluded')/m/'focal_history.parquet'
            for name,p in sources.items():
                target=folder/name
                if target.is_symlink():require(target.resolve()==p.resolve(),'Session reference changed')
                elif target.exists():raise RuntimeError('Refusing to replace a session reference')
                else:target.symlink_to(p.resolve())
            if m!='2023-10':paths.append(folder/'focal_history.parquet')
        if args.variant=='included':
            for name in read(ROOT/'SESSION_BASELINE_HASHES.json'):
                target=out/'report'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old/'report'/name,target)
            result={'status':'VERIFIED_INCLUDED_SESSION_MODELS_REUSED','specifications':20,'history_exact_focal_binding':True,'new_fit':False}
        else:
            progress(args.run,'refit excluded session models')
            sys.path.insert(0,str(ROOT/'vendor/session'))
            import repetition
            result=repetition.run(paths,out,digest([auth['fingerprint'],z['key']]),args.workers,args.memory_gb)
            note=out/'report/repetition/INTERPRETATION.md'
            note.write_text(note.read_text().replace('retain the same focal observations and all accounts','retain the same author-excluded focal observations in both count scenarios'))
        for r in z['files']:require(signature(r['path'])==r['verified_signature'],'History changed during session analysis')
        write(out/'report/AUTHOR_POLICY.json',{'variant':args.variant,'analytical_author_games_excluded':args.variant=='excluded','factual_sessions_preserved':True,'timestamp_uncertainty':'Original two sensitivity scenarios preserved; not repaired','new_history_scans':0})
        progress(args.run,'complete '+args.variant)
        return result
    finally:handle.close()
