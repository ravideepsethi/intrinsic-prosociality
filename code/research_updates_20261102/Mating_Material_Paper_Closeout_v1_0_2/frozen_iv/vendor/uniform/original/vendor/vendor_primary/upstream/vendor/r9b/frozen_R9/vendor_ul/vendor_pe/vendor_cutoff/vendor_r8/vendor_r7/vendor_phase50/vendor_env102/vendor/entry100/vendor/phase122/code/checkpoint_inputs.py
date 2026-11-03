"""Read only the completed 25% publication, never the live download journal."""
from cached_common import *
import phase_inputs as old
import phase_recovery as recovery
import shutil

PERCENT=25

def authenticate_checkpoint(a,up):
    phase10=old.authenticate_phase(a,up)
    root=Path(phase10['root']);conf=phase10['config_sha256'];result=root/'phase_results/25'
    if not (result/'ANALYSIS_INPUTS_PRIVATE.json').is_file():
        raise RuntimeError('25% snapshot not published yet. Wait for CHECKPOINT_025_SAVED; leave downloader running.')
    authority=io.load(PACKAGE/'evidence/checkpoint_authority.json')
    controller=io.cfgsha(dict(version='1.0.0',package_sha256=authority['continuous_package_sha'],inherited_config=conf,checkpoints=[25,50,75,100]))
    receipt=root/'continuous_v100'/controller[:12]/'REPORT_025_DONE.json'
    if not receipt.is_file():raise RuntimeError('25% publication marker missing; wait for CHECKPOINT_025_SAVED')
    r=io.load(receipt)
    if r['controller_conf']!=controller:raise RuntimeError('25% publication controller mismatch')
    io.checked(result/'ANALYSIS_INPUTS_PRIVATE.json',r['inputs_sha256'])
    io.checked(result/'report/REPORT_MANIFEST.json',r['manifest_sha256'])
    for item in io.load(result/'report/REPORT_MANIFEST.json'):
        io.checked(io.child(result/'report',item['path']),item['sha256'],item['bytes'])
    target=root/'plan/targets_25.parquet';binding=io.cfgsha([conf,25,io.sha(target)])
    finished=root/'download/25/finished';got=io.complete(finished,binding)
    if got is None:raise RuntimeError('25% request band is not complete')
    merged=result/'merged'
    if io.complete(merged,io.cfgsha([conf,25])) is None:raise RuntimeError('25% merged metadata is incomplete')
    manifest=io.load(result/'ANALYSIS_INPUTS_PRIVATE.json');summary=io.load(result/'report/summary.json')
    expected=dict(through_percent=25,fixed_denominator=up['ledgers'],upstream_manifest=up['manifest'],
        additional_frame_selection_sql=selection_sql(25),merged_candidate_metadata=str(merged/'metadata.parquet'),
        original_cached_metadata=up['manifest']['original_cached_metadata'],
        full_historical_and_prospective_anchor_stream_required=True,all_frame_rows_preserved=True,final_sample_and_rules_unchanged=True)
    for k,v in expected.items():
        if manifest.get(k)!=v:raise RuntimeError('25% manifest mismatch: '+k)
    planrow=next(v for v in io.load(root/'plan/summary.json')['phases'] if v['through_percent']==25)
    for k,v in planrow.items():
        if summary.get(k)!=v:raise RuntimeError('25% denominator changed: '+k)
    if summary['requested']!=planrow['cumulative_targets'] or not summary.get('all_requested_ids_accounted'):
        raise RuntimeError('25% target accounting incomplete')
    if got['requested']!=pq.ParquetFile(target).metadata.num_rows:raise RuntimeError('25% band count mismatch')
    return dict(root=str(root),config_sha256=conf,summary=summary,metadata=str(merged/'metadata.parquet'),
        manifest_sha256=io.sha(result/'ANALYSIS_INPUTS_PRIVATE.json'),publication_sha256=io.sha(receipt),phase10=phase10,
        receipts={str(f.relative_to(root)):io.sha(f) for f in (finished/'_DONE.json',merged/'_DONE.json')})

def coverage_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([job['ledger']])+' f WHERE '+selection_sql(25))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq(job['metadata']))
            ready=original_plan.readiness_sql()
            c.execute("CREATE TEMP TABLE disposition AS SELECT f.game_id,CASE WHEN f.local_eligibility<>'POTENTIALLY_ELIGIBLE' THEN 'LOCAL_RULE_EXCLUSION' ELSE ("+ready+") END AS disposition FROM f LEFT JOIN m USING(game_id)")
            counts=dict(c.execute('SELECT disposition,count(*) FROM disposition GROUP BY 1').fetchall())
            if sum(counts.values())!=c.execute('SELECT count(*) FROM f').fetchone()[0]:raise RuntimeError('Metadata join changed selected denominator')
            unknown="disposition NOT IN ('LOCAL_RULE_EXCLUSION','CACHED_NONPOOL','CACHED_POOL_METADATA')"
            unresolved=io.copy(c,'SELECT * FROM disposition WHERE '+unknown+' ORDER BY game_id',tmp/'unresolved_PRIVATE.parquet')
            io.copy(c,'SELECT game_id,retrieval_rank FROM f ORDER BY game_id',tmp/'membership_PRIVATE.parquet')
            fields='''f.game_id,f.utc_ms AS archive_start_ms,m.anchor_ms,f.recipient_id,f.opponent_id,
              CASE WHEN f.recipient_color='white' THEN m.white_rating ELSE m.black_rating END AS recipient_rating,
              CASE WHEN f.recipient_color='white' THEN m.black_rating ELSE m.white_rating END AS opponent_rating,
              CASE WHEN f.recipient_color='white' THEN m.white_username ELSE m.black_username END AS recipient_username,
              CASE WHEN f.recipient_color='white' THEN m.black_username ELSE m.white_username END AS opponent_username,
              m.tc_base_s,m.tc_inc_s,m.status,f.n7_author_clean AS expected_n7'''
            c.execute('CREATE VIEW pool AS SELECT '+fields+',f.speed_partition,'+str(core.MONTHS.index(job['month']))+
                "::BIGINT month_code FROM f JOIN m USING(game_id) JOIN disposition d ON f.game_id=d.game_id WHERE d.disposition='CACHED_POOL_METADATA'")
            n=io.copy(c,'SELECT * EXCLUDE(speed_partition) FROM pool ORDER BY game_id',tmp/'pool.parquet')
            if c.execute('SELECT count(DISTINCT game_id) FROM pool').fetchone()[0]!=n:raise RuntimeError('Duplicate game in pool')
            endings=[dict(month=job['month'],status=s,speed=sp,rows=k) for s,sp,k in c.execute('SELECT status,speed_partition,count(*) FROM pool GROUP BY 1,2 ORDER BY 1,2').fetchall()]
            info=dict(month=job['month'],selected_frame_rows=sum(counts.values()),pool_rows=n,
                ordinary_rows=sum(r['rows'] for r in endings if r['status'] in core.NARROW),unresolved_rows=unresolved,
                dispositions=counts,ending_counts=endings)
            io.js(tmp/'coverage.json',info);return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,[job['ledger']]+job['metadata'])[1]

def check_quarantine(a,up,phase,coverage_root,root,conf,memory):
    # Only the already reviewed identity can be excluded. Additional missing rows
    # stop after a coverage-only report; they are not automatically quarantined.
    if not recovery.reuse_v101_quarantine(a,up,phase['phase10'],root,conf):
        raise RuntimeError('Reviewed one-record quarantine audit is unavailable')
    paths=[str(coverage_root/m/'unresolved_PRIVATE.parquet') for m in ex.MONTHS]
    c=io.conn(root.parent/'quarantine_check_spill',memory,1)
    try:
        rows=c.execute('SELECT game_id,disposition FROM '+io.parq(paths)+' ORDER BY game_id').fetchall()
        oldrows=c.execute('SELECT game_id FROM '+io.parq([root/'frame_record_PRIVATE.parquet'])).fetchall()
        if len(rows)!=1 or rows[0][1]!='CACHE_CONFLICT_OR_PRIOR_FLAG' or [(rows[0][0],)]!=oldrows:
            raise RuntimeError('Additional or changed unresolved 25% metadata; inspect coverage report. No new exclusions authorized by this runner.')
        pooled=c.execute('SELECT count(*) FROM '+io.parq([str(coverage_root/m/'pool.parquet') for m in ex.MONTHS])+' WHERE game_id='+io.lit(rows[0][0])).fetchone()[0]
        if pooled:raise RuntimeError('Quarantined row entered retained sample')
    finally:finish_connection(c,root.parent/'quarantine_check_spill')

def prior_analysis(a,up,phase,source):
    auth=io.load(PACKAGE/'evidence/checkpoint_authority.json');conf=auth['phase10_analysis_conf']
    root=a.project_root/'derived/replication/run2_phase_analysis_v110_PRIVATE'/conf[:12]
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=conf or config['code_sha256']!=auth['phase10_code_sha'] or config['phase']!=phase['phase10'] or config['local_receipts']!=up['input_receipts']:
        raise RuntimeError('Completed 10% analysis binding changed')
    io.checked(root/'report/summary.json',auth['phase10_summary_sha'])
    if io.cfgsha(io.load(root/'INPUTS_PRIVATE.json'))!=io.cfgsha(source):raise RuntimeError('10% research sources differ from 25% sources')
    if io.complete(root/'assembled',conf) is None:raise RuntimeError('Completed 10% samples unavailable')
    return dict(root=str(root),conf=conf)

def compare_samples(c,new,old,label):
    c.execute('CREATE OR REPLACE VIEW a AS SELECT * FROM '+io.parq([new]))
    c.execute('CREATE OR REPLACE VIEW b AS SELECT * FROM '+io.parq([old]))
    an,au=c.execute('SELECT count(*),count(DISTINCT game_id) FROM a').fetchone()
    bn,bu=c.execute('SELECT count(*),count(DISTINCT game_id) FROM b').fetchone()
    if an!=bn or au!=an or bu!=bn:raise RuntimeError(label+' row count/identity differs')
    if c.execute('SELECT count(*) FROM a FULL JOIN b USING(game_id) WHERE a.game_id IS NULL OR b.game_id IS NULL').fetchone()[0]:raise RuntimeError(label+' games changed')
    schema=pq.ParquetFile(old).schema_arrow;names=pq.ParquetFile(new).schema_arrow.names
    if not set(schema.names)<=set(names):raise RuntimeError(label+' fields missing')
    terms=[]
    for field in schema:
        k=field.name
        if k in ('row_id','original_row_id'):continue
        expr=f'a."{k}" IS DISTINCT FROM b."{k}"'
        if pa.types.is_floating(field.type):expr+=' AND NOT (a."'+k+'" IS NOT NULL AND b."'+k+'" IS NOT NULL AND abs(a."'+k+'"-b."'+k+'")<=2e-11+1e-10*abs(b."'+k+'"))'
        terms.append('('+expr+')')
    if c.execute('SELECT count(*) FROM a JOIN b USING(game_id) WHERE '+' OR '.join(terms)).fetchone()[0]:raise RuntimeError(label+' frozen features changed')
    return dict(label=label,rows=an,game_identity_and_all_features_reproduced=True,row_ids_rebound=True)

def split_samples(assembled,memberships,prior,root,conf,memory):
    from phase_features import SPECS
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1);checks=[];accounting={}
        try:
            c.execute('CREATE VIEW membership AS SELECT * FROM '+io.parq(memberships))
            if c.execute('SELECT count(*)-count(DISTINCT game_id) FROM membership').fetchone()[0]:raise RuntimeError('Duplicate membership IDs')
            for family in SPECS:
                full=assembled/(family+'_new_phase25.parquet')
                c.execute('CREATE OR REPLACE VIEW fullsample AS SELECT * FROM '+io.parq([full]))
                if c.execute('SELECT count(*) FROM fullsample ANTI JOIN membership USING(game_id)').fetchone()[0]:raise RuntimeError('Sample game outside selected frame')
                for label,where in [('new_phase10',"retrieval_rank<from_hex('"+threshold(10).hex()+"')"),('increment_10_25',"retrieval_rank>=from_hex('"+threshold(10).hex()+"')")]:
                    n=io.copy(c,'SELECT f.* FROM fullsample f JOIN membership USING(game_id) WHERE '+where+' ORDER BY f.row_id',tmp/(family+'_'+label+'.parquet'))
                    accounting[family+'_'+label]=dict(rows=n)
                if sum(accounting[family+'_'+s]['rows'] for s in ('new_phase10','increment_10_25'))!=pq.ParquetFile(full).metadata.num_rows:raise RuntimeError('Bands do not partition 25% sample')
                if prior:
                    checks.append(compare_samples(c,tmp/(family+'_new_phase10.parquet'),Path(prior['root'])/'assembled'/(family+'_new_phase10.parquet'),family+' phase10'))
                    checks.append(compare_samples(c,assembled/(family+'_old_author_clean.parquet'),Path(prior['root'])/'assembled'/(family+'_old_author_clean.parquet'),family+' old'))
                for label in ('new_phase25','old_author_clean','pooled'):
                    src=assembled/(family+'_'+label+'.parquet');dest=tmp/src.name
                    try:os.link(src,dest)
                    except OSError:shutil.copyfile(src,dest)
                    accounting[family+'_'+label]=dict(rows=pq.ParquetFile(src).metadata.num_rows)
            io.js(tmp/'bridge.json',dict(checks=checks,sample_counts=accounting,increment_independent_of_previous_games=True,
                increment_independent_of_players=False,reselection=False,phase_assignment='original full SHA256 rank'))
            return dict(sample_counts=accounting)
        finally:finish_connection(c,tmp/'spill')
    deps=memberships+[assembled/(f+'_'+s+'.parquet') for f in SPECS for s in ('new_phase25','old_author_clean','pooled')]
    if prior:deps += [Path(prior['root'])/'assembled'/(f+'_'+s+'.parquet') for f in SPECS for s in ('new_phase10','old_author_clean')]
    return stable_stage(root,conf,build,deps)
