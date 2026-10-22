"""An explicit sensitivity to one unidentifiable pre-buffer record, not a repair."""
from util import *

def prepare(cat, run, key, audit):
    auth=load(ROOT/'authority/diagnostic_authority.json')
    observed=load(ROOT/'authority/diagnostic/KEY_AND_TIME.json')
    require(observed['target_key'].get('empty') is True and observed['target_time_kind']=='zero',
            'Reviewed diagnostic does not describe the intended missing-key record')
    affected=[r for r in audit['inventory'] if r.get('affected_choosers',0)]
    require(len(affected)==1 and affected[0]['speed']=='bullet' and affected[0]['month']=='2023-06'
            and affected[0]['invalid_needed_chooser_rows']==1 and affected[0]['affected_choosers']==1,
            'Affected history differs from the reviewed single pre-buffer record')
    source=next(r for r in cat['chronology'] if r['speed']=='bullet' and r['month']=='2023-06')
    source_auth=checked(source['path'],observed['source_sha256'])
    root=Path(run)/'PRIVATE/uncertain_prefix';root.mkdir(parents=True,exist_ok=True)
    c=db(root/'spill',1.5,1)
    try:
        c.execute('CREATE VIEW needed AS SELECT chooser FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
        c.execute('CREATE TEMP TABLE target AS SELECT * FROM '+scan(source['path'])+
            ' WHERE (utc_ms IS NULL OR utc_ms<=0) AND '
            '(white_id IN(SELECT chooser FROM needed) OR black_id IN(SELECT chooser FROM needed))')
        rows=c.execute('SELECT * FROM target').to_arrow_table().to_pylist()
        require(len(rows)==1,'Reviewed target count changed')
        r=rows[0]
        require(r['game_id']=='' and r['utc_ms']==0 and all(v is not None for v in r.values())
            and r['white_id']!=r['black_id'] and r['white_elo']>0 and r['black_elo']>0
            and r['result_code'] in (0,1,2),'Reviewed target contents changed')
        copy(c,'SELECT * FROM target',root/'target.parquet')
        count=copy(c,'SELECT DISTINCT chooser FROM (SELECT white_id chooser FROM target '
            'UNION ALL SELECT black_id chooser FROM target) JOIN needed USING(chooser)',root/'choosers.parquet')
        require(count==1,'Uncertainty is no longer confined to one analysis chooser')
    finally:c.close();shutil.rmtree(root/'spill',ignore_errors=True)
    unchanged([source_auth])
    report=dict(status='READY_FOR_SENSITIVITY_TIMESTAMP_STILL_UNRESOLVED',
        source_sha256=source_auth['sha256'],uncertain_source_records=1,affected_analysis_choosers=1,
        source_partition='bullet/2023-06',history_buffer_starts='2023-10-01',
        scenarios=['valid_timestamp_history','include_undated_june_record'],
        account_exclusions=0,focal_opportunity_exclusions_from_uncertainty=0,
        timestamp_imputations=0,source_files_modified=False,api_requests=0,
        assumption='Inclusion scenario treats the malformed record as one additional June 2023 bullet start, based on its archive partition. It is not a recovered game.',
        session_argument='Either omission or a June start is separated from the October history buffer by more than every session threshold; the record cannot change within-buffer session positions.',
        scope='Two explicit interpretations, not a mathematical bound over arbitrary source corruption. The strict timestamp-verified parent specification remains unresolved.')
    js(Path(run)/'report/UNCERTAINTY.json',report)
    commit(root,digest([key,source_auth['sha256']]),source=source_auth)
    return report

def source_is_uncertain(run, source_path):
    root=Path(run)/'PRIVATE/uncertain_prefix';receipt=root/'_DONE.json'
    if not receipt.is_file():return False
    r=load(receipt)
    if str(source_path)!=r['source']['path']:return False
    require(snapshot(source_path)==r['source']['stat'],'Uncertain source changed after authentication')
    require(cached(root,r['key']),'Uncertain-record receipt damaged')
    return True

def valid_prefix_sql(source, needed, run, is_uncertain):
    base='SELECT white_id,black_id,utc_ms,game_id,archive_ordinal FROM '+scan(source)+\
        ' WHERE white_id IN(SELECT chooser FROM '+needed+') OR black_id IN(SELECT chooser FROM '+needed+')'
    if not is_uncertain:return base
    target=Path(run)/'PRIVATE/uncertain_prefix/target.parquet'
    # Exact private key tuple plus ordinal; unchanged source SHA has already been verified.
    return ('WITH relevant AS ('+base+'), target AS (SELECT * FROM '+scan(target)+') '
        'SELECT r.* FROM relevant r WHERE NOT EXISTS (SELECT 1 FROM target t WHERE '
        'r.archive_ordinal IS NOT DISTINCT FROM t.archive_ordinal AND r.game_id IS NOT DISTINCT FROM t.game_id '
        'AND r.utc_ms IS NOT DISTINCT FROM t.utc_ms AND r.white_id=t.white_id AND r.black_id=t.black_id)')
