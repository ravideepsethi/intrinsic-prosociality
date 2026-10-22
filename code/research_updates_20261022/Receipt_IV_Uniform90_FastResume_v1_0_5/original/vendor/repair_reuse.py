"""Explicit, read-only reuse of the authenticated v1.0.0 failed run."""
from rebuild_common import *
PARENT_CONF='56739829cf4a914d145af834bb5a0ccd3798b43fda1910dd2a93e643bc6b6b81'
PARENT_MANIFEST='5292c74576ff24bfba584fdfde669d2c9bdc8a1566b81a65c4355bf159f88a4d'
REPORTS=('receipt_stream.json','candidate_flow.json','alltime_support.json','exposure_selection_counts.csv')

def authenticate_parent(a,run,b):
    parent=a.reuse_run;cfg=load(parent/'config.json')
    require(key(cfg)==PARENT_CONF,'Reuse parent is not the reviewed 56739829cf4a run')
    require(cfg['package_manifest_sha256']==PARENT_MANIFEST,'Reuse producer manifest differs')
    require(Path(cfg['project']).resolve()==a.project,'Reuse project differs')
    for k in ('r12_root','r9_root','local_plan'):
        current=str(getattr(a,k)) if getattr(a,k) is not None else None
        require(cfg[k]==current,'Reuse input setting differs: '+k)
    require({k:v for k,v in cfg['rule'].items() if k!='version'}=={k:v for k,v in RULE.items() if k!='version'},'Scientific rules changed')
    old=load(parent/'PRIVATE/BINDING.json')
    require(key(old['source'])==key(b['source']),'Authenticated chronology or behavioral sources changed')
    for k in ('primary','primary_scores','raw','all_scores','bound'):
        require(key(old['primary'][k])==key(b['primary'][k]),'Primary input binding changed: '+k)
    records=[]
    for name in ('receipt_stream','candidates','supported'):
        folder=parent/'PRIVATE'/name;receipt=frozen.r.io.complete(folder,PARENT_CONF)
        require(receipt is not None,'Completed parent stage missing: '+name)
        for dep in load(folder/'dependencies_PRIVATE.json'):
            frozen.r.io.checked(dep['path'],dep['sha256'])
        records.append(dict(stage=name,receipt_sha256=sha(folder/'_DONE.json')))
    require(pq.ParquetFile(parent/'PRIVATE/supported/queries.parquet').metadata.num_rows==26643193,'Reviewed supported candidate count changed')
    b['candidate_run']=str(parent);b['candidate_configuration']=PARENT_CONF
    save(run/'report/reuse_authentication.json',dict(parent_configuration=PARENT_CONF,parent_package_manifest=PARENT_MANIFEST,
      stages=records,old_outputs_modified=False,selection_and_scores_recomputed=False,new_execution_version=VERSION))

def copy_candidate_reports(run,b):
    parent=Path(b['candidate_run']);manifest=load(parent/'report/REPORT_MANIFEST.json')
    for name in REPORTS:
        rec=next(v for v in manifest if v['path']==name)
        frozen.r.io.checked(parent/'report'/name,rec['sha256'],rec['bytes'])
        shutil.copyfile(parent/'report'/name,run/'report'/name)
