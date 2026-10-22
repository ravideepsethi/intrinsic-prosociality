"""Frozen cached profile evidence, with explicit missing TV measurements."""
from pathlib import Path
import hashlib
import json
from common import TITLES, one, records, qs, sha, log
from registry_frozen import reconstruct_directory, read_extra_streamers

PROFILE_REL = 'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
SUPPLEMENT_GLOB = 'derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/*/current_profile_gap_supplement_private.parquet'
DIRECTORY_REL = 'derived/replication/audience_visibility_v100_PRIVATE/directory_snapshot'

def discover_profiles(root, authority):
    candidates = [root / PROFILE_REL, *sorted(root.glob(SUPPLEMENT_GLOB))]
    expected = {x['sha256']: x for x in authority['profile_source_receipts']}
    found = {}
    for p in candidates:
        if not p.is_file(): continue
        # Only files matching the returned audit enter this analysis.
        if p.stat().st_size not in {x['bytes'] for x in expected.values()}: continue
        digest = sha(p)
        if digest in expected: found.setdefault(digest, p)
    missing = [x['filename'] for h,x in expected.items() if h not in found]
    if missing:
        raise FileNotFoundError('Audited profile snapshot(s) not found with the expected SHA-256: ' + ', '.join(missing))
    return [found[x['sha256']] for x in authority['profile_source_receipts']]

def load_profiles(db, paths, private, authority):
    db.execute('''CREATE TEMP TABLE profile_rows(
      username VARCHAR, returned BOOLEAN, observed_at VARCHAR, j JSON,
      norm_title VARCHAR, bio VARCHAR, norm_tv BIGINT)''')
    receipts = []
    for p in paths:
        schema = {r[0] for r in db.execute(f'DESCRIBE SELECT * FROM read_parquet({qs(p)})').fetchall()}
        required = {'username_norm','returned','raw_user_json','queried_at_utc'}
        if not required <= schema: raise ValueError('Audited profile schema is incomplete')
        def col(name): return f'CAST("{name}" AS VARCHAR)' if name in schema else 'NULL::VARCHAR'
        db.execute(f'''INSERT INTO profile_rows SELECT lower(trim(username_norm)), returned,
          cast(queried_at_utc AS VARCHAR), try_cast(raw_user_json AS JSON),
          upper(nullif(trim({col('title')}),'')),
          concat_ws(' ', {col('profile_bio')}, {col('profile_links')},
            json_extract_string(try_cast(raw_user_json AS JSON),'$.profile.bio'),
            json_extract_string(try_cast(raw_user_json AS JSON),'$.profile.links')),
          try_cast({col('play_time_tv_seconds')} AS BIGINT)
          FROM read_parquet({qs(p)})''')
        receipts.append({'filename':p.name,'sha256':sha(p),'bytes':p.stat().st_size})
    qa = one(db,'''SELECT count(*) saved_rows,
      count(*) FILTER(WHERE returned IS TRUE) returned_rows,
      count(*) FILTER(WHERE returned IS FALSE) explicitly_unreturned_rows,
      count(*) FILTER(WHERE returned IS NULL) unknown_return_status_rows,
      count(*) FILTER(WHERE returned AND (username IS NULL OR username='')) bad_ids,
      count(*) FILTER(WHERE returned AND NOT coalesce(json_type(j)='OBJECT',false)) returned_rows_without_raw_object,
      count(*) FILTER(WHERE returned AND norm_title IS NOT NULL AND
        json_extract_string(j,'$.title') IS NOT NULL AND
        norm_title<>upper(json_extract_string(j,'$.title'))) normalized_raw_title_disagreements,
      count(*) FILTER(WHERE returned AND norm_tv IS NOT NULL AND
        try_cast(json_extract_string(j,'$.playTime.tv') AS BIGINT) IS NOT NULL AND
        norm_tv<>try_cast(json_extract_string(j,'$.playTime.tv') AS BIGINT)) tv_disagreements
      FROM profile_rows''')
    if any(qa[k] for k in ['bad_ids','returned_rows_without_raw_object','normalized_raw_title_disagreements','tv_disagreements']):
        raise ValueError('Profile evidence disagrees with normalized fields or has invalid IDs/JSON')
    for k,v in authority['profile_quality'].items():
        if qa[k] != v: raise ValueError('Profile audit quality count differs: '+k)
    titles = ','.join(qs(t) for t in TITLES)
    db.execute(f'''CREATE TEMP TABLE evidence AS SELECT username,observed_at,
      coalesce(norm_title,upper(nullif(json_extract_string(j,'$.title'),'')),'') title,
      coalesce(json_exists(j,'$.streamer'),false) streamer_field,
      coalesce(json_exists(j,'$.streaming'),false) streaming_field,
      coalesce(nullif(json_extract_string(j,'$.streamer.twitch.channel'),''),
        nullif(json_extract_string(j,'$.streamer.youTube.channel'),''),
        nullif(json_extract_string(j,'$.streamer.youtube.channel'),'')) IS NOT NULL structured_streamer,
      coalesce(json_type(j,'$.streaming')='BOOLEAN' AND json_extract_string(j,'$.streaming')='true',false) streaming_true,
      coalesce(regexp_matches(lower(bio),
        '(^|[^a-z0-9_])(twitch[.]tv|youtube[.]com|youtu[.]be|kick[.]com)(/|[^a-z0-9_.-]|$)'),false) link,
      coalesce(norm_tv,try_cast(json_extract_string(j,'$.playTime.tv') AS BIGINT)) tv_seconds
      FROM profile_rows WHERE returned IS TRUE''')
    if one(db,"SELECT count(*) n FROM evidence WHERE tv_seconds<0 OR title NOT IN ('','BOT','LM',"+titles+")")['n']:
        raise ValueError('Negative TV time or unrecognized title')
    db.execute(f'''CREATE TEMP TABLE profiles AS SELECT username,
      count(*) profile_rows, min(observed_at) first_observed, max(observed_at) last_observed,
      bool_or(title IN ({titles})) titled, bool_or(title='BOT') bot, bool_or(title='LM') lm,
      bool_or(streamer_field) streamer_field, bool_or(streaming_field) streaming_field,
      bool_or(structured_streamer) structured_streamer, bool_or(streaming_true) streaming_true,
      bool_or(structured_streamer OR streaming_true) positive_streamer,
      bool_or(link) link, max(tv_seconds) tv_seconds,
      count(tv_seconds)>0 tv_known, coalesce(max(tv_seconds)>0,false) tv_positive
      FROM evidence GROUP BY username''')
    info = one(db,'''SELECT count(*) returned_distinct_accounts,
      count(*) FILTER(WHERE titled) known_chess_title_accounts,
      count(*) FILTER(WHERE lm) lm_title_accounts,
      count(*) FILTER(WHERE bot) bot_accounts,
      count(*) FILTER(WHERE streamer_field) accounts_with_streamer_field,
      count(*) FILTER(WHERE streaming_field) accounts_with_streaming_field,
      count(*) FILTER(WHERE structured_streamer) accounts_with_structured_streamer_channel,
      count(*) FILTER(WHERE streaming_true) accounts_ever_observed_streaming_true,
      count(*) FILTER(WHERE positive_streamer) positive_streamer_accounts,
      count(*) FILTER(WHERE link) channel_link_candidate_accounts,
      count(*) FILTER(WHERE link AND NOT positive_streamer) candidate_only_accounts,
      count(*) FILTER(WHERE tv_positive) accounts_with_positive_recorded_tv_time,
      count(*) FILTER(WHERE profile_rows>1) accounts_with_multiple_profile_rows,
      count(*) FILTER(WHERE tv_known) accounts_with_numeric_tv_field,
      count(*) FILTER(WHERE tv_seconds=0) accounts_with_recorded_zero_tv_time,
      count(*) FILTER(WHERE NOT tv_known) accounts_with_missing_tv_measurement,
      min(first_observed) first_query_date,max(last_observed) last_query_date FROM profiles''')
    for k,v in authority['profile_summary'].items():
        if info[k] != v: raise ValueError(f'Profile audit count differs: {k}: {info[k]} != {v}')
    db.execute(f'COPY profiles TO {qs(private/"profile_flags.parquet")} (FORMAT PARQUET,COMPRESSION ZSTD)')
    db.execute('DROP TABLE profile_rows')
    db.execute('DROP TABLE evidence')
    return {'sources':receipts,'quality':qa,**info}

def load_directory(db, root, authority, extras=None):
    directory = root / DIRECTORY_REL
    manifest = directory/'directory_manifest.json'
    if not manifest.is_file():
        raise FileNotFoundError('The prior streamer directory cache is required: '+str(manifest))
    info = json.loads(manifest.read_text())
    if not info.get('pagination_completed'): raise ValueError('Prior directory cache is incomplete')
    for item in info['pages']:
        name = Path(item['file'])
        if name.name != item['file'] or sha(directory/name) != item['sha256']:
            raise ValueError('Prior directory page failed integrity verification')
    users,_ = reconstruct_directory(directory,info)
    frozen_hash = hashlib.sha256(json.dumps(sorted(users.items()),separators=(',',':')).encode()).hexdigest()
    expected = authority['directory']
    if frozen_hash != expected['registry_sha256'] or len(users) != expected['directory_accounts']:
        raise ValueError('Directory membership differs from the returned audience analysis')
    extra_info = None
    if extras:
        if not extras.is_file(): raise FileNotFoundError(extras)
        new,extra_info = read_extra_streamers(extras)
        for uid,title in new.items(): users.setdefault(uid,title)
    db.execute('CREATE TEMP TABLE streamers(username VARCHAR PRIMARY KEY,title VARCHAR)')
    if users:
        db.executemany('INSERT INTO streamers VALUES (?,?)',sorted(users.items()))
    combined = hashlib.sha256(json.dumps(sorted(users.items()),separators=(',',':')).encode()).hexdigest()
    log(f'Using {len(users):,} cached directory / user-supplied positive accounts; no data requests')
    return {'frozen_directory_accounts':expected['directory_accounts'],
      'frozen_registry_sha256':frozen_hash,'combined_accounts':len(users),
      'combined_registry_sha256':combined,'extra_list':extra_info,
      'started_utc':info['started_utc'],'completed_utc':info['completed_utc'],
      'scope':'Existing incomplete dated positive list, unchanged; not a streamer census'}
