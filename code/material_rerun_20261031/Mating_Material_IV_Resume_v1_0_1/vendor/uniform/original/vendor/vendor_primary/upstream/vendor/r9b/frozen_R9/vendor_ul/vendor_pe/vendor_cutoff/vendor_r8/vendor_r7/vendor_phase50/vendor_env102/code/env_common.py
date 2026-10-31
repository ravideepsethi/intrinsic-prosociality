"""Pinned inputs and local-only execution for the environment diagnostics."""
from pathlib import Path
import sys
PACKAGE=Path(__file__).resolve().parents[1]
ENTRY=PACKAGE/'vendor/entry100'
sys.path.insert(0,str(ENTRY/'code'))
import entry_common as prior
from entry_common import *
import entry_models as oldmodels
import entry_report as oldreport
PACKAGE=Path(__file__).resolve().parents[1]
VERSION='1.0.2'
OUTPUT_REL='derived/replication/run2_environment_diagnostics_v100_PRIVATE'
RECENT=['fair_history_present_30','log_fair_30','kind_ever_30','kind_rate_30','log_disconnect_30','log_receipt_30','log_claim_30']
RATE_NAMES=['opponent_observed_disconnect_rate','opponent_observed_chooser_rate']
ENV_NAMES=['log_opponent_games90']+RATE_NAMES

def verify_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);io.checked(io.child(PACKAGE,name),digest)
    prior.verify_package()
    io.checked(ENTRY/'PACKAGE_MANIFEST.sha256',io.load(PACKAGE/'evidence/authority.json')['entry_package_sha256'])

def bind(project,entry=None,parent=None):
    authority=io.load(PACKAGE/'evidence/authority.json');conf=authority['entry_config_sha256']
    root=(Path(entry) if entry else project/prior.ENTRY_REL/conf[:12]).expanduser().resolve()
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=conf:raise RuntimeError('Expected the reviewed completed entry configuration')
    if config['package_sha256']!=authority['entry_package_sha256']:raise RuntimeError('Entry producer changed')
    io.checked(root/'report/summary.json',authority['entry_summary_sha256'])
    if io.load(root/'report/summary.json')['status']!='ENTRY_DIAGNOSTICS_COMPLETE':raise RuntimeError('Entry diagnostics incomplete')
    binding=prior.authenticate(project,parent)
    if config['parent']!=binding:raise RuntimeError('Entry and 25% sources differ')
    checked_stage_files(root/'prepared',conf,[c+'.parquet' for c in COHORTS])
    parentroot=Path(binding['parent']);source=io.load(parentroot/'INPUTS_PRIVATE.json')
    # Restore paths only within the explicitly named project, not by broad discovery.
    for key in ('parts','panels','chron'):
        for row in source[key]:row['path']=str(relocate(project,row['path']))
    source['spaced']=str(relocate(project,source['spaced']))
    io.checked(source['spaced'],authors.SPACED_SHA,295180899)
    needed=set(MODEL_COLUMNS)-set(ENTRY_COLUMNS)
    needed |= {'received','y','reached','game_id','anchor_ms'}
    actual=set(pq.ParquetFile(source['spaced']).schema_arrow.names)
    if not needed<=actual:raise RuntimeError('Receipt cohort schema is missing '+str(sorted(needed-actual)))
    modules=[UPSTREAM/'code'/n for n in ('performance_histories.py','performance_cache.py')]
    lineage=[{k:r[k] for k in ('month','shard','sha256','rows')} for r in source['parts']]
    hdef=feature_cache.definition('monthly_behavior_events_v1',dict(parts=lineage,authors=binding['author_ids'],counts=list(audit.COUNTS)),modules)
    mdef=feature_cache.definition('main_keys_and_future_choices_v1',dict(panels=[r['sha256'] for r in source['panels']]),modules)
    shared=project/CACHE_REL
    binding.update(entry=str(root),entry_config=conf,source=source,
        histories=[str(shared/'history_index'/io.cfgsha(hdef)/m) for m in MONTHS],
        futures=[str(shared/'main_index'/io.cfgsha(mdef)/f'{k:02}') for k in range(len(source['panels']))],
        history_conf=io.cfgsha(hdef),main_conf=io.cfgsha(mdef))
    return binding

def selected(d,mask):return {k:v[mask] for k,v in d.items()}

def checked_columns(path,required):
    missing=set(required)-set(pq.ParquetFile(path).schema_arrow.names)
    if missing:raise RuntimeError(str(path)+' lacks required fields: '+str(sorted(missing)))

def stage(job,producer,deps):return stable_stage(Path(job['output']),job['conf'],producer,deps)[1]
