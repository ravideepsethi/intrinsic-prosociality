#!/usr/bin/env python3
"""Audience-proxy robustness on the frozen 41,534,331-opportunity main sample.

Source panels are read-only. Public output is aggregate only. Streamer listing
and profile identifiers, thin-panel caches, and DuckDB spill stay PRIVATE.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import zipfile

from common import VERSION, TITLES, atomic_json, log, now, one, qs, qi, records, sha, write_csv
from registry import collect_directory, read_extra_streamers
from estimates import group_expression, make_cells, estimate_cells, standardize

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = Path('/Volumes/XT_Pro/lichess_kindness')
PANEL_REL = 'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel'
PROFILE_REL = 'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
PROFILE_SHA = 'f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
REQUIRED = {'chooser_username_norm','disconnected_username_norm','kind_draw','fair_competitive',
 'clearly_worse','chooser_elo','disconnected_elo','ply_count','api_speed',
 'chooser_clock_last_obs_s','disconnected_clock_last_obs_s','game_id'}
DEFINITIONS = ('rating_and_directory','rating_directory_known_titles')

def configure(db, threads, memory_gb, spill):
    db.execute(f'SET threads={int(threads)}')
    db.execute(f"SET memory_limit='{int(memory_gb)}GB'")
    db.execute(f'SET temp_directory={qs(spill)}')
    db.execute('SET preserve_insertion_order=false')

def verify_panel(root, authority):
    paths = [root/f"month={a['month']}"/'analysis_panel.parquet' for a in authority['monthly_inputs']]
    for p,a in zip(paths,authority['monthly_inputs']):
        if not p.is_file():
            raise FileNotFoundError(f'Main panel not found: {p}. Mount XT_Pro or set LICHESS_AUDIENCE_PROJECT_ROOT.')
        if p.stat().st_size != a['bytes']:
            raise RuntimeError(f"Main-panel file size differs for {a['month']}")
    log('Verifying the 24 frozen monthly files (approximately 12.7 GB)...')
    # Two readers avoid excessive contention on the external drive.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for a,digest in zip(authority['monthly_inputs'],ex.map(sha,paths)):
            if digest!=a['sha256']:
                raise RuntimeError(f"Main-panel SHA-256 mismatch: {a['month']}")
            log('Verified '+a['month'])
    return paths

def load_profiles(db, paths):
    db.execute('CREATE TEMP TABLE profile_rows(username VARCHAR,title VARCHAR,seen VARCHAR)')
    sources=[]
    for i,p in enumerate(paths):
        if not p.is_file():
            raise FileNotFoundError(p)
        digest=sha(p)
        if p.name=='profile_snapshot_24m_private_lossless.parquet' and 'FINAL_CERTIFIED' in str(p):
            if digest!=PROFILE_SHA:
                raise RuntimeError('Certified title-source snapshot SHA-256 differs')
        schema={r[0] for r in db.execute(f'DESCRIBE SELECT * FROM read_parquet({qs(p)})').fetchall()}
        required={'username_norm','title','returned'}
        if not required<=schema:
            raise RuntimeError(f'Profile file {p.name} lacks normalized fields {sorted(required-schema)}; do not guess title coverage')
        seen='cast(queried_at_utc AS VARCHAR)' if 'queried_at_utc' in schema else 'NULL::VARCHAR'
        bad=one(db,f'''SELECT count(*) n FROM read_parquet({qs(p)})
            WHERE returned AND (username_norm IS NULL OR trim(username_norm)='')''')['n']
        if bad:
            raise RuntimeError('Returned profiles have missing account identifiers')
        db.execute(f'''INSERT INTO profile_rows SELECT lower(trim(username_norm)),
            upper(trim(coalesce(title,''))),{seen} FROM read_parquet({qs(p)}) WHERE returned''')
        sources.append({'source':f'local_profile_snapshot_{i+1}','sha256':digest,
                        'bytes':p.stat().st_size,'certified_august_snapshot':digest==PROFILE_SHA})
    title_list=','.join(qs(t) for t in TITLES)
    unknown=records(db,f"SELECT title,count(*) n FROM profile_rows WHERE title NOT IN('', 'BOT', 'LM', {title_list}) GROUP BY title")
    if unknown:
        raise RuntimeError('Unrecognized title values in normalized profiles; inspect the private source')
    db.execute(f'''CREATE TEMP TABLE profiles AS SELECT username,
         bool_or(title IN({title_list})) AS titled, bool_or(title='BOT') AS bot,
         min(seen) first_observed,max(seen) last_observed FROM profile_rows GROUP BY username''')
    coverage=one(db,'''SELECT count(*) AS returned_accounts,
        coalesce(sum(titled::INTEGER),0) AS titled_accounts,
        coalesce(sum(bot::INTEGER),0) AS bot_accounts,
        min(first_observed) AS first_profile_date,max(last_observed) AS last_profile_date FROM profiles''')
    db.execute('DROP TABLE profile_rows')
    return sources,coverage

def register_streamers(db, users):
    db.execute('CREATE TEMP TABLE streamers(username VARCHAR PRIMARY KEY,title VARCHAR)')
    db.execute('BEGIN TRANSACTION')
    try:
        if users:
            db.executemany('INSERT INTO streamers VALUES (?,?)',sorted(users.items()))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise

def build_base(db, paths, months, cache):
    cache.mkdir(parents=True,exist_ok=True)
    thin=[]
    title_list=','.join(qs(t) for t in TITLES)
    for path,a in zip(paths,months):
        dest=cache/(a['month']+'.parquet')
        stamp=cache/(a['month']+'.json')
        if dest.exists() and stamp.exists():
            receipt=json.loads(stamp.read_text())
            if receipt['sha256']!=sha(dest) or receipt['source_sha256']!=a['sha256']:
                raise RuntimeError('Thin-panel cache differs; no overwrite performed')
            log('Reusing joined panel '+a['month'])
        else:
            schema={r[0] for r in db.execute(f'DESCRIBE SELECT * FROM read_parquet({qs(path)})').fetchall()}
            if not REQUIRED<=schema:
                raise RuntimeError(f'Source columns missing: {sorted(REQUIRED-schema)}')
            db.execute(f'CREATE OR REPLACE TEMP VIEW p AS SELECT * FROM read_parquet({qs(path)})')
            qa=one(db,'''SELECT count(*) n,
                count(*) FILTER(WHERE chooser_username_norm IS NULL OR chooser_username_norm='' OR
                   disconnected_username_norm IS NULL OR disconnected_username_norm='' OR
                   kind_draw IS NULL OR fair_competitive IS NULL OR clearly_worse IS NULL OR
                   (fair_competitive AND clearly_worse)) bad FROM p''')
            if qa['n']!=a['rows'] or qa['bad']:
                raise RuntimeError('Invalid roles, outcome, state, or source count')
            mi=(int(a['month'][:4])-2023)*12+int(a['month'][5:])
            temp=dest.with_suffix('.tmp.parquet')
            sql=f'''SELECT lower(p.chooser_username_norm) chooser,
              lower(p.disconnected_username_norm) opponent,
              cast(p.kind_draw AS INTEGER) y,
              CASE WHEN p.fair_competitive THEN 1 WHEN p.clearly_worse THEN 0 ELSE 2 END::INTEGER state,
              p.chooser_elo ce,p.disconnected_elo de,p.ply_count ply,
              p.chooser_clock_last_obs_s cc,p.disconnected_clock_last_obs_s dc,
              p.api_speed speed,{mi}::INTEGER month_index,
              sc.username IS NOT NULL cs,sd.username IS NOT NULL ds,
              (coalesce(pc.titled,false) OR coalesce(sc.title IN({title_list}),false)) ct,
              (coalesce(pd.titled,false) OR coalesce(sd.title IN({title_list}),false)) dt,
              coalesce(pc.bot,false) cb,coalesce(pd.bot,false) dbot,
              pc.username IS NOT NULL cp,pd.username IS NOT NULL dp
              FROM p LEFT JOIN profiles pc ON lower(p.chooser_username_norm)=pc.username
              LEFT JOIN profiles pd ON lower(p.disconnected_username_norm)=pd.username
              LEFT JOIN streamers sc ON lower(p.chooser_username_norm)=sc.username
              LEFT JOIN streamers sd ON lower(p.disconnected_username_norm)=sd.username'''
            db.execute(f'COPY ({sql}) TO {qs(temp)} (FORMAT PARQUET,COMPRESSION ZSTD)')
            n=one(db,f'SELECT count(*) n FROM read_parquet({qs(temp)})')['n']
            if n!=a['rows']:
                raise RuntimeError('Metadata join changed row count')
            os.replace(temp,dest)
            atomic_json(stamp,{'sha256':sha(dest),'source_sha256':a['sha256'],'rows':n})
            log('Joined '+a['month'])
        thin.append(dest)
    db.execute('CREATE VIEW base AS SELECT * FROM read_parquet(['+','.join(qs(p) for p in thin)+'])')
    return thin

def validate_sample(db, expected):
    qa=one(db,'''SELECT count(*) opportunities,sum(y)::BIGINT kind_draws,
        count(DISTINCT chooser) chooser_accounts,
        count(*) FILTER(WHERE state=1) competitive_opportunities,
        count(*) FILTER(WHERE state=0) clearly_worse_opportunities,
        sum(y) FILTER(WHERE state=1)::BIGINT competitive_kind_draws,
        sum(y) FILTER(WHERE state=0)::BIGINT clearly_worse_kind_draws,
        count(*) FILTER(WHERE ce<1600 AND state=1) below1600_competitive_opportunities,
        count(*) FILTER(WHERE ce<1600 AND state=0) below1600_clearly_worse_opportunities,
        sum(y) FILTER(WHERE ce<1600 AND state=1)::BIGINT below1600_competitive_kind_draws,
        sum(y) FILTER(WHERE ce<1600 AND state=0)::BIGINT below1600_clearly_worse_kind_draws,
        count(DISTINCT chooser) FILTER(WHERE y=1) granting_accounts,
        count(DISTINCT chooser) FILTER(WHERE y=1 AND state=1) competitive_granting_accounts
        FROM base''')
    for key,val in expected.items():
        if key=='missing_chooser_groups':
            continue  # Independently checked per month.
        if key not in qa or qa[key]!=val:
            raise RuntimeError(f'Current sample total differs: {key}: {qa.get(key)} vs {val}')
    return qa

def quality_tables(db):
    coverage=records(db,'''SELECT state,y,count(*) n,
        sum(cp::INTEGER)::BIGINT chooser_profile_observed,
        sum(dp::INTEGER)::BIGINT opponent_profile_observed,
        sum((cp AND dp)::INTEGER)::BIGINT both_profiles_observed,
        sum(cs::INTEGER)::BIGINT chooser_known_streamer,
        sum(ds::INTEGER)::BIGINT opponent_known_streamer,
        sum(ct::INTEGER)::BIGINT chooser_known_titled,
        sum(dt::INTEGER)::BIGINT opponent_known_titled
        FROM base GROUP BY state,y ORDER BY state,y''')
    return coverage

def write_report(out, payload):
    rows=payload['summary']
    focus=[r for r in rows if r['threshold']==2400 and r['view']=='either_player' and
           r['definition']=='rating_directory_known_titles']
    lines=['# Audience-proxy robustness results','',
        'This analysis measures concentration among identifiable streamer/elite accounts. '
        'It does not observe spectators or identify the causal effect of being watched.','',
        f"Verified current sample: {payload['sample_qa']['opportunities']:,} opportunities; "
        f"{payload['sample_qa']['kind_draws']:,} kind draws.",'',
        '## Excluding either player: 2400 or a known chess title; streamers take priority','',
        '| Group | Opportunities | Kind draws | Share of kind draws | Competitive rate | Clearly-worse rate | Raw gap | Chooser FE gap |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    def fmt(x):return 'NA' if x is None else f'{x:.3f}'
    for r in focus:
        lines.append(f"| {r['group']} | {r['opportunities']:,} | {r['kind_draws']:,} | "
            f"{fmt(r['kind_draw_share_pct'])}% | {fmt(r['competitive_rate_pct'])}% | "
            f"{fmt(r['clearly_worse_rate_pct'])}% | {fmt(r['raw_gradient_pp'])} pp | "
            f"{fmt(r['chooser_fe_gradient_pp'])} pp |")
    lines+=['','## Interpretation and coverage','',
        '- The remaining group is not identified as streamer/elite under this rule; it is not certified unwatched.',
        '- The directory is a current, capped public listing. It misses historical, unlisted, and other off-platform streamers.',
        '- Cached title data were collected after the study period and on a sample selected partly by granting behavior. '
        'Absent profiles are unknown, not verified untitled. The rating-and-directory-only analyses avoid this title-source selection.',
        '- Ratings are from each opportunity, not current profiles. A player can enter multiple rating-defined groups over time.',
        '- Strict remainder means neither player is flagged. It still has unmeasured audiences and incomplete title/streamer coverage.',
        '- Rates use all opportunities in the stated group. Desert contrasts omit the middle evaluation region.',
        '- Chooser FE uses only accounts seen in both desert categories within that group; these are state switchers, not outcome switchers.',
        '- Between-group confidence intervals include covariance for choosers appearing in both groups.',
        '- Read the CIs rather than interpreting failure to reject as similarity. The two equivalence margins are exploratory defaults.',
        '- Common-support adjustment uses identical weights across both groups and both desert states. '
        'No overlap, especially for rating-defined elite groups, is reported as such.',
        '- Accounts below 30 clusters are flagged; t intervals do not remove the limitations of few-cluster inference.','',
        '## Files','',
        '- `group_summary.csv`: rates, sample sizes, grant shares, raw ratio, chooser FE.',
        '- `estimates.csv`: confidence intervals and standard errors for every estimand.',
        '- `between_group_contrasts.csv`: group differences with covariance-aware intervals.',
        '- `common_support_adjustment.csv`: adjusted desert comparisons and retained support.',
        '- `metadata_coverage.csv`: title-source coverage separately by outcome and desert state.',
        '- `composition.csv`: rating, speed/stage and clock composition by group.',
        '- `RESULTS.json`: complete aggregate output and provenance.','',
        'All results are descriptive robustness analyses. No empirical conclusion has been hardcoded.']
    (out/'RESULTS.md').write_text('\n'.join(lines)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=DEFAULT_PROJECT)
    parser.add_argument('--panel-root',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cache',type=Path)
    parser.add_argument('--profile-file',action='append',type=Path,default=[])
    parser.add_argument('--extra-streamers',type=Path)
    parser.add_argument('--threads',type=int,default=10)
    parser.add_argument('--memory-gb',type=int,default=6)
    parser.add_argument('--min-cell',type=int,default=10)
    parser.add_argument('--max-directory-pages',type=int,default=400)
    args=parser.parse_args()
    if not 1<=args.threads<=10 or args.memory_gb<2 or args.min_cell<1:
        parser.error('Use 1-10 threads, memory-gb>=2 and min-cell>=1')
    import duckdb
    if duckdb.__version__!='1.5.5':
        raise RuntimeError('Use supplied requirements: duckdb==1.5.5')
    if args.out.exists():
        raise FileExistsError('Output directory already exists; choose a fresh run name')
    args.out.mkdir(parents=True)
    started=time.monotonic()
    cache=args.cache or args.project_root/'derived/replication/audience_visibility_v100_PRIVATE'
    cache.mkdir(parents=True,exist_ok=True)
    lock=(cache/'run.lock').open('a+')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another audience run is using this private cache')
    authority=json.loads((HERE/'panel_authority.json').read_text())
    paths=verify_panel(args.panel_root or args.project_root/PANEL_REL,authority)
    streamers,registry_info=collect_directory(cache/'directory_snapshot',args.max_directory_pages)
    extras,extra_info=read_extra_streamers(args.extra_streamers) if args.extra_streamers else ({},None)
    for uid,title in extras.items():
        streamers.setdefault(uid,title)
    registry_hash=hashlib.sha256(json.dumps(sorted(streamers.items()),separators=(',',':')).encode()).hexdigest()
    profile_paths=args.profile_file or [args.project_root/PROFILE_REL]
    if not args.profile_file and not profile_paths[0].exists():
        profile_paths=[]
        log('Certified title snapshot is absent. Running rating/directory analysis; title coverage will be reported as missing.')
    with tempfile.TemporaryDirectory(prefix='analysis_work_',dir=cache) as work:
        db=duckdb.connect(str(Path(work)/'analysis.duckdb'))
        configure(db,args.threads,args.memory_gb,Path(work)/'spill')
        try:
            profile_sources,profile_info=load_profiles(db,profile_paths)
            register_streamers(db,streamers)
            code_hashes={p.name:sha(p) for p in sorted(HERE.glob('*.py'))}
            key=hashlib.sha256(json.dumps({'code':code_hashes,'profiles':profile_sources,
                 'registry':registry_hash,'authority':sha(HERE/'panel_authority.json')},sort_keys=True).encode()).hexdigest()[:20]
            build_base(db,paths,authority['monthly_inputs'],cache/('panel_'+key))
            qa=validate_sample(db,authority['expected_counts'])
            log(f"Current sample reproduced exactly: {qa['opportunities']:,} opportunities")
            coverage=quality_tables(db)
            all_summary,all_estimates,all_contrasts,adjusted,composition=[],[],[],[],[]
            # Full sample provides a directly comparable baseline.
            make_cells(db,'0')
            base_tag={'threshold':0,'definition':'full_sample','view':'full_sample'}
            s,e,c=estimate_cells(db,base_tag,qa['opportunities'],qa['kind_draws'])
            for r in s+e:r['group']='full_sample'
            all_summary+=s;all_estimates+=e
            for threshold in (2400,2200,2500):
                for definition in DEFINITIONS:
                    for view in ('chooser','either_player'):
                        tag={'threshold':threshold,'definition':definition,'view':view}
                        log(f'Estimating {threshold}, {definition}, {view}')
                        expr=group_expression(threshold,definition,view)
                        make_cells(db,expr)
                        s,e,c=estimate_cells(db,tag,qa['opportunities'],qa['kind_draws'])
                        if sum(r['opportunities'] for r in s)!=qa['opportunities'] or sum(r['kind_draws'] for r in s)!=qa['kind_draws']:
                            raise RuntimeError('Subgroup counts do not partition the main sample')
                        all_summary+=s;all_estimates+=e;all_contrasts+=c
                        if threshold==2400:
                            composition+= [dict(tag,**r) for r in records(db,f'''SELECT {expr} g,speed,
                              count(*) n,sum(y)::BIGINT k,avg(ce) mean_chooser_rating,
                              avg(de) mean_opponent_rating,avg(ply) mean_ply,
                              avg(cc) mean_chooser_clock_s,avg(dc) mean_opponent_clock_s,
                              avg(cp::INTEGER) chooser_profile_coverage,
                              avg(dp::INTEGER) opponent_profile_coverage FROM base GROUP BY g,speed''')]
                            adjusted+=standardize(db,expr,tag,args.min_cell)
                        # Durable aggregate checkpoints after every specification.
                        atomic_json(args.out/'PROGRESS.json',{'completed_specification':tag,'completed_utc':now()})
                        write_csv(args.out/'group_summary.csv',all_summary)
                        write_csv(args.out/'estimates.csv',all_estimates)
                        write_csv(args.out/'between_group_contrasts.csv',all_contrasts)
            # A separate coverage-restricted diagnostic is intentionally not the
            # primary estimator: the original profile acquisition selected on y.
            profile_support=one(db,'SELECT count(*) n FROM base WHERE cp AND dp')['n']
            payload={'status':'COMPLETED_WITH_MEASUREMENT_LIMITATIONS','version':VERSION,
              'completed_utc':now(),'elapsed_seconds':time.monotonic()-started,
              'sample_qa':qa,'panel_sha256_verified':True,
              'authority_sha256':sha(HERE/'panel_authority.json'),'code_sha256':code_hashes,
              'repository_commit':authority['repository_commit'],
              'streamer_listing':{'started_utc':registry_info['started_utc'],
                'completed_utc':registry_info['completed_utc'],'pages':len(registry_info['pages']),
                'directory_accounts':registry_info['unique_users'],'total_with_extras':len(streamers),
                'registry_sha256':registry_hash,'extra_list':extra_info,
                'scope':registry_info['scope'],'limitation':registry_info['limitation']},
              'profiles':{'sources':profile_sources,**profile_info,'opportunities_with_both_profiles':profile_support,
                'selection':'Original acquisition oversampled granting accounts; not a title census'},
              'specification':{'primary_rating_threshold':2400,'sensitivity_thresholds':[2200,2500],
                'human_chess_titles':TITLES,'LM_included':False,'rating_timing':'at each opportunity',
                'known_title_timing':'at profile or directory observation; post-panel',
                'fe':'kind_draw ~ competitive + chooser-by-group intercepts, estimated separately by group',
                'fe_weights':'n_competitive*n_worse/(n_competitive+n_worse)',
                'fe_CR1':'G/(G-1)*(N-1)/(N-G-1), N and G restricted to state-switching accounts',
                'contrast_covariance':'chooser scores summed across groups before squaring; group-specific finite-sample factors',
                'ci':'Student t, G-1 per estimate; min(G_A,G_B)-1 for group contrasts',
                'equivalence_margins_pp':[0.25,0.50],
                'equivalence_note':'Exploratory margins fixed in code, not author-approved substantive equivalence thresholds',
                'common_support':f'both ratings in 200-point bins, speed, calendar quarter, ply bins, both clock bins; min {args.min_cell} per group-state cell',
                'adjustment_SE':'Chooser-clustered conditional-on-strata/weights sandwich, G/(G-1)',
                'audience_presence_observed':False,'causal_audience_effect_identified':False},
              'runtime':{'python':platform.python_version(),'duckdb':duckdb.__version__,
                         'threads':args.threads,'memory_gb':args.memory_gb},
              'summary':all_summary,'estimates':all_estimates,'contrasts':all_contrasts,
              'adjusted':adjusted,'metadata_coverage':coverage}
            atomic_json(args.out/'RESULTS.json',payload)
            write_csv(args.out/'metadata_coverage.csv',coverage)
            write_csv(args.out/'common_support_adjustment.csv',adjusted)
            write_csv(args.out/'composition.csv',composition)
            write_report(args.out,payload)
        finally:
            db.close()
    # Reproducibility code is public; registry membership and private profiles are not.
    code_dir=args.out/'executed_code';code_dir.mkdir()
    for p in HERE.iterdir():
        if p.suffix in ('.py','.md','.json','.txt','.command'):
            shutil.copy2(p,code_dir/p.name)
    files=sorted(p for p in args.out.rglob('*') if p.is_file())
    manifest=''.join(sha(p)+'  '+p.relative_to(args.out).as_posix()+'\n' for p in files)
    (args.out/'SHA256SUMS.txt').write_text(manifest)
    atomic_json(args.out/'_SUCCESS.json',{'status':'AUDIENCE_ROBUSTNESS_V100_COMPLETED',
       'completed_utc':now(),'results_sha256':sha(args.out/'RESULTS.json'),
       'manifest_sha256':sha(args.out/'SHA256SUMS.txt'),
       'limitations':'Audience unmeasured; streamer registry incomplete; sampled post-panel title coverage',
       'private_rows_in_export':False})
    archive=args.out.with_suffix('.zip')
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(args.out.rglob('*')):
            if p.is_file():z.write(p,args.out.name+'/'+p.relative_to(args.out).as_posix())
    sidecar=archive.with_name(archive.name+'.sha256')
    sidecar.write_text(sha(archive)+'  '+archive.name+'\n')
    log('AUDIENCE_ROBUSTNESS_V100_COMPLETED')
    print(f'RESULT_ZIP={archive}\nRESULT_SHA256={sidecar}',flush=True)
    fcntl.flock(lock,fcntl.LOCK_UN)
    lock.close()

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        log(f'FAILED: {type(exc).__name__}: {exc}')
        raise
