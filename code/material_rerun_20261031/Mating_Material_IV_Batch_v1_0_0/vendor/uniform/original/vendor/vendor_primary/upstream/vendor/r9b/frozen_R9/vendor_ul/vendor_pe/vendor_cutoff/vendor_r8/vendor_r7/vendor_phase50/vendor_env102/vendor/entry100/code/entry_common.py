"""Frozen 25% dependencies; the new runner never calls upstream orchestration."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]
UPSTREAM=HERE/'vendor/phase122'
sys.path.insert(0,str(UPSTREAM/'code'))
from phase_features import *
import checkpoint_secondary as secondary
import performance_cache as feature_cache
import performance_histories as fast
from performance_runtime import Runtime
import hashlib,json,math,time,shutil,contextlib

VERSION='1.0.0'
COHORTS=('new_phase25','increment_10_25','new_phase10','old_author_clean','pooled')
MAIN_COHORTS=COHORTS[:3]
ENTRY_REL='derived/replication/run2_entry_diagnostics_v100_PRIVATE'
PARENT_REL='derived/replication/run2_phase25_analysis_v120_PRIVATE'
CACHE_REL='derived/replication/run2_feature_cache_v1_PRIVATE'
MODEL_COLUMNS=['row_id','recipient_id','opponent_id','recipient_rating','opponent_rating',
 'month_code','archive_start_ms','tc_base_s','tc_inc_s','pre_games_30d']+SCORE_COLS+COUNT_COLUMNS+ENTRY_COLUMNS
COMP_COLUMNS=['comp_'+s for s in SCORE_COLS]


def verify_package():
    manifests=[HERE/'PACKAGE_MANIFEST.sha256']+list((HERE/'vendor').rglob('PACKAGE_MANIFEST.sha256'))
    for manifest in manifests:
        for line in manifest.read_text().splitlines():
            digest,name=line.split('  ',1);io.checked(io.child(manifest.parent,name),digest)
    auth=io.load(HERE/'evidence/authority.json')
    io.checked(UPSTREAM/'PACKAGE_MANIFEST.sha256',auth['upstream_package_manifest_sha256'])


def checked_stage_files(root,conf,names):
    root=Path(root);receipt=io.load(root/'_DONE.json')
    if receipt['config_sha256']!=conf:raise RuntimeError('Wrong completed stage: '+str(root))
    out=[]
    for name in names:
        records=[r for r in receipt['files'] if r['path']==name]
        if len(records)!=1:raise RuntimeError('Missing/ambiguous receipt member: '+name)
        r=records[0];io.checked(io.child(root,name),r['sha256'],r['bytes']);out.append(dict(r))
    return out


def authenticate(project,parent=None):
    auth=io.load(HERE/'evidence/authority.json');conf=auth['config_sha256']
    root=Path(parent) if parent else project/PARENT_REL/conf[:12]
    root=root.expanduser().resolve()
    if not root.is_dir():raise RuntimeError('Completed 25% analysis not found: '+str(root))
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=conf:raise RuntimeError('Expected the reviewed completed 25% configuration')
    if config['code_sha256']!=auth['upstream_package_manifest_sha256']:raise RuntimeError('25% producer changed')
    io.checked(root/'report/summary.json',auth['summary_sha256'])
    summary=io.load(root/'report/summary.json')
    if summary['status']!='PHASE_025_AVAILABLE_CASE_ANALYSIS_COMPLETE':raise RuntimeError('25% analysis not complete')
    split=root/'split';records=checked_stage_files(split,conf,['entry_'+c+'.parquet' for c in COHORTS])
    source=io.load(root/'INPUTS_PRIVATE.json');ids=list(source['author_ids'].values())
    if set(source['author_ids'])!=set(AUTHORS) or len(set(ids))!=2:raise RuntimeError('Author identity binding changed')
    shared=project/CACHE_REL
    receipt=io.load(root/'scores/00/_DONE.json');scoreconf=receipt['cache_definition_sha256']
    definition=io.load(shared/'scores'/scoreconf/'0/definition.json')
    if io.cfgsha(definition)!=scoreconf or definition['source']['authors']!=ids:raise RuntimeError('Wrong author-clean score cache')
    if definition['kind']!='lag7_pair_excluded_scores_v1':raise RuntimeError('Wrong score definition')
    for name,digest in definition['code'].items():
        path=UPSTREAM/'code'/name
        if not path.exists():path=Path(num.__file__) if name=='iv_numerics.py' else path
        io.checked(path,digest)
    indexconf=definition['source']['index'];refconf=definition['source']['reference']
    reference=shared/'reference'/refconf/'models'
    checked_stage_files(reference,refconf,['clean.npy'])
    competitive_definition=feature_cache.definition('competitive_history_author_clean_v1',
        dict(pooled_definition=definition,cp_cutoff=-100,minimum_decisions=5),[Path(secondary.__file__)])
    bound=dict(parent=str(root),parent_config_sha256=conf,entry_files=records,
        score_definition=definition,score_definition_sha256=scoreconf,competitive_definition=competitive_definition,
        index_conf=indexconf,reference_conf=refconf,author_ids=ids,
        source_summary_sha256=auth['summary_sha256'],quarantine=summary['metadata_quarantine'])
    return bound


def index_auth_job(job):
    threads_one()
    rows=checked_stage_files(job['index'],job['index_conf'],['people.parquet','pairs.parquet','events.parquet'])
    return dict(shard=job['shard'],files=rows)


def prepare_queries(split,root,conf,ids):
    def build(tmp):
        cols=list(dict.fromkeys(['row_id']+feature_cache.BEHAVIOR_KEYS+SCORE_COLS))
        q=io.read(split/'entry_pooled.parquet',cols)
        if q['row_id'].null_count:raise RuntimeError('Missing query ID')
        a=arrays(q);design.row_digest(a['row_id'])
        if authors.author_mask(a['recipient_id'],a['opponent_id'],ids).any():raise RuntimeError('Author in completed entry sample')
        shard=num.user_hash(a['opponent_id'])%np.uint64(16)
        for s in range(16):io.table(tmp/f'{s:02}.parquet',q.filter(pa.array(shard==s)))
        return dict(rows=len(q))
    return stable_stage(root,conf,build,[split/'entry_pooled.parquet'])


def score_job(job):
    """The frozen competitive score producer, with an existing-index-only guard.

    Its io.stage call can only reuse the complete index checked here. No raw
    history paths are supplied and no index rebuilding is permitted.
    """
    if io.complete(job['index'],job['index_conf']) is None:
        raise RuntimeError('Required score index is incomplete; run the completed 25% package first')
    job=dict(job,index_job=dict(output=job['index'],conf=job['index_conf'],parts=[],memory=job['memory']))
    return secondary.score_job(job)


def assemble(split,scorepaths,root,conf,memory,threads):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,threads);support=[]
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scorepaths))
            if c.execute('SELECT count(*)-count(DISTINCT row_id) FROM s').fetchone()[0]:raise RuntimeError('Duplicate score rows')
            for cohort in COHORTS:
                src=split/('entry_'+cohort+'.parquet')
                c.execute('CREATE OR REPLACE VIEW d AS SELECT * FROM '+io.parq([src]))
                n=c.execute('SELECT count(*) FROM d').fetchone()[0]
                if c.execute('SELECT count(*) FROM d JOIN s USING(row_id)').fetchone()[0]!=n:raise RuntimeError('Missing score rows')
                fields=','.join('d.'+v for v in MODEL_COLUMNS)+',s.* EXCLUDE(row_id)'
                n=io.copy(c,'SELECT '+fields+' FROM d JOIN s USING(row_id) ORDER BY row_id',tmp/(cohort+'.parquet'))
                good='comp_n_7d>=5 AND isfinite(comp_adjusted_7d) AND isfinite(comp_expected_7d)'
                goodn,good_events=c.execute('SELECT count(*),coalesce(sum(analysis_entry_90::BIGINT),0) FROM d JOIN s USING(row_id) WHERE '+good).fetchone()
                total_events=c.execute('SELECT sum(analysis_entry_90::BIGINT) FROM d').fetchone()[0]
                support.append(dict(cohort=cohort,all_entry_rows=n,competitive_supported_rows=goodn,unsupported_rows=n-goodn,
                    all_entry_events=total_events,supported_entry_events=good_events,support_share=goodn/n if n else None))
            io.js(tmp/'support.json',support);return dict(support=support)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,scorepaths+[split/('entry_'+v+'.parquet') for v in COHORTS])
