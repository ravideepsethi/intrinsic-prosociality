"""Read only the completed receipt cache; no reconstruction or source scans."""
from common import *
from concurrent.futures import ThreadPoolExecutor

DERIVED='''ln(1+pre_games_30d) log_pre_games,ln(1+fair_90) log_fair90,
 CASE WHEN fair_90>0 THEN kind_90::DOUBLE/fair_90 ELSE 0 END prior_kind_rate,
 (fair_90>0)::INT fair_history_present,ln(1+disconnect_90) log_disconnect90,
 ln(1+receipt_90) log_receipt90,ln(1+claim_90) log_claim90,
 CASE WHEN tc_base_s+40*tc_inc_s<180 THEN 0 WHEN tc_base_s+40*tc_inc_s<480 THEN 1
 WHEN tc_base_s+40*tc_inc_s<1500 THEN 2 ELSE 3 END speed_class,
 CASE WHEN board_cp<0 THEN 0 WHEN board_cp<100 THEN 1 WHEN board_cp<300 THEN 2 ELSE 3 END band'''
COLS=['row_id','recipient_id','opponent_id','outcome_opponent','reached','y','received','month_code',
 'recipient_rating','opponent_rating','adjusted_7d','expected_7d','chooser_color',
 'giver_cost','recipient_benefit','giver_rd','recipient_rd','board_cp','ply','giver_clock',
 'recipient_clock','log_pre_games','log_fair90','prior_kind_rate','fair_history_present',
 'log_disconnect90','log_receipt90','log_claim90','speed_class','band']

def bind_cache(project,work,threads,authority=None):
    a=authority or read(PACKAGE/'authority/parent.json')
    root=Path(project)/a['parent_relative_root'];key=a['parent_key']
    if digest(read(root/'config.json'))!=key:raise RuntimeError('Parent configuration hash changed')
    if read(root/'config.json')['package_sha256']!=a['parent_package_manifest_sha256']:
        raise RuntimeError('Parent executed package differs')
    authenticate(root/'report/REPORT_MANIFEST.json',work,a['parent_report_manifest_sha256'])
    inventory=read(root/'report/REPORT_MANIFEST.json')
    for name in ('summary.json','receipt_cohort_audit.csv','secondary_dose_estimates.csv','secondary_dose_summaries.json'):
        rec=next(x for x in inventory if x['path']==name)
        authenticate(root/'report'/name,work,rec['sha256'],rec['bytes'])
    summary=read(root/'report/summary.json')
    if summary['status']!='COMPLETE' or summary['run_key']!=key or summary['secondary_blocked_months']:
        raise RuntimeError('The pinned receipt run is not complete and verified')
    ids=read(root/'binding_PRIVATE.json')['author_ids']
    if set(ids)!=set(AUTHORS) or len(set(ids.values()))!=2:raise RuntimeError('Parent author identities unavailable')
    with (root/'report/receipt_cohort_audit.csv').open() as f:counts={r['month']:int(r['rows']) for r in csv.DictReader(f)}
    if set(counts)!=set(MONTHS):raise RuntimeError('Parent month audit incomplete')
    paths=[];records=[]
    for month in MONTHS:
        folder=root/'months'/month;done=read(folder/'_DONE.json')
        if done['key']!=key:raise RuntimeError('Wrong month checkpoint: '+month)
        for name in ('dose.parquet','secondary_status.json','receipt_audit.json','payoff_audit.json'):
            match=[r for r in done['files'] if r['path']==name]
            if len(match)!=1:raise RuntimeError('Missing parent checkpoint member: '+month+'/'+name)
            r=match[0];records.append(dict(path=str(folder/name),sha256=r['sha256'],bytes=r['signature']['bytes']))
        paths.append(str(folder/'dose.parquet'))
    def verify(r):authenticate(r['path'],work,r['sha256'],r['bytes'])
    with ThreadPoolExecutor(max_workers=min(4,threads)) as pool:list(pool.map(verify,records))
    for month,path in zip(MONTHS,paths):
        folder=Path(path).parent;s=read(folder/'secondary_status.json');r=read(folder/'receipt_audit.json')
        if s['status']!='VERIFIED' or s.get('rows_removed')!=0 or r.get('distinct_invalid_rows',0)!=0:
            raise RuntimeError('Parent receipt audit no longer verifies: '+month)
        if pq.ParquetFile(path).metadata.num_rows!=counts[month]:raise RuntimeError('Monthly receipt count changed: '+month)
    answer=dict(parent_key=key,paths=paths,source_files=records,author_ids=ids,expected=a,
                source_binding_sha256=digest(records),parent_root=str(root))
    write(Path(work)/'binding_PRIVATE.json',answer)
    return answer

def open_data(c,binding):
    c.execute('CREATE VIEW raw AS SELECT * FROM '+scan(binding['paths']))
    authors=','.join(str(int(x)) for x in binding['author_ids'].values())
    bad=c.execute(f'''SELECT count(*) FROM raw WHERE
      recipient_id IS NULL OR opponent_id IS NULL OR recipient_id=opponent_id
      OR recipient_id IN ({authors}) OR opponent_id IN ({authors})
      OR recipient_id IS DISTINCT FROM panel_recipient OR opponent_id IS DISTINCT FROM panel_chooser
      OR received IS DISTINCT FROM panel_kind OR NOT coalesce(panel_kind OR panel_claim,false)
      OR panel_kind AND panel_claim OR panel_fair IS DISTINCT FROM TRUE
      OR complete90 IS DISTINCT FROM TRUE OR anchor_ms+{90*DAY}>={PANEL_END}
      OR anchor_ms IS NULL OR archive_start_ms IS NULL OR anchor_ms<archive_start_ms
      OR anchor_ms IS DISTINCT FROM panel_anchor OR archive_start_ms IS DISTINCT FROM panel_start
      OR NOT coalesce(y IN (0,1) AND reached IN (0,1) AND y<=reached,false)
      OR NOT coalesce(isfinite(board_cp) AND board_cp>=-100,false)
      OR NOT coalesce(isfinite(giver_rd) AND isfinite(recipient_rd) AND isfinite(giver_cost) AND isfinite(recipient_benefit)
        AND giver_rd>0 AND recipient_rd>0 AND giver_cost>0 AND recipient_benefit>0,false)
      OR NOT coalesce(chooser_color IN ('white','black'),false)
      OR (reached=1 AND (outcome_opponent IS NULL OR outcome_opponent<0 OR outcome_opponent=recipient_id
        OR outcome_opponent=opponent_id OR outcome_opponent IN ({authors})
        OR outcome_t IS NULL OR outcome_start IS NULL OR outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY} OR outcome_start<=anchor_ms))''').fetchone()[0]
    if bad:raise RuntimeError(f'{bad} invalid receipt, identity, position or outcome rows; no rows dropped')
    row=c.execute('''SELECT count(*),count(DISTINCT row_id),count(DISTINCT game_id),
      count(DISTINCT recipient_id),sum(received::INT),count(*) FILTER(WHERE giver_rd<=110 AND recipient_rd<=110),
      sum(received::INT) FILTER(WHERE giver_rd<=110 AND recipient_rd<=110) FROM raw''').fetchone()
    a=binding['expected'];want=(a['expected_rows'],)*3+(a['expected_recipients'],a['expected_grants'],a['expected_rd110_rows'],a['expected_rd110_grants'])
    if tuple(row)!=want:raise RuntimeError('Receipt sample/count/uniqueness reconciliation failed: '+str(row))
    c.execute('CREATE VIEW enriched AS SELECT *, '+DERIVED+' FROM raw')
    return dict(rows=row[0],recipients=row[3],grants=row[4],rd110_rows=row[5],rd110_grants=row[6])

def load_scope(c,scope):
    where='TRUE' if scope=='all_rd' else 'giver_rd<=110 AND recipient_rd<=110'
    if scope=='within':where='recipient_id IN (SELECT recipient_id FROM enriched GROUP BY recipient_id HAVING count(*)>=2)'
    return arrays(c.execute('SELECT '+','.join(COLS)+' FROM enriched WHERE '+where+' ORDER BY row_id').to_arrow_table())

def row_hash(d):return hashlib.sha256(np.asarray(d['row_id'],dtype='<i8').tobytes()).hexdigest()
