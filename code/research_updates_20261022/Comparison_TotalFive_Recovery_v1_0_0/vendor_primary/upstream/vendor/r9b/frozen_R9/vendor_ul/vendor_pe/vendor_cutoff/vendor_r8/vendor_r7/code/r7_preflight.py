"""Validate every planned input schema before starting expensive model fits."""
from r7_common import *

BASE={'row_id','recipient_id','opponent_id','archive_start_ms','month_code','tc_base_s','tc_inc_s',
      'recipient_rating','opponent_rating','n_7d','counterparts_7d','expected_7d','adjusted_7d',
      'pre_games_30d'} | {f'{k}_{days}' for days in (30,90) for k in ('fair','kind','disconnect','receipt','claim')}
COMP={'comp_n_7d','comp_adjusted_7d','comp_expected_7d','comp_counterparts_7d'}


def required(job):
    columns=set(BASE);kind=job['kind'];level=job['level'];selection=job['selection']
    columns.update({'iv':{'received','y','reached'},'ordinary':{'y','reached'},
                    'entry':{'analysis_entry_90','recipient_disconnect_main','active_timeout'}}[kind])
    if kind=='entry' and job.get('part_a',True):columns.update(['y','complete90'])
    if 'env' in selection or 'ENV' in level or 'volume' in level:columns.add('environment_supported')
    if 'ENV' in level or 'volume' in level:columns.update(ENV)
    if 'comp' in selection or 'XC' in level or job['instrument']=='competitive':columns.update(COMP)
    return columns


def check(jobs,paths=None,binding=None,include_c=False):
    schemas={};rows=[]
    for job in jobs:
        path=job['input']
        if path not in schemas:schemas[path]=set(pq.ParquetFile(path).schema_arrow.names)
        missing=required(job)-schemas[path]
        if missing:raise RuntimeError('R7 input preflight: '+job['sample']+' '+job['level']+' missing columns '+', '.join(sorted(missing)))
        rows.append(dict(sample=job['sample'],control_level=job['level'],instrument=job['instrument'],
                         required_columns=len(required(job)),schema_passed=True))
    if include_c:
        for sample in ('S0','F50'):
            env_common.checked_columns(paths[sample],['game_id','recipient_id','opponent_id','recipient_disconnect_main'] if sample=='F50' else ['game_id','recipient_id','opponent_id'])
        needed=['game_id','disconnected_user_id','chooser_user_id','ply_count','engine_eval_cp_disconnected','disconnected_clock_last_obs_s','fair_competitive']
        for rec in binding['source']['panels']:env_common.checked_columns(rec['path'],needed)
    return dict(status='INPUT_SCHEMA_PREFLIGHT_PASSED',model_count=len(jobs),models=rows,
                part_C_endpoint_schemas_checked=include_c)
