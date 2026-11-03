#!/usr/bin/env python3
"""Build the agreed pool/observed-nonadjacency sample and descriptive comparisons."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import zipfile
from collections import defaultdict

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from audit_io import (require, log, sha, canonical_sha, signature, read_json, json_bytes,
    write_bytes, write_json, relative_file, inspected_file, unchanged, report_bytes,
    lit, pq_sql, records, describe, copy_parquet, stage, verify_stage, lock,
    heartbeat, small_parquet)
from sample_rules import (CANDIDATE, NONADJACENT, MISSING, AMBIGUOUS, STATUSES,
    SAMPLES, COUNT_COLUMNS, CONTINUOUS, mask_query, counts_sql, summary_query,
    board_case, ply_case, presence_query, distinct_counts_query)

VERSION = '1.0.0'
ALGORITHM = 'pool-observed-nonadjacency-main-sample-20260909-v100'
JOIN_ALGORITHM = 'source-join-observed-adjacency-no-endtime-20260909-v100'
EVIDENCE_SHA = {
    'SOURCE_UNION_REPORT.zip': 'a801d1000109124d888874c1d4bfdaca95045c5f150b7398a86a0bb55db7b680',
    'SOURCE_JOIN_REPORT.zip': '3a661bae8d5a912e197c22d35ebc6c6c750505760fbc6b516cbabba4a3596254',
    'PANEL_AUTHORITY_REPORT.zip': '0a1a62f6efda4746f034a45c7fc82f2f44735cf1c98bde77ea3a3ddbca4f8d10',
}
CERT_SHA = '8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7'
CERT_PRODUCER = '0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e'
JOIN_PRODUCER = '762ca0951d02adc8f364013a1b79cdc3c7b9349f34fe0977fa6dd1bc4d153d37'
JOIN_LOGIC = '95807c5fe32bcdba13e05307b6ce7fcfb57f5c57eca29ecf6495bda92a16ad04'
MONTHS = [f'{y}-{m:02}' for y in (2023,2024,2025) for m in range(1,13)
          if '2023-11' <= f'{y}-{m:02}' <= '2025-10']
EXPECTED_COUNTS = {'original':47587020, 'pool':44138221, 'main_pool_nonadjacent':41534331,
                   'pool_restore_missing_previous':41889951}
JOIN_REQUIRED = {
    'game_id':'VARCHAR', 'month':'VARCHAR', 'source':'VARCHAR', 'source_provenance':'VARCHAR',
    'p1':'BIGINT', 'p2':'BIGINT', 'focal_start_ms':'BIGINT', 'focal_mapping_ok':'BOOLEAN',
    'previous_classification_status':'VARCHAR', 'previous_game_id':'VARCHAR',
    'mutual_previous_same_pair':'BOOLEAN', 'mutual_previous_observed':'BOOLEAN',
    'previous_start_order_ambiguous':'BOOLEAN',
}
BASE_COLUMNS = ['game_id','month','chooser_user_id','disconnected_user_id','utc_ms','api_status',
                'outcome_kind_draw','engine_eval_cp_disconnected','chooser_elo','disconnected_elo',
                'chooser_draw_payoff_v2','ply_count','api_speed','disconnected_clock_last_obs_s']


def aggregate(rows, keys, values=('rows',)):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        dest = result.setdefault(key, {k:v for k,v in zip(keys,key)})
        for column in values:
            dest[column] = dest.get(column,0)+row[column]
    return [result[k] for k in sorted(result)]


def load_evidence(bundle):
    data = {name:report_bytes(bundle/'evidence'/name,digest) for name,digest in EVIDENCE_SHA.items()}
    source_bytes = data['SOURCE_UNION_REPORT.zip']['SOURCE_UNION_REPORT.json']
    source = json.loads(source_bytes)
    join_data = data['SOURCE_JOIN_REPORT.zip']
    summary, success = json.loads(join_data['SUMMARY.json']), json.loads(join_data['_SUCCESS.json'])
    auth = json.loads(join_data['INPUT_AUTHENTICATION.json'])
    previous = json.loads(join_data['source_by_previous_status.json'])
    # This older report supplies only Stage07 file identities. Its incomplete
    # source classifications are never used; all source labels come from the union.
    panel = json.loads(data['PANEL_AUTHORITY_REPORT.zip']['SOURCE_RECOVERY_REPORT.json'])
    require(source['status']=='SOURCE_UNION_24M_CERTIFIED_OK'
            and source['global_qa']=={'rows':47587020,'unique_ids':47587020,'null_rows':0}, 'Wrong source union authority')
    require(summary['status']==success['status']=='REMATCH_SOURCE_JOIN_COMPLETE_TIMING_OPEN', 'Incomplete source/adjacency join')
    require(auth['source_report_sha256']==hashlib.sha256(source_bytes).hexdigest(), 'Join references a different source union')
    require(auth['all_consumed_source_and_census_files_full_sha256_verified']
            and auth['consumed_census_partitions']==128, 'Join input authentication incomplete')
    require(success['summary_sha256']==hashlib.sha256(join_data['SUMMARY.json']).hexdigest(), 'Join summary is unbound')
    for item in success['public_files']:
        require(hashlib.sha256(join_data[item['name']]).hexdigest()==item['sha256'], 'Join report receipt mismatch')
    require(aggregate(previous,['month','source'])==aggregate(source['source_counts'],['month','source']), 'Join/source monthly counts disagree')
    require([r['month'] for r in source['month_coverage']]==MONTHS, 'Source coverage is not the full 24 months')
    require(all(r['rows']==r['source_verified'] and r['missing_ids']==r['extra_ids']==0 for r in source['month_coverage']), 'Source coverage is incomplete')
    require(panel['baseline_ok'] and panel['global_distinct_game_ids']==47587020, 'Stage07 panel authority failed')
    panel_receipts = {r['month']:r for r in panel['panel_receipts']}
    require(len(panel['panel_receipts'])==24 and sorted(panel_receipts)==MONTHS, 'Panel file receipts incomplete')
    families = json.loads(join_data['CACHE_METADATA_SCHEMA_REPORT.json'])['schema_families']
    candidates = [r['schema'] for r in families if r['files']==24 and any(c['name']=='chooser_user_id' for c in r['schema'])]
    require(len(candidates)==1, 'Missing/ambiguous full Stage07 schema')
    return {'source':source,'join':summary,'join_success':success,'join_bytes':join_data,
            'previous':previous,'panel_receipts':panel_receipts,'panel_schema':candidates[0]}


def production_plan(bundle, project):
    e = load_evidence(bundle)
    old_root = Path('/Volumes/XT_Pro/lichess_kindness')
    source_root = project/Path(e['source']['private_output_root']).relative_to(old_root)
    join_root = project/'output/rematch_source_join_v100/20260908T031408Z_6459_source_union_20260909'
    panel_root = project/'derived/replication/analysis_panel_24m_sf100k'
    metadata = []
    for name in ('SUMMARY.json','_SUCCESS.json','INPUT_AUTHENTICATION.json'):
        metadata.append(inspected_file(join_root/name, hashlib.sha256(e['join_bytes'][name]).hexdigest()))
    contract_path = join_root/'private/INPUT_CONTRACT.json'
    metadata.append(inspected_file(contract_path))
    old_contract = read_json(contract_path)
    require(canonical_sha(old_contract)==e['join_success']['input_contract_sha256'], 'Private join contract differs from uploaded receipt')
    require(old_contract['algorithm']==JOIN_ALGORITHM and old_contract['code_sha256']==JOIN_PRODUCER
            and old_contract['logic_sha256']==JOIN_LOGIC and old_contract['game_buckets']==128, 'Unexpected join producer/settings')
    ledger_path = join_root/'private/OUTPUT_CHECKPOINTS.json'
    metadata.append(inspected_file(ledger_path,e['join_success']['output_checkpoints_manifest_sha256']))
    ledger = read_json(ledger_path)
    require(len(ledger)==e['join_success']['output_checkpoints_count']==258, 'Join checkpoint inventory differs')
    require(len({r['path'] for r in ledger})==len(ledger), 'Duplicate join checkpoint paths')
    join_receipts = {r['path']:r for r in ledger if re.fullmatch(r'joined/gb_\d{4}/_DONE.json',r['path'])}
    require(set(join_receipts)=={f'joined/gb_{i:04d}/_DONE.json' for i in range(128)}, 'Incomplete joined game partitions')
    require({p.name for p in (join_root/'private/joined').glob('gb_*') if p.is_dir()}=={f'gb_{i:04d}' for i in range(128)}, 'Unexpected joined partition directories')
    entries = []; observed_previous = []
    for rel,item in sorted(join_receipts.items()):
        p = relative_file(join_root/'private',rel)
        metadata.append(inspected_file(p,item['sha256']))
        done = read_json(p)
        require(done['algorithm']==JOIN_ALGORITHM and done['contract_hash']==e['join_success']['input_contract_sha256'], 'Join partition contract differs')
        candidates = [r for r in done['files'] if r['path']=='source_adjacency.parquet']
        require(len(candidates)==1, 'Joined Parquet not uniquely listed')
        receipt = candidates[0]
        entries.append({'path':str(p.parent/'source_adjacency.parquet'),'sha256':receipt['sha256'],
                        'size_bytes':receipt['bytes'],'rows':done['rows'],'kind':'join','schema':JOIN_REQUIRED,'exact_schema':False})
        observed_previous.extend(done['tables']['source_by_previous_status'])
    require(aggregate(observed_previous,['month','source','classification_status'])==aggregate(e['previous'],['month','source','classification_status']), 'Joined partition status counts differ from report')
    metadata.append(inspected_file(source_root/'_SUCCESS.json'))
    local_source = read_json(source_root/'_SUCCESS.json')
    require(all(local_source.get(k)==v for k,v in e['source'].items()), 'Local source certificate differs')
    source_receipt = next(r for r in e['source']['outputs'] if r['filename']=='source_by_game_id_24m.parquet')
    original_source_path = str(Path(e['source']['private_output_root'])/source_receipt['filename'])
    require({r['path']:r['sha256'] for r in old_contract['input_bytes']}.get(original_source_path)==source_receipt['sha256'], 'Join was not bound to the completed source map')
    source_path = source_root/source_receipt['filename']
    entries.append({'path':str(source_path),'sha256':source_receipt['sha256'],'size_bytes':source_receipt['size_bytes'],
                    'rows':47587020,'kind':'source','schema':{r['name']:'VARCHAR' for r in e['source']['schema']},'exact_schema':True})
    metadata.append(inspected_file(panel_root/'_SUCCESS.json',CERT_SHA))
    cert = read_json(panel_root/'_SUCCESS.json')
    require(cert['status']=='STAGE07_24M_CERTIFIED_OK' and cert['script_sha256']==CERT_PRODUCER, 'Unexpected Stage07 certificate')
    require(all(cert['global_qa'].get(k)==v for k,v in e['source']['baseline_totals'].items()), 'Stage07 baseline differs')
    months = []
    for month in MONTHS:
        r = e['panel_receipts'][month]
        panel_path = project/Path(r['path']).relative_to(old_root)
        require(panel_path.is_file(),'Missing monthly panel: '+str(panel_path))
        src = [r for r in e['source']['source_counts'] if r['month']==month]
        statuses = [r for r in e['previous'] if r['month']==month]
        pool_status = {r['classification_status']:r['rows'] for r in statuses if r['source']=='pool'}
        expected = {'original':sum(x['rows'] for x in src),'pool':sum(x['rows'] for x in src if x['source']=='pool'),
                    'main_pool_nonadjacent':pool_status.get(NONADJACENT,0),
                    'pool_restore_missing_previous':pool_status.get(NONADJACENT,0)+pool_status.get(MISSING,0)}
        require(expected['original']==r['target_ids'], 'Panel/source monthly counts differ')
        entries.append({'path':str(panel_path),'sha256':r['sha256'],'size_bytes':panel_path.stat().st_size,
                        'rows':r['target_ids'],'kind':'panel','month':month,
                        'schema':{c['name']:c['type'] for c in e['panel_schema']},'exact_schema':True})
        months.append({'month':month,'panel_path':str(panel_path),'source_counts':src,'statuses':statuses,'expected_counts':expected})
    require({s:sum(m['expected_counts'][s] for m in months) for s,_ in SAMPLES}==EXPECTED_COUNTS, 'Main-sample count authority differs')
    return {'entries':entries,'metadata':metadata,'source_path':str(source_path),
            'join_paths':[r['path'] for r in entries if r['kind']=='join'],
            'source_root':str(source_root),'join_root':str(join_root),'panel_root':str(panel_root),
            'months':months,'previous':e['previous'],'source_counts':e['source']['source_counts'],
            'expected_counts':EXPECTED_COUNTS,'evidence_sha256':EVIDENCE_SHA}


def sql_type(t):
    if pa.types.is_string(t) or pa.types.is_large_string(t): return 'VARCHAR'
    names = {'bool':'BOOLEAN','int8':'TINYINT','int16':'SMALLINT','int32':'INTEGER','int64':'BIGINT',
             'float':'FLOAT','double':'DOUBLE','uint64':'UBIGINT','uint32':'UINTEGER'}
    return names.get(str(t),str(t))


def authenticate_entry(entry):
    actual = inspected_file(entry['path'],entry['sha256'])
    require(actual['size_bytes']==entry['size_bytes'],'Input size differs: '+entry['path'])
    pf = pq.ParquetFile(entry['path'])
    require(pf.metadata.num_rows==entry['rows'],'Input footer count differs: '+entry['path'])
    schema = {f.name:sql_type(f.type) for f in pf.schema_arrow}
    require(all(schema.get(k)==v for k,v in entry['schema'].items()),'Input columns/types differ: '+entry['path'])
    require(not entry['exact_schema'] or schema==entry['schema'],'Unexpected extra input columns: '+entry['path'])
    require(signature(entry['path'])==actual['signature'],'Input changed during schema check')
    return {**entry,'signature':actual['signature']}


def authenticate_inputs(plan,workers):
    result = list(plan['metadata'])
    with heartbeat('Authenticating joined/source/panel inputs'), ThreadPoolExecutor(max_workers=workers) as ex:
        jobs = [ex.submit(authenticate_entry,r) for r in plan['entries']]
        for i,future in enumerate(as_completed(jobs),1):
            result.append(future.result())
            if i%16==0 or i==len(jobs): log(f'Input hashes checked: {i}/{len(jobs)}')
    unchanged(result)
    return sorted(result,key=lambda r:r['path'])


def mask_validation(con,plan):
    qa = records(con,"""SELECT count(*) AS rows,count(DISTINCT game_id) AS unique_ids,
      count(*) FILTER(WHERE game_id IS NULL OR NOT regexp_full_match(game_id,'[A-Za-z0-9]{8}')) AS invalid_ids
      FROM j""")[0]
    require(qa=={'rows':plan['expected_counts']['original'],'unique_ids':plan['expected_counts']['original'],'invalid_ids':0},'Joined ID uniqueness/count failure')
    invalid = con.execute(f'''SELECT count(*) FROM j WHERE
      focal_mapping_ok IS DISTINCT FROM TRUE OR p1 IS NULL OR p2 IS NULL OR p1=p2 OR focal_start_ms IS NULL
      OR source IS NULL OR month IS NULL OR source_provenance IS NULL OR trim(source_provenance)=''
      OR previous_classification_status IS NULL OR previous_classification_status NOT IN ({','.join(lit(x) for x in STATUSES)})
      OR mutual_previous_observed IS NULL OR previous_start_order_ambiguous IS NULL
      OR ((previous_classification_status={lit(NONADJACENT)}) IS DISTINCT FROM (mutual_previous_same_pair IS FALSE))
      OR ((previous_classification_status={lit(CANDIDATE)}) IS DISTINCT FROM (mutual_previous_same_pair IS TRUE))
      OR ((previous_classification_status IN ({lit(MISSING)},{lit(AMBIGUOUS)})) IS DISTINCT FROM (mutual_previous_same_pair IS NULL))
      OR ((previous_classification_status={lit(AMBIGUOUS)}) IS DISTINCT FROM previous_start_order_ambiguous)
      OR (mutual_previous_same_pair IS TRUE AND mutual_previous_observed IS DISTINCT FROM TRUE)
      OR (mutual_previous_same_pair IS FALSE AND mutual_previous_observed IS DISTINCT FROM FALSE)
      OR (mutual_previous_observed AND (previous_game_id IS NULL OR previous_game_id=game_id))
      OR (NOT mutual_previous_observed AND previous_game_id IS NOT NULL)
      OR month IS DISTINCT FROM strftime(to_timestamp(focal_start_ms/1000.0),'%Y-%m')''').fetchone()[0]
    require(invalid==0,f'{invalid} invalid joined flag/identity/month rows')
    counts = records(con,'SELECT month,source,previous_classification_status AS classification_status,count(*) AS rows FROM j GROUP BY 1,2,3')
    require(aggregate(counts,['month','source','classification_status'])==aggregate(plan['previous'],['month','source','classification_status']),'Joined status counts differ from report')
    source_rows = con.execute('SELECT count(*) FROM s').fetchone()[0]
    require(source_rows==qa['rows'],'Source map row count differs')
    # Full-join comparison catches missing IDs in either direction and label/provenance changes.
    mismatch = con.execute('''SELECT count(*) FROM j FULL OUTER JOIN s USING(game_id)
      WHERE j.game_id IS NULL OR s.game_id IS NULL OR j.month IS DISTINCT FROM s.month
        OR j.source IS DISTINCT FROM s.source OR j.source_provenance IS DISTINCT FROM s.source_provenance''').fetchone()[0]
    require(mismatch==0,f'{mismatch} per-game source/ID/provenance mismatches')
    return {**qa,'invalid_joined_rows':invalid,'source_mismatches':mismatch}


def build_masks(con,plan,dest,contract):
    def produce(tmp):
        qa = mask_validation(con,plan)
        con.execute('CREATE OR REPLACE TEMP VIEW masks_to_write AS '+mask_query())
        n = copy_parquet(con,'SELECT *,month AS partition_month FROM masks_to_write',tmp/'parts','partition_month')
        require(n==plan['expected_counts']['original'],'Eligibility row loss')
        require({p.name for p in (tmp/'parts').glob('partition_month=*')}=={'partition_month='+m['month'] for m in plan['months']},'Eligibility months differ')
        write_json(tmp/'INPUT_QA.json',qa)
        return {'rows':n,'qa':qa}
    return stage(dest,contract,produce)


def month_mask_paths(mask_root,done,month):
    paths = [relative_file(mask_root,r['relative_path']) for r in done['files']
             if r['relative_path'].startswith('parts/partition_month='+month+'/') and r['relative_path'].endswith('.parquet')]
    require(bool(paths),'No eligibility files for '+month)
    return paths


def decorated(row):
    out = dict(row)
    out['kindness_pct'] = 100*row['kind_draws']/row['rows'] if row['rows'] else None
    out['fair_kindness_pct'] = 100*row['fair_kind_draws']/row['fair_rows'] if row['fair_rows'] else None
    out['fair_share_pct'] = 100*row['fair_rows']/row['rows'] if row['rows'] else None
    for name in CONTINUOUS:
        if name+'_n' in row:
            out[name+'_mean'] = row[name+'_sum']/row[name+'_n'] if row[name+'_n'] else None
            out[name+'_missing_or_nonfinite'] = row['rows']-row[name+'_n']
    return out


def build_month(con,m,mask_paths,dest,contract):
    def produce(tmp):
        con.execute('CREATE OR REPLACE TEMP VIEW p AS SELECT * FROM '+pq_sql([m['panel_path']]))
        con.execute('CREATE OR REPLACE TEMP VIEW e AS SELECT * FROM '+pq_sql(mask_paths))
        for view in ('p','e'):
            qa = records(con,f'''SELECT count(*) AS rows,count(DISTINCT game_id) AS unique_ids,
              count(*) FILTER(WHERE game_id IS NULL OR month IS DISTINCT FROM {lit(m['month'])}) AS invalid FROM {view}''')[0]
            require(qa=={'rows':m['expected_counts']['original'],'unique_ids':m['expected_counts']['original'],'invalid':0},m['month']+': monthly ID/month/count failure in '+view)
        mismatch = con.execute('''SELECT count(*) FROM p FULL OUTER JOIN e USING(game_id)
          WHERE p.game_id IS NULL OR e.game_id IS NULL OR p.month IS DISTINCT FROM e.month
            OR p.chooser_user_id IS DISTINCT FROM e.chooser_user_id
            OR p.disconnected_user_id IS DISTINCT FROM e.disconnected_user_id
            OR p.utc_ms IS DISTINCT FROM e.observed_start_ms''').fetchone()[0]
        require(mismatch==0,m['month']+': panel/eligibility ID, role, or start-time mismatch')
        invalid = con.execute("SELECT count(*) FROM p WHERE api_status IS DISTINCT FROM 'timeout' OR outcome_kind_draw IS NULL OR engine_eval_cp_disconnected IS NULL").fetchone()[0]
        require(invalid==0,m['month']+': invalid analysis outcome/evaluation/status')
        columns = ','.join('p.'+c for c in BASE_COLUMNS)
        con.execute('''CREATE OR REPLACE TEMP VIEW b AS SELECT '''+columns+''',e.source,
          e.previous_classification_status,e.main_exclusion_reason,e.eligible_pool,e.eligible_main,
          e.eligible_pool_restore_missing_previous FROM p JOIN e USING(game_id)''')
        source_counts = records(con,'SELECT source,'+counts_sql()+' FROM b GROUP BY source')
        require(aggregate(source_counts,['source'],COUNT_COLUMNS)==aggregate(m['source_counts'],['source'],COUNT_COLUMNS),m['month']+': source/outcome counts differ from authenticated union')
        summaries = [records(con,summary_query(sample,condition))[0] for sample,condition in SAMPLES]
        require({r['sample']:r['rows'] for r in summaries}==m['expected_counts'],m['month']+': sample membership count differs')
        main_path = tmp/'analysis_panel.parquet'
        n = copy_parquet(con,'SELECT p.* FROM p JOIN e USING(game_id) WHERE e.eligible_main',main_path)
        require(n==m['expected_counts']['main_pool_nonadjacent'],'Filtered panel row loss')
        require(describe(con,'SELECT * FROM p')==describe(con,'SELECT * FROM '+pq_sql([main_path])),'Filtered panel schema differs from Stage07')
        outqa = records(con,'SELECT count(*) AS rows,count(DISTINCT game_id) AS unique_ids FROM '+pq_sql([main_path]))[0]
        require(outqa=={'rows':n,'unique_ids':n},'Filtered panel uniqueness failure')
        con.execute('CREATE OR REPLACE TEMP VIEW written_main AS SELECT * FROM '+pq_sql([main_path]))
        wrong = con.execute('''SELECT count(*) FROM written_main w FULL OUTER JOIN
          (SELECT game_id FROM e WHERE eligible_main) x USING(game_id)
          WHERE w.game_id IS NULL OR x.game_id IS NULL''').fetchone()[0]
        require(wrong==0,'Written main panel has wrong ID set')
        written_counts = records(con,'SELECT '+counts_sql()+' FROM written_main')[0]
        expected_main = next(r for r in summaries if r['sample']=='main_pool_nonadjacent')
        require(written_counts=={k:expected_main[k] for k in COUNT_COLUMNS},'Written main outcomes do not reconcile')
        audit = tmp/'_audit'; audit.mkdir()
        presence_path = audit/'chooser_presence.parquet'
        copy_parquet(con,presence_query(),presence_path)
        con.execute('CREATE OR REPLACE TEMP VIEW month_presence AS SELECT * FROM '+pq_sql([presence_path]))
        chooser_counts = {r['sample']:r for r in records(con,distinct_counts_query('month_presence'))}
        monthly = [decorated({'month':m['month'],**r,**chooser_counts[r['sample']]}) for r in summaries]
        board = []; speeds = []
        for sample,condition in SAMPLES:
            board.extend(records(con,f"SELECT '{sample}' AS sample,{board_case()} AS board_state,{ply_case()} AS game_stage,{counts_sql()} FROM b WHERE {condition} GROUP BY 1,2,3"))
            speeds.extend(records(con,f"SELECT '{sample}' AS sample,coalesce(api_speed,'missing') AS speed,{counts_sql()} FROM b WHERE {condition} GROUP BY 1,2"))
        for cells in (board,speeds):
            collapsed = {r['sample']:r['rows'] for r in aggregate(cells,['sample'])}
            require(all(collapsed.get(sample,0)==m['expected_counts'][sample] for sample,_ in SAMPLES),'Descriptive group-count conservation failed')
        attrition = records(con,'SELECT main_exclusion_reason,'+counts_sql()+' FROM b GROUP BY 1')
        for rows in (board,speeds,attrition):
            for r in rows: r['month'] = m['month']
        data = {'month':m['month'],'sample_counts':monthly,'board_state_ply_counts':board,
                'speed_counts':speeds,'attrition_counts':attrition,
                'qa':{'panel_eligibility_mismatches':mismatch,'invalid_analysis_rows':invalid,
                      'written_main_id_mismatches':wrong,'written_main_rows':n,'original_panel_rows':m['expected_counts']['original']}}
        write_json(audit/'MONTH_SUMMARY.json',data)
        return data
    return stage(dest,contract,produce)


def finish_tables(con,plan,monthly,month_roots):
    small = [r for d in monthly for r in d['info']['sample_counts']]
    sums = COUNT_COLUMNS+[x+y for x in CONTINUOUS for y in ('_n','_sum')]
    global_counts = aggregate(small,['sample'],sums)
    chooser_paths = [p/'_audit/chooser_presence.parquet' for p in month_roots]
    con.execute('CREATE OR REPLACE TEMP VIEW all_presence AS SELECT chooser_user_id,bit_or(presence_bits) AS presence_bits FROM '+pq_sql(chooser_paths)+' GROUP BY chooser_user_id')
    distinct = {r['sample']:r for r in records(con,distinct_counts_query('all_presence'))}
    global_counts = [decorated({**r,**distinct[r['sample']]}) for r in global_counts]
    sample_order = {sample:i for i,(sample,_) in enumerate(SAMPLES)}
    global_counts.sort(key=lambda r:sample_order[r['sample']])
    require({r['sample']:r['rows'] for r in global_counts}==plan['expected_counts'],'Global sample counts differ')
    expected_all = {k:sum(r[k] for r in plan['source_counts']) for k in COUNT_COLUMNS}
    expected_pool = {k:sum(r[k] for r in plan['source_counts'] if r['source']=='pool') for k in COUNT_COLUMNS}
    for sample,expected in [('original',expected_all),('pool',expected_pool)]:
        got = next(r for r in global_counts if r['sample']==sample)
        require({k:got[k] for k in COUNT_COLUMNS}==expected,'Global baseline/source counts differ')
    lookup = {r['sample']:r for r in global_counts}
    for name in COUNT_COLUMNS+['choosers','fair_choosers','kind_choosers','fair_kind_choosers']:
        require(lookup['main_pool_nonadjacent'][name]<=lookup['pool_restore_missing_previous'][name]<=lookup['pool'][name]<=lookup['original'][name], 'Nested-sample conservation failure: '+name)
    board = aggregate([r for d in monthly for r in d['info']['board_state_ply_counts']],['sample','board_state','game_stage'],COUNT_COLUMNS)
    speeds = aggregate([r for d in monthly for r in d['info']['speed_counts']],['sample','speed'],COUNT_COLUMNS)
    attrition = aggregate([r for d in monthly for r in d['info']['attrition_counts']],['main_exclusion_reason'],COUNT_COLUMNS)
    return {'SAMPLE_COUNTS':global_counts,'MONTHLY_COUNTS':small,
            'BOARD_STATE_PLY_COUNTS':[decorated(r) for r in board],
            'SPEED_COUNTS':[decorated(r) for r in speeds],
            'ATTRITION_COUNTS':[decorated(r) for r in attrition],
            'MONTHLY_ATTRITION_COUNTS':[r for d in monthly for r in d['info']['attrition_counts']]}


def make_summary(report):
    lines = ['# Pool main-sample build','',report['status'],'',
             "Rule: `source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`.",'',
             '| Sample | Opportunities | Kind draws | Kindness % | Fair opportunities | Fair kindness % | Choosers |',
             '|---|---:|---:|---:|---:|---:|---:|']
    def pct(v): return 'NA' if v is None else f'{v:.4f}'
    for r in report['sample_counts']:
        lines.append(f"| {r['sample']} | {r['rows']:,} | {r['kind_draws']:,} | {pct(r['kindness_pct'])} | {r['fair_rows']:,} | {pct(r['fair_kindness_pct'])} | {r['choosers']:,} |")
    lines += ['', 'Chooser totals are deduplicated across months. Rates pool numerators and denominators.', '',
              'This certifies the stated observed-adjacency screen. Literal immediate-rematch timing has not been certified.',
              'The main panels preserve all Stage07 columns and retained values. Regression, dynamic-sequence, matching and figure rebuilds remain downstream work.', '']
    return '\n'.join(lines)


def save_report(report_root,report,tables):
    report_root.mkdir(parents=True,exist_ok=True)
    name = 'Pool_Main_Sample_24M_Report_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')+'_'+str(os.getpid())
    temp = report_root/('.partial_'+name); temp.mkdir()
    write_json(temp/'MAIN_SAMPLE_REPORT.json',report)
    write_bytes(temp/'SUMMARY.md',make_summary(report).encode())
    for key,rows in tables.items():
        write_json(temp/(key+'.json'),rows)
        small_parquet(temp/(key+'.parquet'),rows)
    entries = sorted(p for p in temp.iterdir() if p.is_file())
    write_bytes(temp/'SHA256SUMS.txt',''.join(sha(p)+'  '+p.name+'\n' for p in entries).encode())
    destination = report_root/(name+'.zip'); partial = report_root/(name+'.zip.partial')
    with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(temp.iterdir()): z.write(p,p.name)
    os.rename(partial,destination)
    write_bytes(Path(str(destination)+'.sha256'),(sha(destination)+'  '+destination.name+'\n').encode())
    os.rename(temp,report_root/name)
    return destination


def run(plan,out,reports,workers=4,threads=8,memory='6GB',check_space=True):
    start = time.monotonic()
    protected = [Path(plan[k]).resolve() for k in ('source_root','join_root','panel_root')]
    require(out!=reports and out not in reports.parents and reports not in out.parents,'Private and report roots must be separate')
    for p in protected:
        require(all(q!=p and p not in q.parents and q not in p.parents for q in (out,reports)),'Output overlaps an input root')
    out.mkdir(parents=True,exist_ok=True)
    with lock(out/'RUN.lock'):
        code_root = Path(__file__).parent
        contract = {'version':VERSION,'algorithm':ALGORITHM,
                    'code_sha256':{n:sha(code_root/n) for n in ('build_main_sample.py','audit_io.py','sample_rules.py')},
                    'duckdb_version':duckdb.__version__,'pyarrow_version':pa.__version__,
                    'evidence_sha256':plan['evidence_sha256'],
                    'input_files':sorted([{k:r[k] for k in ('path','sha256','size_bytes')} for r in plan['entries']+plan['metadata']],key=lambda r:r['path']),
                    'months':[m['month'] for m in plan['months']],'expected_counts':plan['expected_counts'],
                    'main_predicate':"source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'"}
        cp = out/'RUN_CONTRACT.json'
        if cp.exists(): require(read_json(cp)==contract,'Output contract differs. Completed work preserved; changed code/inputs/environment need a new output root.')
        else:
            require({p.name for p in out.iterdir()} <= {'RUN.lock'},'Unrecognized existing output folder preserved')
            write_json(cp,contract)
        contract_sha = sha(cp)
        if (out/'_SUCCESS.json').exists():
            success = read_json(out/'_SUCCESS.json')
            require(success['contract_sha256']==contract_sha,'Completed output contract differs')
            with heartbeat('Authenticating completed outputs'):
                for r in success['stages']:
                    p = relative_file(out,r['relative_path'])
                    require(sha(p/'_DONE.json')==r['receipt_sha256'],'Completed stage receipt changed')
                    verify_stage(p,contract_sha)
                for r in success['files']:
                    require(sha(relative_file(out,r['relative_path']))==r['sha256'],'Completed audit file changed')
                require(sha(success['report_zip'])==success['report_zip_sha256'],'Completed report missing/changed')
            log('POOL_MAIN_SAMPLE_24M_CERTIFIED_OK: completed output hashes rechecked; original inputs were not reread')
            print('UPLOAD: '+success['report_zip']); print('UPLOAD: '+success['report_zip']+'.sha256')
            return success
        panel_bytes = sum(r['size_bytes'] for r in plan['entries'] if r['kind']=='panel')
        already_written = sum(p.stat().st_size for p in out.rglob('*.parquet') if not any(x.startswith('.partial_') for x in p.relative_to(out).parts))
        budget = max(12*1024**3,int(panel_bytes*1.25)+20*1024**3-already_written)
        log(f'Input panels {panel_bytes/1024**3:.1f} GiB; free-space planning budget {budget/1024**3:.1f} GiB')
        if check_space: require(shutil.disk_usage(out).free>=budget,'Insufficient free space for full filtered panels, audit files and spill. Required planning budget: '+f'{budget/1024**3:.1f} GiB')
        inputs = authenticate_inputs(plan,workers)
        write_json(out/'INPUT_FILES.json',inputs)
        write_json(out/'SAMPLE_DEFINITION.json',{
            'main_predicate':contract['main_predicate'],'expected_counts':plan['expected_counts'],
            'eligibility_is_game_level':True,'uses_future_repairing_for_selection':False,
            'all_stage07_columns_retained':True,'exact_clock_or_end_time_threshold_applied':False,
            'literal_immediate_rematches_certified':False,
            'unknown_main_treatment':'excluded','missing_history_robustness':'restore left_boundary_unresolved, keep ambiguous_start_order excluded',
            'history_scope':'inherited rated-standard game-start chronology',
            'outcome':'existing Stage07 outcome_kind_draw','fair_definition':'engine_eval_cp_disconnected >= -100',
            'interpretation':'conservative screen excluding mutually consecutive same-opponent candidates and unresolved previous classifications'})
        spill = out/'duckdb_spill'; spill.mkdir(exist_ok=True)
        con = duckdb.connect()
        try:
            con.execute(f'SET threads={threads}'); con.execute('SET memory_limit='+lit(memory))
            con.execute('SET temp_directory='+lit(spill)); con.execute('SET preserve_insertion_order=false')
            con.execute('SET partitioned_write_max_open_files=24')
            con.execute('SET partitioned_write_flush_threshold=65536')
            con.execute("SET TimeZone='UTC'")
            con.execute('CREATE TEMP VIEW j AS SELECT * FROM '+pq_sql(plan['join_paths']))
            con.execute('CREATE TEMP VIEW s AS SELECT * FROM '+pq_sql([plan['source_path']]))
            mask_root = out/'eligibility'
            with heartbeat('Checking all IDs and writing monthly eligibility'):
                mask_done = build_masks(con,plan,mask_root,contract_sha)
            unchanged(inputs)
            monthly=[]; month_roots=[]
            for i,m in enumerate(plan['months'],1):
                dest = out/'panel'/('month='+m['month'])
                log(f'{m["month"]}: monthly sample/composition build ({i}/{len(plan["months"])})')
                with heartbeat(m['month']+': copying retained Stage07 rows and checking comparisons'):
                    done = build_month(con,m,month_mask_paths(mask_root,mask_done,m['month']),dest,contract_sha)
                monthly.append(done); month_roots.append(dest)
                info = next(r for r in done['info']['sample_counts'] if r['sample']=='main_pool_nonadjacent')
                log(f'{m["month"]}: main {info["rows"]:,}; kind draws {info["kind_draws"]:,}; fair {info["fair_rows"]:,}')
                unchanged(inputs)
            with heartbeat('Pooling tables and deduplicating chooser counts across months'):
                tables = finish_tables(con,plan,monthly,month_roots)
            unchanged(inputs)
        finally: con.close()
        stages = [{'relative_path':p.relative_to(out).as_posix(),'receipt_sha256':sha(p/'_DONE.json')}
                  for p in [mask_root]+month_roots]
        files = [{'relative_path':n,'sha256':sha(out/n),'size_bytes':(out/n).stat().st_size}
                 for n in ('RUN_CONTRACT.json','INPUT_FILES.json','SAMPLE_DEFINITION.json')]
        panel_outputs = [{'month':m['month'],**next(r for r in d['files'] if r['relative_path']=='analysis_panel.parquet'),
                          'relative_path':(p/'analysis_panel.parquet').relative_to(out).as_posix()}
                         for m,d,p in zip(plan['months'],monthly,month_roots)]
        report = {'version':VERSION,'algorithm':ALGORITHM,'status':'POOL_MAIN_SAMPLE_24M_CERTIFIED_OK',
            'main_predicate':contract['main_predicate'],'expected_counts':plan['expected_counts'],
            'sample_counts':tables['SAMPLE_COUNTS'],'monthly_counts':tables['MONTHLY_COUNTS'],
            'attrition_counts':tables['ATTRITION_COUNTS'],'monthly_qa':[d['info']['qa'] for d in monthly],
            'eligibility_qa':mask_done['info']['qa'],'input_files_hashed':len(inputs),'inputs_unchanged':True,
            'private_output_root':str(out),'main_panel_pattern':'panel/month=*/analysis_panel.parquet',
            'eligibility_pattern':'eligibility/parts/partition_month=*/*.parquet',
            'panel_outputs':panel_outputs,'stages':stages,'files':files,'contract_sha256':contract_sha,
            'evidence_sha256':plan['evidence_sha256'],'code_sha256':contract['code_sha256'],
            'network_requests':0,'stockfish_evaluations_recomputed':0,'rating_replay_recomputed':False,
            'original_chronology_rescanned':False,'literal_immediate_rematches_certified':False,
            'observed_screen_certified':True,'behavioural_models_reestimated':False,
            'resource_settings':{'hash_workers':workers,'duckdb_threads':threads,'duckdb_memory_limit':memory},
            'environment':{'python':sys.version,'duckdb':duckdb.__version__,'pyarrow':pa.__version__,'platform':platform.platform()},
            'elapsed_seconds':time.monotonic()-start,
            'limits':['Sample eligibility uses observed previous adjacency, not a validated end-to-start rematch flag.',
                      'The retained sample is not certified as strangers or randomly assigned opponents.',
                      'Missing/ambiguous history is excluded in main; the stated robustness restores only missing predecessors.',
                      'Master panels contain all board states. Competitive restrictions remain analysis-specific.',
                      'Source labels cover timeout opportunities; all-game activity denominators remain separate.',
                      'Receipt sequences, exposure histories, chooser signals, Patron matches and figures need rebuilding downstream.',
                      'Full histories remain necessary for prior behaviour, ratings, meetings and censoring; discarded opportunities are not erased.',
                      'These tables are unadjusted descriptions, not causal estimates or controlled price effects.']}
        report_path = save_report(reports,report,tables)
        success = {**report,'report_zip':str(report_path),'report_zip_sha256':sha(report_path)}
        write_json(out/'_SUCCESS.json',success)
        log(f'POOL_MAIN_SAMPLE_24M_CERTIFIED_OK: {plan["expected_counts"]["main_pool_nonadjacent"]:,} retained opportunities')
        print('MAIN PANEL: '+str(out/'panel'))
        print('UPLOAD: '+str(report_path)); print('UPLOAD: '+str(report_path)+'.sha256')
        return success


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--output',type=Path); parser.add_argument('--report-root',type=Path)
    parser.add_argument('--workers',type=int,default=4); parser.add_argument('--threads',type=int,default=8)
    parser.add_argument('--memory',default='6GB')
    args=parser.parse_args()
    try:
        require(1<=args.workers<=10 and 1<=args.threads<=10,'Use 1-10 hash workers and DuckDB threads')
        require(re.fullmatch(r'[1-9][0-9]*(GB|MB)',args.memory) is not None,'Memory must look like 6GB')
        project=args.project.expanduser().resolve(); require(project.is_dir(),'Project not found; connect XT_Pro: '+str(project))
        plan=production_plan(Path(__file__).resolve().parent,project)
        out=(args.output or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE').expanduser().resolve()
        reports=(args.report_root or project/'output/pool_main_sample_24m_v100').expanduser().resolve()
        run(plan,out,reports,args.workers,args.threads,args.memory)
    except KeyboardInterrupt:
        log('Interrupted; completed eligibility and monthly stages remain resumable.'); return 130
    except Exception as exc:
        log('POOL_MAIN_SAMPLE_STOPPED: '+str(exc)); return 2
    return 0


if __name__=='__main__':
    sys.exit(main())
