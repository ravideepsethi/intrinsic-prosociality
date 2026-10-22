"""Both-player exclusions, overlap and missing-data diagnostics."""
import json
import os
from common import TITLES, qs, sha, one, records, atomic_json, log
from estimates import make_cells, estimate_cells

PANEL_REL = 'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel'
REQUIRED = {'chooser_username_norm','disconnected_username_norm','kind_draw',
 'fair_competitive','clearly_worse','chooser_elo','disconnected_elo','game_id'}
STAGES = {
  '01_elite_title_streamer':'elite OR titled OR streamer',
  '02_add_profile_links':'elite OR titled OR streamer OR channel_link',
  '03_add_recorded_tv':'elite OR titled OR streamer OR channel_link OR tv_positive',
}
SCOPES = {'all_available_metadata':'true',
          'both_profiles_observed':'cp AND dp',
          'both_profiles_and_numeric_tv':'cp AND dp AND ctv_known AND dtv_known'}

def build_base(db, paths, months, cache):
    cache.mkdir(parents=True,exist_ok=True)
    thin=[]
    titles=','.join(qs(t) for t in TITLES)
    for path,a in zip(paths,months):
        dest=cache/(a['month']+'.parquet');stamp=cache/(a['month']+'.json')
        if dest.exists() and stamp.exists():
            r=json.loads(stamp.read_text())
            if r['sha256']!=sha(dest) or r['source_sha256']!=a['sha256']:
                raise ValueError('Expanded private cache hash differs; no overwrite performed')
            log('Reusing expanded joined panel '+a['month'])
        else:
            schema={r[0] for r in db.execute(f'DESCRIBE SELECT * FROM read_parquet({qs(path)})').fetchall()}
            if not REQUIRED<=schema: raise ValueError('Main panel lacks required fields')
            db.execute(f'CREATE OR REPLACE TEMP VIEW p AS SELECT * FROM read_parquet({qs(path)})')
            qa=one(db,'''SELECT count(*) n,count(*) FILTER(WHERE
              chooser_username_norm IS NULL OR trim(chooser_username_norm)='' OR
              disconnected_username_norm IS NULL OR trim(disconnected_username_norm)='' OR
              kind_draw IS NULL OR fair_competitive IS NULL OR clearly_worse IS NULL OR
              (fair_competitive AND clearly_worse)) bad FROM p''')
            if qa['bad'] or qa['n']!=a['rows']: raise ValueError('Invalid panel outcomes, states or account keys')
            expr=f'''SELECT lower(trim(p.chooser_username_norm)) chooser,
              lower(trim(p.disconnected_username_norm)) opponent,cast(p.kind_draw AS INTEGER) y,
              CASE WHEN p.fair_competitive THEN 1 WHEN p.clearly_worse THEN 0 ELSE 2 END::INTEGER state,
              p.chooser_elo ce,p.disconnected_elo de,
              pc.username IS NOT NULL cp,pd.username IS NOT NULL dp,
              (coalesce(pc.titled,false) OR coalesce(sc.title IN ({titles}),false)) ct,
              (coalesce(pd.titled,false) OR coalesce(sd.title IN ({titles}),false)) dt,
              coalesce(pc.bot,false) cb,coalesce(pd.bot,false) dbot,
              (sc.username IS NOT NULL OR coalesce(pc.positive_streamer,false)) cs,
              (sd.username IS NOT NULL OR coalesce(pd.positive_streamer,false)) ds,
              coalesce(pc.link,false) cl,coalesce(pd.link,false) dl,
              coalesce(pc.tv_known,false) ctv_known,coalesce(pd.tv_known,false) dtv_known,
              pc.tv_seconds ctv_seconds,pd.tv_seconds dtv_seconds,
              coalesce(pc.tv_positive,false) ctv,coalesce(pd.tv_positive,false) dtv
              FROM p LEFT JOIN profiles pc ON lower(trim(p.chooser_username_norm))=pc.username
              LEFT JOIN profiles pd ON lower(trim(p.disconnected_username_norm))=pd.username
              LEFT JOIN streamers sc ON lower(trim(p.chooser_username_norm))=sc.username
              LEFT JOIN streamers sd ON lower(trim(p.disconnected_username_norm))=sd.username'''
            tmp=dest.with_suffix('.tmp.parquet')
            db.execute(f'COPY ({expr}) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD)')
            n=one(db,f'SELECT count(*) n FROM read_parquet({qs(tmp)})')['n']
            if n!=a['rows']: raise ValueError('Audience join changed panel row count')
            os.replace(tmp,dest)
            atomic_json(stamp,{'sha256':sha(dest),'source_sha256':a['sha256'],'rows':n})
            log('Joined expanded audience flags: '+a['month'])
        thin.append(dest)
    db.execute('CREATE OR REPLACE TEMP VIEW base AS SELECT * FROM read_parquet(['+','.join(qs(p) for p in thin)+'])')
    return thin

def mark(db,threshold):
    db.execute(f'''CREATE OR REPLACE TEMP VIEW marked AS SELECT *,
      coalesce(ce>={int(threshold)} OR de>={int(threshold)},false) elite,
      ct OR dt titled,cs OR ds streamer,cl OR dl channel_link,ctv OR dtv tv_positive,
      cb OR dbot OR ce IS NULL OR de IS NULL OR ce<=0 OR de<=0 invalid
      FROM base''')

def stage_expression(stage):
    if stage=='00_no_exclusion': return '0'
    return f'CASE WHEN invalid THEN 3 WHEN ({STAGES[stage]}) THEN 1 ELSE 0 END'

def run_estimates(db,qa,out):
    summary=[];estimates=[];contrasts=[];partition=[]
    for threshold in (2400,2200,2500):
        mark(db,threshold)
        scopes=SCOPES if threshold==2400 else {'all_available_metadata':'true'}
        for scope,where in scopes.items():
            scope_n=one(db,f'SELECT count(*) n FROM marked WHERE {where}')['n']
            stages=['00_no_exclusion',*STAGES] if threshold==2400 else list(STAGES)
            for stage in stages:
                log(f'Estimating rating>={threshold}; {scope}; {stage}')
                expr=stage_expression(stage)
                make_cells(db,expr,where,source='marked')
                tag={'threshold':threshold,'metadata_scope':scope,'stage':stage}
                s,e,c=estimate_cells(db,tag,qa['opportunities'],qa['kind_draws'])
                if sum(x['opportunities'] for x in s)!=scope_n:
                    raise ValueError('Exclusion groups do not partition this scope')
                if stage=='00_no_exclusion':
                    for x in s+e: x['group']='all_opportunities_in_scope'
                for x in s:
                    x['scope_opportunities']=scope_n
                    x['share_of_scope_pct']=100*x['opportunities']/scope_n if scope_n else None
                summary+=s;estimates+=e;contrasts+=c
                if stage!='00_no_exclusion':
                    partition+= [dict(tag,**r) for r in records(db,f'''SELECT {expr} group_code,
                      CASE WHEN NOT cp OR NOT dp THEN 'profile_missing_for_one_or_both'
                           WHEN NOT ctv_known OR NOT dtv_known THEN 'profiles_observed_tv_missing'
                           ELSE 'profiles_and_numeric_tv_observed' END metadata_status,
                      state,count(*) n,sum(y)::BIGINT k,count(DISTINCT chooser) chooser_accounts
                      FROM marked WHERE {where} GROUP BY group_code,metadata_status,state''')]
                atomic_json(out/'PROGRESS.json',{'last_completed':tag})
                # Safe aggregate checkpoints; no account IDs in these tables.
                from common import write_csv
                write_csv(out/'group_summary.csv',summary)
                write_csv(out/'estimates.csv',estimates)
    return summary,estimates,contrasts,partition

def diagnostics(db):
    mark(db,2400)
    coverage=records(db,'''SELECT state,y,count(*) n,
      sum(cp::INTEGER)::BIGINT chooser_profile_observed,
      sum(dp::INTEGER)::BIGINT opponent_profile_observed,
      sum((cp AND dp)::INTEGER)::BIGINT both_profiles_observed,
      sum(ctv_known::INTEGER)::BIGINT chooser_numeric_tv_observed,
      sum(dtv_known::INTEGER)::BIGINT opponent_numeric_tv_observed,
      sum((ctv_known AND dtv_known)::INTEGER)::BIGINT both_numeric_tv_observed
      FROM base GROUP BY state,y ORDER BY state,y''')
    overlap=records(db,'''SELECT elite,titled,streamer,channel_link,tv_positive,invalid,
      count(*) n,sum(y)::BIGINT k,count(DISTINCT chooser) chooser_accounts,
      count(*) FILTER(WHERE state=1) competitive_n,
      sum(y) FILTER(WHERE state=1)::BIGINT competitive_k,
      count(*) FILTER(WHERE state=0) clearly_worse_n,
      sum(y) FILTER(WHERE state=0)::BIGINT clearly_worse_k
      FROM marked GROUP BY elite,titled,streamer,channel_link,tv_positive,invalid
      ORDER BY elite,titled,streamer,channel_link,tv_positive,invalid''')
    if sum(x['n'] for x in overlap)!=one(db,'SELECT count(*) n FROM base')['n']:
        raise ValueError('Overlap cells do not partition all opportunities')
    account_coverage=records(db,'''SELECT ever_grant,cp,ctv_known,count(*) chooser_accounts,
      sum(n)::BIGINT opportunities,sum(k)::BIGINT kind_draws FROM
      (SELECT chooser,max(y)=1 ever_grant,bool_or(cp) cp,bool_or(ctv_known) ctv_known,
       count(*) n,sum(y)::BIGINT k FROM base GROUP BY chooser)
      GROUP BY ever_grant,cp,ctv_known ORDER BY ever_grant,cp,ctv_known''')
    flags=[]
    for name,c,d in [('rating_at_least_2400','ce>=2400','de>=2400'),
                     ('known_chess_title','ct','dt'),('directory_or_structured_streamer','cs','ds'),
                     ('profile_channel_link','cl','dl'),('recorded_tv_positive','ctv','dtv')]:
        for role,expr in [('chooser',c),('opponent',d),('either_player',f'({c}) OR ({d})')]:
            flags.append(dict(flag=name,role=role,**one(db,f'''SELECT count(*) n,sum(y)::BIGINT k,
              count(DISTINCT chooser) chooser_accounts,count(DISTINCT opponent) opponent_accounts
              FROM base WHERE {expr}''')))
    duration=[]
    for role,prefix in [('chooser','c'),('opponent','d')]:
        duration += [dict(role=role,**r) for r in records(db,f'''SELECT
          CASE WHEN NOT {prefix}p THEN '0_no_cached_profile'
               WHEN NOT {prefix}tv_known THEN '1_tv_measurement_missing'
               WHEN {prefix}tv_seconds=0 THEN '2_recorded_zero'
               WHEN {prefix}tv_seconds<3600 THEN '3_positive_under_one_hour'
               WHEN {prefix}tv_seconds<36000 THEN '4_one_to_ten_hours'
               ELSE '5_ten_or_more_hours' END recorded_tv_category,
          count(*) n,sum(y)::BIGINT k,count(DISTINCT {role if role=='chooser' else 'opponent'}) accounts
          FROM base GROUP BY recorded_tv_category ORDER BY recorded_tv_category''')]
    return {'metadata_coverage_by_opportunity':coverage,'metadata_coverage_by_chooser':account_coverage,
      'flag_overlap':overlap,'individual_flag_coverage':flags,'recorded_tv_duration':duration}
