#!/usr/bin/env python3
"""Audit saved Patron profiles. No network requests; never modify input files.

Public results are aggregate counts. Identifiers, links and extracted evidence
remain in a separate PRIVATE directory. A link in a bio is a candidate only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

VERSION = '1.0.0'
SNAPSHOT_REL = 'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
SNAPSHOT_SHA = 'f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
SUPPLEMENT_GLOB = 'derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/*/current_profile_gap_supplement_private.parquet'
TITLES = ('GM','IM','FM','CM','NM','WGM','WIM','WFM','WCM','WNM')

def qs(value):
    return "'" + str(value).replace("'", "''") + "'"

def qi(value):
    return '"' + str(value).replace('"', '""') + '"'

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''):
            h.update(b)
    return h.hexdigest()

def records(db, sql):
    cur = db.execute(sql)
    names = [x[0] for x in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def load_source(db, path, label):
    cols = {r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(path)]).fetchall()}
    needed = {'username_norm', 'returned', 'raw_user_json'}
    if not needed <= cols:
        raise ValueError(f'{path.name}: required columns missing: {sorted(needed-cols)}')
    def col(name):
        return f'CAST({qi(name)} AS VARCHAR)' if name in cols else 'NULL::VARCHAR'
    sql = f'''SELECT {qs(label)} AS profile_source, lower(trim(username_norm)) username,
      returned, {col('queried_at_utc')} observed_at,
      {col('raw_user_json')} raw_text, try_cast(raw_user_json AS JSON) j,
      upper(nullif(trim({col('title')}),'')) normalized_title,
      concat_ws(' ', {col('profile_bio')}, {col('profile_links')},
        json_extract_string(try_cast(raw_user_json AS JSON),'$.profile.bio'),
        json_extract_string(try_cast(raw_user_json AS JSON),'$.profile.links')) profile_text,
      try_cast({col('play_time_tv_seconds')} AS BIGINT) tv_seconds_normalized
      FROM read_parquet({qs(path)})'''
    db.execute('INSERT INTO saved_profiles ' + sql)
    return {'source': label, 'filename': path.name, 'sha256': sha(path),
            'bytes': path.stat().st_size, 'columns': sorted(cols)}

def audit(db, sources, private_dir):
    db.execute('''CREATE TEMP TABLE saved_profiles(
      profile_source VARCHAR, username VARCHAR, returned BOOLEAN, observed_at VARCHAR,
      raw_text VARCHAR, j JSON, normalized_title VARCHAR,
      profile_text VARCHAR, tv_seconds_normalized BIGINT)''')
    receipts = [load_source(db, p, f'profile_source_{i+1}') for i,p in enumerate(sources)]
    bad_ids = db.execute("SELECT count(*) FROM saved_profiles WHERE returned AND (username IS NULL OR username='')").fetchone()[0]
    if bad_ids:
        raise ValueError('Returned profile rows lack a normalized identifier')
    db.execute('''CREATE TEMP TABLE evidence AS
      SELECT *, coalesce(normalized_title,upper(nullif(json_extract_string(j,'$.title'),''))) title,
        coalesce(json_type(j)='OBJECT',false) raw_object,
        coalesce(json_exists(j,'$.streamer'),false) streamer_field_present,
        coalesce(json_exists(j,'$.streaming'),false) streaming_field_present,
        nullif(json_extract_string(j,'$.streamer.twitch.channel'),'') twitch_channel,
        coalesce(nullif(json_extract_string(j,'$.streamer.youTube.channel'),''),
          nullif(json_extract_string(j,'$.streamer.youtube.channel'),'')) youtube_channel,
        coalesce(json_type(j,'$.streaming')='BOOLEAN' AND
          json_extract_string(j,'$.streaming')='true',false) streaming_true,
        coalesce(regexp_matches(lower(profile_text),
          '(^|[^a-z0-9_])(twitch[.]tv|youtube[.]com|youtu[.]be|kick[.]com)(/|[^a-z0-9_.-]|$)'),false) channel_link_candidate,
        coalesce(tv_seconds_normalized,try_cast(json_extract_string(j,'$.playTime.tv') AS BIGINT)) tv_seconds
      FROM saved_profiles WHERE returned IS TRUE''')
    title_sql = ','.join(qs(t) for t in TITLES)
    db.execute(f'''CREATE TEMP TABLE accounts AS SELECT username,
      count(*) profile_rows, count(DISTINCT profile_source) source_count,
      min(observed_at) first_observed_at, max(observed_at) last_observed_at,
      string_agg(DISTINCT title,',') observed_titles,
      bool_or(coalesce(title IN({title_sql}),false)) known_chess_title,
      bool_or(coalesce(title='LM',false)) lm_title,
      bool_or(coalesce(title='BOT',false)) bot_title,
      bool_or(streamer_field_present) streamer_field_present,
      bool_or(twitch_channel IS NOT NULL OR youtube_channel IS NOT NULL) structured_streamer_channel,
      bool_or(streaming_field_present) streaming_field_present,
      bool_or(streaming_true) ever_observed_streaming_true,
      bool_or(channel_link_candidate) channel_link_candidate,
      string_agg(DISTINCT twitch_channel,' | ') twitch_channels,
      string_agg(DISTINCT youtube_channel,' | ') youtube_channels,
      bool_or(coalesce(tv_seconds>0,false)) any_recorded_tv_time
      FROM evidence GROUP BY username''')
    db.execute(f"COPY accounts TO {qs(private_dir/'audience_profile_evidence.parquet')} (FORMAT PARQUET,COMPRESSION ZSTD)")
    db.execute(f'''COPY (SELECT username, observed_titles, first_observed_at, last_observed_at,
      structured_streamer_channel, ever_observed_streaming_true, twitch_channels,youtube_channels
      FROM accounts WHERE structured_streamer_channel OR ever_observed_streaming_true)
      TO {qs(private_dir/'positive_streamer_evidence.csv')} (HEADER,FORMAT CSV)''')
    db.execute(f'''COPY (SELECT profile_source,username,observed_at,title,
      twitch_channel,youtube_channel,streaming_true,profile_text
      FROM evidence WHERE channel_link_candidate)
      TO {qs(private_dir/'streamer_candidates_for_review.csv')} (HEADER,FORMAT CSV)''')
    summary = records(db, '''SELECT count(*) returned_distinct_accounts,
      count(*) FILTER(WHERE known_chess_title) known_chess_title_accounts,
      count(*) FILTER(WHERE lm_title) lm_title_accounts,
      count(*) FILTER(WHERE bot_title) bot_accounts,
      count(*) FILTER(WHERE streamer_field_present) accounts_with_streamer_field,
      count(*) FILTER(WHERE structured_streamer_channel) accounts_with_structured_streamer_channel,
      count(*) FILTER(WHERE streaming_field_present) accounts_with_streaming_field,
      count(*) FILTER(WHERE ever_observed_streaming_true) accounts_ever_observed_streaming_true,
      count(*) FILTER(WHERE structured_streamer_channel OR ever_observed_streaming_true) positive_streamer_accounts,
      count(*) FILTER(WHERE channel_link_candidate) channel_link_candidate_accounts,
      count(*) FILTER(WHERE channel_link_candidate AND NOT (structured_streamer_channel OR ever_observed_streaming_true)) candidate_only_accounts,
      count(*) FILTER(WHERE any_recorded_tv_time) accounts_with_positive_recorded_tv_time,
      count(*) FILTER(WHERE profile_rows>1) accounts_with_multiple_profile_rows
      FROM accounts''')[0]
    quality = records(db, '''SELECT count(*) saved_rows,
      count(*) FILTER(WHERE returned IS TRUE) returned_rows,
      count(*) FILTER(WHERE returned IS FALSE) explicitly_unreturned_rows,
      count(*) FILTER(WHERE returned IS NULL) unknown_return_status_rows,
      count(*) FILTER(WHERE returned AND NOT coalesce(json_type(j)='OBJECT',false)) returned_rows_without_raw_object,
      count(*) FILTER(WHERE returned AND normalized_title IS NOT NULL AND
        json_extract_string(j,'$.title') IS NOT NULL AND
        normalized_title<>upper(json_extract_string(j,'$.title'))) normalized_raw_title_disagreements
      FROM saved_profiles''')[0]
    by_source = records(db, '''SELECT profile_source,count(*) returned_rows,count(DISTINCT username) returned_accounts,
      min(observed_at) first_observed_at,max(observed_at) last_observed_at,
      count(*) FILTER(WHERE streamer_field_present) streamer_field_rows,
      count(*) FILTER(WHERE streaming_field_present) streaming_field_rows,
      count(*) FILTER(WHERE channel_link_candidate) channel_link_candidate_rows
      FROM evidence GROUP BY profile_source ORDER BY profile_source''')
    keys = records(db, '''SELECT field,count(*) returned_rows_with_key
      FROM evidence,unnest(json_keys(j)) t(field)
      WHERE raw_object GROUP BY field ORDER BY field''')
    titles = records(db, '''SELECT coalesce(title,'[no title recorded]') title,
      count(*) profile_rows,count(DISTINCT username) distinct_accounts
      FROM evidence GROUP BY title ORDER BY title''')
    return {'version':VERSION,'source_receipts':receipts,'quality':quality,'summary':summary,
            'coverage_by_source':by_source,'top_level_key_inventory':keys,'title_inventory':titles,
            'interpretation':[
              'No streamer field is missing measurement, not evidence of being a non-streamer.',
              'streaming=true is evidence of being live at query time; false is not a non-streamer classification.',
              'Profile links are candidates for review, not automatically owned channels or verified streamers.',
              'TV time is a separate profile field, not a game-level spectator count or streamer flag.',
              'Counts describe saved profiles, not the full paper sample; the Patron acquisition is selected.',
              'Titles and profiles have their actual query dates, not assumed panel-period dates.',
              'Private evidence includes repeated snapshots and preserves source dates; input files are unchanged.'
            ]}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--profile',type=Path,action='append',help='Explicit normalized profile input(s); otherwise audit certified snapshot and existing gap supplement(s).')
    ap.add_argument('--threads',type=int,default=4)
    args = ap.parse_args()
    if not 1<=args.threads<=10: ap.error('threads must be between 1 and 10')
    import duckdb
    started=time.monotonic()
    root=args.project_root.expanduser().resolve()
    if not root.is_dir(): raise FileNotFoundError('Project root not found; mount XT_Pro first')
    sources=[p.expanduser().resolve() for p in args.profile] if args.profile else [root/SNAPSHOT_REL,*sorted(root.glob(SUPPLEMENT_GLOB))]
    sources=list(dict.fromkeys(sources))
    for p in sources:
        if not p.is_file(): raise FileNotFoundError(f'Profile file not found: {p}')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+f'_{os.getpid()}'
    public=root/'output'/f'PATRON_AUDIENCE_CACHE_AUDIT_v100_{stamp}'
    private=root/'derived/replication/patron_audience_cache_audit_v100_PRIVATE'/stamp
    public.mkdir(parents=True,exist_ok=False);private.mkdir(parents=True,exist_ok=False)
    os.chmod(private,0o700)
    print(f'Auditing {len(sources)} saved profile file(s); no API requests.',flush=True)
    if not args.profile and sha(sources[0]) != SNAPSHOT_SHA:
        raise ValueError('Certified August snapshot SHA-256 differs. Stopping without changing it.')
    db=duckdb.connect(str(private/'audit.duckdb'))
    db.execute(f"SET threads={args.threads}")
    db.execute("SET memory_limit='3GB'")
    db.execute(f'SET temp_directory={qs(private/"spill")}')
    try:
        result=audit(db,sources,private)
    finally:
        db.close()
    result.update({'elapsed_seconds':time.monotonic()-started,'duckdb_version':duckdb.__version__,
      'certified_august_snapshot_verified':not bool(args.profile),
      'status':'COMPLETE_WITH_DATA_QUALITY_WARNINGS' if (result['quality']['returned_rows_without_raw_object'] or result['quality']['normalized_raw_title_disagreements']) else 'COMPLETE',
      'private_evidence_directory':str(private),'network_requests':0})
    write_json(public/'RESULTS.json',result)
    lines=['# Saved Patron profile audience audit','', 'Counts refer to available saved profiles, not the full game sample.','']
    lines += [f'- {k}: {v:,}' for k,v in result['summary'].items()]
    lines += ['','## Interpretation','']+[f'- {x}' for x in result['interpretation']]
    (public/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    shutil.copy2(Path(__file__),public/'executed_audit.py')
    write_json(public/'_SUCCESS.json',{'status':result['status'],'version':VERSION,'results_sha256':sha(public/'RESULTS.json')})
    files=sorted(p for p in public.iterdir() if p.is_file())
    (public/'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
    zipped=public.with_suffix('.zip')
    with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.iterdir()): z.write(p,arcname=public.name+'/'+p.name)
    sidecar=Path(str(zipped)+'.sha256')
    sidecar.write_text(f'{sha(zipped)}  {zipped.name}\n')
    desktop=args.desktop.expanduser();desktop.mkdir(parents=True,exist_ok=True)
    for p in (zipped,sidecar):
        if p.resolve() != (desktop/p.name).resolve(): shutil.copy2(p,desktop/p.name)
    print(json.dumps(result['summary'],indent=2),flush=True)
    print(f'Private evidence: {private}\nUpload these aggregate files:\n{desktop/zipped.name}\n{desktop/sidecar.name}',flush=True)

if __name__=='__main__':
    main()
