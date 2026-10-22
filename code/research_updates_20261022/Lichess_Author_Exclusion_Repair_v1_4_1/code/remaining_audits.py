"""Authenticate already excluded producers; never substitute a new IV estimand."""
from remaining_common import *
import audit_current as ac

class CheckedStages:
    def __init__(self):self.files={};self.stages=[]
    def file(self,path,expected,size=None):
        p=Path(path).resolve();sig=signature(p)
        if p not in self.files:
            got=sha(p);require(signature(p)==sig,'File changed while hashing');self.files[p]=(sig,got)
        require(self.files[p]==(sig,expected),'Authenticated dependency changed: '+str(p))
        require(size is None or p.stat().st_size==size,'Dependency byte count changed')
    def stage(self,folder,conf,needed=('result.json',)):
        folder=Path(folder);r=read(folder/'_DONE.json')
        require(r['config_sha256']==conf,'Stage configuration differs: '+str(folder))
        by={x['path']:x for x in r['files']}
        for name in tuple(needed)+('dependencies_PRIVATE.json',):
            require(name in by,'Missing sealed output: '+name);x=by[name]
            p=(folder/name).resolve();require(p.is_relative_to(folder.resolve()),'Unsafe stage path')
            self.file(p,x['sha256'],x['bytes'])
        deps=read(folder/'dependencies_PRIVATE.json')
        for x in deps:self.file(x['path'],x['sha256'])
        self.stages.append(str(folder));return deps

def framework_recipient(a,out):
    # Reuse the full main-panel exclusion/aggregate audit from the reviewed run.
    status=read(a.parent/'report/current_audits/framework.json')
    require(status['status']=='EXISTING_FRAMEWORK_PERSISTENCE_VERIFIED','Framework parent audit incomplete')
    sys.path.insert(0,str(ROOT/'vendor/framework_full/code'))
    import fw_common as fw
    current=a.project/'derived/replication/framework_tests_v101_PRIVATE/5c1254207382'
    reuse=read(current/'REUSE_PRIVATE.json');old=Path(reuse['parent'])
    key=fw.digest(read(old/'CONFIGURATION.json'))
    require(key==reuse['parent_key'] and old.name=='bb37d1b1d1a3','Framework A3 parent changed')
    ak=fw.digest([key,'A3'])
    require(fw.completed(old/'A3/final',ak),'Recipient Patron final checkpoint changed')
    for rule in ('author_clean_baseline','exclude_either_recipient_flag'):
        require(fw.completed(old/'A3'/rule,fw.digest([ak,rule])),'Recipient Patron fitted checkpoint changed')
    result=read(old/'A3/final/status.json')
    require(result['authors_excluded_both_roles'] is True,'Recipient Patron producer did not exclude authors')
    pinned=[r for r in read(ROOT/'vendor/framework_full/evidence/parent_result_manifest.json') if r['path'].startswith('results/A3/report/')]
    require(pinned,'Missing reviewed recipient-Patron report authority')
    for r in pinned:
        path=old/r['path'].removeprefix('results/')
        require(path.is_file() and sha(path)==r['sha256'],'Reviewed recipient-Patron result changed')
    # Exact source, August roster and shared-account/date estimator are bundled
    # unchanged; original certificates bind all monthly panel and roster bytes.
    csv_reports(old/'A3/report',out/'report/tables')
    return dict(status='EXISTING_AUTHOR_EXCLUDED_RESULT_VERIFIED',family='recipient_patron',producer=result,paired_inclusion_counterfactual='NOT_RUN')

def iv_remaining(a,out):
    sys.path.insert(0,str(ROOT/'vendor/iv_primary'))
    import primary_inputs as pi,primary_common as pc
    old=a.project/'derived/replication/alltime_iv_primary_v100_PRIVATE/cf6b3d8b4d65'
    verify_report(ROOT/'evidence/iv_primary/report',old/'report')
    status=read(old/'report/STATUS.json');conf=status['configuration_sha256']
    require(status['completed_models']==status['planned_models']==134,'Current IV inventory differs')
    bound=pi.bind(argparse.Namespace(project=a.project,r12_root=a.project/'derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3',r9_root=None,comparison_root=None,workers=a.workers,memory_gb=a.memory_gb),out,digest([POLICY,sha(__file__)]))
    ids=bound['bound']['binding']['author_ids'];require(len(set(ids))==2,'IV author IDs unresolved')
    check=CheckedStages();jobs=[]
    for name in ('PRIMARY_PLAN','DIAGNOSTIC_PLAN'):jobs+=read(old/'PRIVATE'/(name+'.json'))
    require(len(jobs)==134,'IV model plan is not the complete current inventory')
    frames={};scores=set()
    for j in jobs:
        folder=Path(j['output']);require(folder.is_relative_to(old),'IV result outside reviewed run')
        deps=check.stage(folder,conf)
        paths={str(Path(x['path']).resolve()) for x in deps}
        require(str(Path(j['input']).resolve()) in paths and str(Path(j['scores']).resolve()) in paths,'IV fit lacks source/score dependency')
        frames[str(Path(j['input']).resolve())]=True;scores.add(str(Path(j['scores']).resolve()))
    counts=[]
    for path in frames:
        n=ac.audit_zero([path],'recipient_id','opponent_id',ids,out,a)
        counts.append(dict(frame=Path(path).parent.name+'/'+Path(path).name,rows=n,author_rows=0))
    for name in ('TIMING_CONTRAST_PLAN','COMPARISON_CONTRAST_PLAN'):
        plan=old/'PRIVATE'/(name+'.json')
        require(plan.is_file(),'Missing current IV contrasts: '+name)
        for j in read(plan):check.stage(j['output'],conf)
    table(out/'report/frame_audit',counts);csv_reports(old/'report',out/'report/tables')
    return dict(status='ALL_CURRENT_RECEIPT_IV_MODELS_AUTHOR_CLEAN_VERIFIED',models=134,distinct_frames=len(frames),score_files=len(scores),author_ids=ids,donor_reference='Original author-clean R9/R9b scores and nuisance reference authenticated by original binder; pinned v130 donor census retained',existing_parent_donor_audit=read(a.parent/'report/current_audits/iv_current.json'),separate_entry_and_ordinary='Audited in entry family',paired_inclusion_counterfactual='NOT_RUN')

def entry(a,out):
    sys.path.insert(0,str(ROOT/'vendor/entry'))
    import run_finish as f
    parent=a.project/'derived/replication/alltime_entry_placebo_v103_PRIVATE'/f.PARENT_CONF[:12]
    f.verify_parent_header(parent,a.project);b=f.bind(parent);check=f.Authentication()
    check.stage(parent/'PRIVATE/frames',f.PARENT_CONF,('F.parquet','O.parquet','F_scores.parquet','O_scores.parquet'))
    ids=b['primary']['bound']['binding']['author_ids']
    require(sorted(b['source']['author_ids'].values())==sorted(ids),'Entry and receipt author identities differ')
    flows=[]
    for label in ('legacy','totalfive'):
        for sample in ('F','O'):
            src=Path(b['old_paths'][sample]) if label=='legacy' else parent/'PRIVATE/frames'/(sample+'.parquet')
            scores=Path(b['old_scores'][sample]) if label=='legacy' else parent/'PRIVATE/frames'/(sample+'_scores.parquet')
            n=ac.audit_zero([src],'recipient_id','opponent_id',ids,out,a)
            require(n==f.EXPECTED_ROWS[label+'_'+sample],'Entry/ordinary frame count differs')
            for level in f.r9.LEVELS:
                check.stage(parent/'PRIVATE/models'/(label+'_'+sample+'__'+level),f.PARENT_CONF,('result.json',),[src,scores])
            flows.append(dict(sample=label+'_'+sample,rows=n,author_rows=0))
    finished=a.project/'derived/replication/alltime_entry_placebo_v105_PRIVATE/28aca5e0752a'
    config=read(finished/'config.json');conf=f.key(config)
    require(conf.startswith(finished.name) and config['parent_configuration']==f.PARENT_CONF,'Finished entry run differs')
    require(config['rule']==f.RULE,'Finished entry scientific definition differs')
    status=read(finished/'report/STATUS.json')
    require(status['progress_percent']==100 and all(v['status']=='COMPLETE' for v in status['stages'].values()),'Entry finish is incomplete')
    for r in read(finished/'report/REPORT_MANIFEST.json'):check.file(finished/'report'/r['path'],r['sha256'],r['bytes'])
    for level in f.r9.LEVELS:
        for label in ('new_receipt_minus_new_ordinary','F_new_minus_old','O_new_minus_old'):
            check.stage(finished/'PRIVATE/contrasts'/(label+'__'+level),conf,('result.json',))
    table(out/'report/frame_audit',flows);csv_reports(finished/'report',out/'report/tables')
    return dict(status='ENTRY_AND_ORDINARY_AUTHOR_CLEAN_RESULTS_VERIFIED',populations=flows,completed_finish=conf,paired_inclusion_counterfactual='NOT_RUN',factual_chronology_preserved=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--family',choices=['framework_recipient','iv_remaining','entry'],required=True);p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();a.parent=parent_root(a.project);out=a.run/'PRIVATE/audits'/a.family
    for s in ('PRIVATE','report'):(out/s).mkdir(parents=True,exist_ok=True)
    try:
        result=globals()[a.family](a,out)
        shutil.copytree(out/'report',a.run/'report/audit_tables'/a.family,dirs_exist_ok=True)
        write(a.run/'report/current_audits'/(a.family+'.json'),result)
    except Exception as e:
        import traceback
        write(a.run/'report/current_audits'/(a.family+'.json'),dict(status='NOT_VERIFIED',error=str(e),traceback=traceback.format_exc()));raise

if __name__=='__main__':main()
