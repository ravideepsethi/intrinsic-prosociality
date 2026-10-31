"""Reapply the frozen focal-pair restriction and Patron rematching appendix."""
from __future__ import annotations
from pathlib import Path
import shutil
import pandas as pd
from source import frequent_dyad_v101 as census
from source import paperwide_dyad_v100 as audit
from source import dyad_auth
from source import wave3b1_helpers as h

q=h.q


def run(args,sample,bridge,state,digest,public):
    old=args.project_root/'derived/replication/frequent_dyad_census_24m_v101_PRIVATE'
    authentication=dyad_auth.authenticate_frequent_state(old,args.hash_workers)
    flags_state=state/'dyad_flags';flags_state.mkdir(parents=True,exist_ok=True)
    flags,receipt=census.build_stage07_flags(
        stage_paths=[Path(m['path']) for m in sample['month_records']],
        pair_paths=[old/f'frequent_pairs/pair_bucket={i:03d}/part-00000.parquet' for i in range(128)],
        player_path=old/'frequent_players_private.parquet',state=flags_state,
        config_sha256=digest,thresholds=[2,3,5,10],expected_rows=sample['authority']['rows'],
        threads=args.threads,memory_limit=args.memory_limit)
    def join(directory):
        db=h.prior.connect(directory/'work.duckdb',args,directory/'spill')
        try:
            panel='['+','.join(q(m['path']) for m in sample['month_records'])+']'
            flag_sql='['+','.join(q(p) for p in sorted(flags.rglob('*.parquet')))+']'
            target=directory/'joined_private.parquet'
            db.execute(f"""COPY (SELECT p.game_id,p.chooser_username_norm,p.kind_draw,
                p.fair_competitive,p.api_speed::VARCHAR AS speed,f.pair_games_24m
                FROM read_parquet({panel},union_by_name=true,hive_partitioning=false) p
                JOIN read_parquet({flag_sql},union_by_name=true,hive_partitioning=false) f
                  ON p.game_id=f.game_id
              ) TO {q(target)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)""")
            qa=h.records(db,f"""SELECT count(*) AS rows,count(DISTINCT game_id) AS unique_games,
              count(*) FILTER(WHERE kind_draw) AS kind_draws,count(*) FILTER(WHERE fair_competitive) AS fair_rows,
              count(*) FILTER(WHERE pair_games_24m IS NULL OR pair_games_24m<1) AS bad_pair
              FROM read_parquet({q(target)})""")[0]
            expected={'rows':sample['authority']['rows'],'unique_games':sample['authority']['rows'],
                      'kind_draws':sample['authority']['kind_draws'],'fair_rows':sample['authority']['fair_rows'],'bad_pair':0}
            h.eq(qa,expected,'new-panel dyad join conservation')
        finally: db.close()
        (directory/'work.duckdb').unlink(missing_ok=True)
        shutil.rmtree(directory/'spill',ignore_errors=True)
        return qa
    joined,_=h.prior.checkpoint(state,'dyad_join',digest,join)
    work=state/'dyad_rematch_work';work.mkdir(parents=True,exist_ok=True)
    view=work/'project_view';destination=view/audit.PROFILE_REL
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.is_symlink():
        h.eq(destination.resolve(),bridge.resolve(),'dyad snapshot bridge target')
    elif destination.exists(): raise RuntimeError('Unexpected file at dyad project-view snapshot')
    else: destination.symlink_to(bridge.resolve())
    audit.EXPECTED_PROFILE_ROWS=census.parquet_rows(bridge)
    audit.EXPECTED_STAGE07_ROWS=sample['authority']['rows']
    db=h.prior.connect(work/'work.duckdb',args,work/'spill')
    try:
        rows,support=audit.patron_sensitivity(db,view,joined/'joined_private.parquet',work)
    finally: db.close()
    h.common.write_csv(public/'dyad_patron_rematches.csv',pd.DataFrame(rows))
    h.save_json(public/'dyad_support.json',support)
    h.save_json(public/'dyad_authentication.json',{'invariant_index':authentication,'new_flags':receipt})
    h.save_json(public/'dyad_scope.json',{
      'status':'FROZEN_DYAD_APPENDIX_REBUILT','matching':'fresh deterministic 1:3 within the frozen new-main target pool; kind role additionally requires a retained fair kind draw',
      'profile_outcome':'August only; nonreturns and never-queried targets remain missing',
      'focal_opportunities_only':True,'drop_other_games_of_players':False,
      'pair_frequency':'all standard-rated games in the whole 24-month census; includes post-focal games',
      'interpretation':'descriptive sensitivity, not pre-focal reputation identification',
      'frozen_available_profile_rule':'match first using all target accounts, then use returned outcomes; no focal-return group gate in this distinct appendix',
      'not_the_main_1to3_estimate':True,'restrictions':[r['restriction'] for r in rows]})
    return {'restrictions':len(rows),'status':'DYAD_APPENDIX_COMPLETE'}
