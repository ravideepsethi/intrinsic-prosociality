"""Import certified v1.0.2 chronology without rerunning its scan or merge."""
from rebuild_common import *

CHRONOLOGY_CONF='25d22fd1d9e9af03752bc2b253ff051f3151a410a0453c12a5d24fe3ce29355d'
CHRONOLOGY_MANIFEST='227c42c648c5b0fe40252471d810a933b2f61051debfeb95921471d25e34dcca'
OUTPUTS={'chronology':'features.parquet','locally_eligible':'queries.parquet'}
REPORTS=('chronology_scan_reuse.json','chronology_merge.json','chronology_reuse.json','local_eligibility.json')


def checked_stage(folder,conf):
    receipt=frozen.r.io.complete(folder,conf)
    require(receipt is not None,'Completed v1.0.2 chronology checkpoint missing: '+str(folder))
    for dep in load(folder/'dependencies_PRIVATE.json'):
        frozen.r.io.checked(dep['path'],dep['sha256'])
    return receipt


def authenticate_chronology(a,run,b):
    parent=a.reuse_chronology;cfg=load(parent/'config.json');oldconf=key(cfg)
    require(oldconf==CHRONOLOGY_CONF,'Chronology parent is not the reviewed 25d22fd1d9e9 run')
    require(cfg['version']=='1.0.2' and cfg['package_manifest_sha256']==CHRONOLOGY_MANIFEST,'Chronology producer differs')
    for name in ('project','r12_root','r9_root','local_plan','reuse_run'):
        current=str(getattr(a,name)) if getattr(a,name) is not None else None
        require(cfg[name]==current,'Chronology input setting differs: '+name)
    require({k:v for k,v in cfg['rule'].items() if k!='version'}==
            {k:v for k,v in RULE.items() if k!='version'},'Chronology scientific rules changed')
    old=load(parent/'PRIVATE/BINDING.json')
    for name in ('source','frame_root','frame_conf','comparison_root','comparison_conf',
                 'old_paths','old_scores','metadata','quarantine','candidate_run','candidate_configuration'):
        require(key(old[name])==key(b[name]),'Chronology input binding changed: '+name)
    for name in ('primary','primary_scores','raw','all_scores','bound'):
        require(key(old['primary'][name])==key(b['primary'][name]),'Chronology primary binding changed: '+name)
    receipts=[]
    for name,filename in OUTPUTS.items():
        folder=parent/'PRIVATE'/name
        receipt=checked_stage(folder,oldconf)
        require(any(x['path']==filename for x in receipt['files']),'Chronology output is not certified: '+name)
        receipts.append(dict(stage=name,receipt_sha256=sha(folder/'_DONE.json'),rows=receipt['rows']))
    manifest=load(parent/'report/REPORT_MANIFEST.json')
    for name in REPORTS:
        rec=next((x for x in manifest if x['path']==name),None)
        require(rec is not None,'Chronology report absent: '+name)
        frozen.r.io.checked(parent/'report'/name,rec['sha256'],rec['bytes'])
    b['chronology_run']=str(parent);b['chronology_configuration']=oldconf
    save(run/'report/completed_chronology_reuse.json',dict(parent_configuration=oldconf,
         parent_package_manifest=CHRONOLOGY_MANIFEST,stages=receipts,
         old_outputs_modified=False,raw_game_scans_started=0,chronology_merge_repeated=False))
    log('Verified completed v1.0.2 chronology and local eligibility; no scan or chronology merge will run.')


def import_chronology(run,conf,b):
    parent=Path(b['chronology_run']);oldconf=b['chronology_configuration']
    for name,filename in OUTPUTS.items():
        source=parent/'PRIVATE'/name
        # The authentication stage verifies inputs too; recheck output bytes at import.
        record=frozen.r.io.complete(source,oldconf)
        require(record is not None,'Completed chronology disappeared: '+name)
        def build(tmp,source=source,filename=filename,record=record):
            try:os.link(source/filename,tmp/filename)
            except OSError:shutil.copy2(source/filename,tmp/filename)
            return dict(rows=record['rows'],imported_from_configuration=oldconf,
                        source_receipt_sha256=sha(source/'_DONE.json'),recomputed=False)
        stage(run/'PRIVATE'/name,conf,build,[source/filename,source/'_DONE.json'])
    manifest=load(parent/'report/REPORT_MANIFEST.json')
    for name in REPORTS:
        rec=next(x for x in manifest if x['path']==name)
        frozen.r.io.checked(parent/'report'/name,rec['sha256'],rec['bytes'])
        shutil.copyfile(parent/'report'/name,run/'report'/name)
    log('Completed chronology imported read-only. Starting the bounded metadata audit.')
