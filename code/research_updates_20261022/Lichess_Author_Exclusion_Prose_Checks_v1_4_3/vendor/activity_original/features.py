"""Resumable, read-only panel scan for chooser rating and preferred time control."""
from __future__ import annotations
import concurrent.futures as cf
import multiprocessing as mp
import os
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from .common import atomic_json, load_json, sha256_file, utc_now


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def connect(memory='1GB', threads=1, spill=None):
    con = duckdb.connect()
    con.execute(f'SET threads={int(threads)}')
    con.execute('SET memory_limit=' + literal(memory))
    con.execute('SET preserve_insertion_order=false')
    if spill:
        Path(spill).mkdir(parents=True, exist_ok=True)
        con.execute('SET temp_directory=' + literal(spill))
    return con


def monthly_features(task):
    root = Path(task['cache'])
    root.mkdir(parents=True, exist_ok=True)
    month = task['month']
    output = root / (month + '.parquet')
    receipt = root / (month + '.json')
    if receipt.exists():
        saved = load_json(receipt)
        if saved['contract'] != task['contract'] or saved['source_sha256'] != task['expected_sha256']:
            raise RuntimeError('Rating cache authority mismatch: ' + month)
        if not output.is_file() or sha256_file(output) != saved['sha256']:
            raise RuntimeError('Rating cache checksum mismatch: ' + month)
        return dict(month=month, resumed=True, qa=saved['qa'])
    con = connect(task.get('memory', '1GB'), spill=root/'spill'/month)
    try:
        con.execute('''CREATE TEMP TABLE p AS SELECT
            month, chooser_user_id AS chooser,
            CAST(outcome_kind_draw AS INTEGER) AS y,
            CAST(kind_draw AS INTEGER) AS y_alias,
            engine_eval_cp_disconnected AS evaluation,
            fair_competitive AS fair_alias, clearly_worse AS worse_alias, api_status,
            CAST(chooser_elo AS DOUBLE) AS rating,
            coalesce(nullif(lower(trim(api_speed)),''),'__missing__') AS speed,
            coalesce(nullif(trim(time_control),''),'__missing__') AS tc
            FROM read_parquet(?,hive_partitioning=false)''', [task['path']])
        qa = con.execute('''SELECT count(*) AS rows,
            count(*) FILTER (WHERE chooser IS NULL) AS missing_chooser,
            count(*) FILTER (WHERE y IS NULL OR y NOT IN (0,1)) AS invalid_outcome,
            count(*) FILTER (WHERE y IS DISTINCT FROM y_alias) AS outcome_mismatch,
            count(*) FILTER (WHERE evaluation IS NULL) AS missing_evaluation,
            count(*) FILTER (WHERE fair_alias IS DISTINCT FROM (evaluation>=-100)) AS fair_mismatch,
            count(*) FILTER (WHERE worse_alias IS DISTINCT FROM (evaluation<=-300)) AS worse_mismatch,
            count(*) FILTER (WHERE api_status IS DISTINCT FROM 'timeout') AS non_timeout,
            count(*) FILTER (WHERE evaluation>=-100 OR evaluation<=-300) AS binary_rows,
            count(*) FILTER (WHERE (evaluation>=-100 OR evaluation<=-300)
              AND (rating IS NULL OR NOT isfinite(rating) OR rating<=0)) AS unusable_rating_binary_rows,
            count(*) FILTER (WHERE (evaluation>=-100 OR evaluation<=-300)
              AND (speed='__missing__' OR tc='__missing__')) AS missing_time_control_binary_rows
            FROM p''').df().iloc[0].to_dict()
        qa = {k:int(v) for k,v in qa.items()}
        bad = ['missing_chooser','invalid_outcome','outcome_mismatch','missing_evaluation',
               'fair_mismatch','worse_mismatch','non_timeout']
        if qa['rows'] != task['rows'] or any(qa[k] for k in bad):
            raise RuntimeError('Rating source QA failed: ' + month + ' ' + str(qa))
        if con.execute('SELECT DISTINCT month FROM p').fetchall() != [(month,)]:
            raise RuntimeError('Monthly source field disagrees with inventory: ' + month)
        temporary = output.with_suffix('.parquet.tmp')
        con.execute(f'''COPY (
            SELECT chooser, speed, tc, count(*)::BIGINT AS n_binary,
                count(*) FILTER (WHERE evaluation>=-100)::BIGINT AS f,
                count(*) FILTER (WHERE evaluation<=-300)::BIGINT AS l,
                coalesce(sum(y) FILTER (WHERE evaluation>=-100),0)::BIGINT AS a,
                coalesce(sum(y) FILTER (WHERE evaluation<=-300),0)::BIGINT AS b,
                count(*) FILTER (WHERE isfinite(rating) AND rating>0)::BIGINT AS rating_n,
                coalesce(sum(rating) FILTER (WHERE isfinite(rating) AND rating>0),0)::DOUBLE AS rating_sum
            FROM p WHERE evaluation>=-100 OR evaluation<=-300
            GROUP BY chooser,speed,tc
        ) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
        os.replace(temporary, output)
        atomic_json(receipt, dict(month=month, contract=task['contract'],
            source_sha256=task['expected_sha256'], sha256=sha256_file(output),
            qa=qa, completed_utc=utc_now()))
        return dict(month=month, resumed=False, qa=qa)
    finally:
        con.close()


def merge_features(private, months, contract, threads=8, memory='4GB'):
    output = private/'chooser_rating_features.parquet'
    receipt = private/'chooser_rating_features_receipt.json'
    monthly = [private/'monthly'/(m+'.parquet') for m in sorted(months)]
    if len(monthly) != len(set(monthly)) or any(not p.is_file() for p in monthly):
        raise RuntimeError('Incomplete or duplicate monthly feature inventory')
    source_digests = {p.stem:load_json(p.with_suffix('.json'))['sha256'] for p in monthly}
    if receipt.exists():
        saved = load_json(receipt)
        if saved['contract'] != contract or saved['monthly_sha256'] != source_digests:
            raise RuntimeError('Merged rating-feature authority mismatch')
        if not output.is_file() or sha256_file(output) != saved['sha256']:
            raise RuntimeError('Merged rating-feature checksum mismatch')
        return output, saved
    con = connect(memory, threads, private/'merge_spill')
    try:
        # A single chooser may appear in many months and time controls. Count
        # opportunity exposure before selecting the modal (speed,time-control).
        con.execute('''CREATE TEMP TABLE by_tc AS SELECT chooser,speed,tc,
            sum(n_binary)::BIGINT AS n_binary, sum(f)::BIGINT AS f, sum(l)::BIGINT AS l,
            sum(a)::BIGINT AS a, sum(b)::BIGINT AS b,
            sum(rating_n)::BIGINT AS rating_n, sum(rating_sum)::DOUBLE AS rating_sum
            FROM read_parquet(?,hive_partitioning=false) GROUP BY chooser,speed,tc''',
            [[str(p) for p in monthly]])
        con.execute('''CREATE TEMP VIEW ordered AS SELECT *,
            row_number() OVER (PARTITION BY chooser ORDER BY n_binary DESC,speed,tc) AS pick,
            max(n_binary) OVER (PARTITION BY chooser) AS max_n,
            sum(n_binary) OVER (PARTITION BY chooser)::BIGINT AS total_binary,
            sum(f) OVER (PARTITION BY chooser)::BIGINT AS total_f,
            sum(l) OVER (PARTITION BY chooser)::BIGINT AS total_l,
            sum(a) OVER (PARTITION BY chooser)::BIGINT AS total_a,
            sum(b) OVER (PARTITION BY chooser)::BIGINT AS total_b,
            sum(rating_n) OVER (PARTITION BY chooser)::BIGINT AS all_rating_n,
            count(*) OVER (PARTITION BY chooser)::BIGINT AS distinct_time_controls
            FROM by_tc''')
        temporary = output.with_suffix('.parquet.tmp')
        con.execute(f'''COPY (
            SELECT chooser, total_f AS f, total_l AS l, total_a AS a, total_b AS b,
                total_binary AS n_binary, speed AS modal_speed,tc AS modal_time_control,
                n_binary AS modal_opportunities,rating_n AS modal_rating_n,all_rating_n,
                rating_sum/nullif(rating_n,0) AS mean_rating,
                n_binary::DOUBLE/total_binary AS modal_opportunity_share,
                distinct_time_controls,modal_ties
            FROM (SELECT *,sum(CASE WHEN n_binary=max_n THEN 1 ELSE 0 END)
                OVER (PARTITION BY chooser)::BIGINT AS modal_ties FROM ordered)
            WHERE pick=1 ORDER BY chooser
        ) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
        os.replace(temporary,output)
        saved = dict(contract=contract, monthly_sha256=source_digests,
            sha256=sha256_file(output), completed_utc=utc_now())
        atomic_json(receipt,saved)
        return output,saved
    finally:
        con.close()


def build_features(auth, private, contract, workers=4, threads=8, worker_memory='1GB', merge_memory='4GB'):
    tasks = [dict(row, path=str(row['path']), cache=str(private/'monthly'),
        contract=contract, memory=worker_memory) for row in auth['month_records']]
    done=[]
    if workers == 1:
        for task in tasks:
            result=monthly_features(task);done.append(result)
            print('RATING_MONTH_OK '+result['month']+' resumed='+str(result['resumed']),flush=True)
    else:
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
            for future in cf.as_completed([pool.submit(monthly_features,task) for task in tasks]):
                result=future.result();done.append(result)
                print('RATING_MONTH_OK '+result['month']+' resumed='+str(result['resumed']),flush=True)
    print('MERGING_CHOOSER_RATING_FEATURES',flush=True)
    output,receipt=merge_features(private,[t['month'] for t in tasks],contract,threads,merge_memory)
    return output,receipt,sorted(done,key=lambda x:x['month'])


def join_features(census, features_path):
    features=pd.read_parquet(features_path)
    if features.chooser.duplicated().any() or features.chooser.isna().any():
        raise RuntimeError('Invalid feature-table chooser key')
    original=census.loc[(census.f+census.l)>0,['chooser','f','l','a','b']]
    check=original.merge(features[['chooser','f','l','a','b']],on='chooser',how='outer',
                         suffixes=('_original','_scan'),validate='one_to_one',indicator=True)
    if not (check['_merge']=='both').all():raise RuntimeError('Feature scan has a different binary chooser inventory')
    for name in ('f','l','a','b'):
        if not np.array_equal(check[name+'_original'].to_numpy(),check[name+'_scan'].to_numpy()):
            raise RuntimeError('Rating scan did not reproduce chooser counts/grants: '+name)
    del check
    both=census.loc[(census.f>0)&(census.l>0)]
    extra=features.drop(columns=['f','l','a','b'])
    joined=both.merge(extra,on='chooser',how='left',validate='one_to_one')
    if joined.n_binary.isna().any() or not np.array_equal(joined.n_binary,(joined.f+joined.l)):
        raise RuntimeError('Both-state feature join lost or changed opportunities')
    if (joined.modal_opportunities<=0).any() or (joined.modal_opportunities>joined.n_binary).any():
        raise RuntimeError('Invalid modal-time-control support')
    if ((joined.modal_rating_n<0)|(joined.modal_rating_n>joined.modal_opportunities)).any():
        raise RuntimeError('Invalid rating coverage')
    return joined,dict(status='ALL_BINARY_CHOOSER_COUNTS_REPRODUCED',binary_choosers=len(original),
        both_state_choosers=len(joined),observed_nongranters=int(((joined.a+joined.b)==0).sum()))
