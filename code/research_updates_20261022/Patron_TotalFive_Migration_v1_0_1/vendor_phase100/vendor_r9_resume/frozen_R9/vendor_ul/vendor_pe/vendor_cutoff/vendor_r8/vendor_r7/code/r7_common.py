"""R7 contracts. Vendored producers stay byte-for-byte unchanged."""
from pathlib import Path
import sys, os, math, json, time, hashlib, contextlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor_phase50/code'))
import phase50_common as upstream
from phase50_common import np, pa, pq, io, num, stats, design, arrays, stable_stage, finish_connection, threads_one, no_network, DAY
import env_common, env_numerics, env_rates, env_models
VERSION = '1.0.3'
X0 = ['recipient_rating','rating_gap','rating_gap_square','abs_rating_gap',
      'log_opponent_prior_decisions','log_opponent_prior_counterparts','opponent_history_expected_rate',
      'fair_history_present_90','log_fair_90','kind_ever_90','kind_rate_90','log_disconnect_90',
      'log_receipt_90','log_volume_30','log_claim_90']
NH = X0[:7]
T30 = list(env_common.RECENT)
T15 = T30 + X0[7:]
XC = ['competitive_expected_rate','log_competitive_decisions','log_competitive_counterparts']
ENV = list(env_common.ENV_NAMES)
SD = dict(env_models.SD)
TABLES = ['A_joint_balance','A_joint_tests','A_predicted_outcome','B_estimates','B_balance',
          'B_joint_balance','B_ladder','B_entry','B_placebo','B_placebo_contrasts','B_indicator',
          'B_repeated','C_classes','C_prior_by_class','C_entry_by_class','C_restricted_iv']

def stable_stage(root,conf,producer,inputs=()):
    """Bind dependency identities across restarts, beyond upstream within-run checks.

    SHA256 is recorded on first creation; unchanged size/mtime signatures permit
    fast resume after the parent input-authentication gate. Any changed signature
    stops, even when bytes happen to remain equal. Output hashes are always checked.
    """
    root=Path(root);inputs=[Path(p) for p in inputs]
    before=[dict(path=str(p.resolve()),signature=io.sig(p)) for p in inputs]
    if (root/'_DONE.json').exists():
        record=io.load(root/'dependencies_PRIVATE.json')
        if [{k:r[k] for k in ('path','signature')} for r in record]!=before:
            raise RuntimeError('Checkpoint input changed since creation: '+str(root))
        result=io.stage(root,conf,producer)
    else:
        record=[dict(r,sha256=io.sha(p)) for r,p in zip(before,inputs)]
        def build(tmp):
            result=producer(tmp) or {}
            if [dict(path=str(p.resolve()),signature=io.sig(p)) for p in inputs]!=before:
                raise RuntimeError('Input changed while producing stage')
            io.js(tmp/'dependencies_PRIVATE.json',record)
            return result
        result=io.stage(root,conf,build)
    if [dict(path=str(p.resolve()),signature=io.sig(p)) for p in inputs]!=before:
        raise RuntimeError('Input changed while verifying stage')
    return result

# Adapt only new R7 stages; no vendored source or completed upstream receipt is edited.
env_rates.stable_stage=stable_stage
env_common.stable_stage=stable_stage

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ',1)
        io.checked(io.child(ROOT,name),digest)

def subset(d,m):
    return d if np.asarray(m,bool).all() else {k:v[m] for k,v in d.items()}

def comp_mask(d):
    return (d['comp_n_7d']>=5)&np.isfinite(d['comp_adjusted_7d'])&np.isfinite(d['comp_expected_7d'])

def feature_design(d, level='X0', recipient_fe=False):
    """Exact frozen transforms; no imputation beyond named history conventions."""
    xs,names,ts,tnames,groups,missing=stats.controls(d,True)
    if names != X0 or any(missing.values()):
        raise RuntimeError('Frozen X0 schema/finite-value contract changed: '+str(missing))
    values=dict(zip(names,xs)); traits=dict(zip(tnames,ts))
    selected=list(X0 if not level.startswith('NH') else NH)
    if 'XC' in level:
        if not comp_mask(d).all(): raise RuntimeError('XC requires competitive-supported rows')
        for name,v in zip(XC,[d['comp_expected_7d'],np.log1p(d['comp_n_7d']),np.log1p(d['comp_counterparts_7d'])]):
            values[name]=(v-v.mean())/max(float(v.std()),1e-12)
        selected+=XC
    if 'ENV' in level or 'volume' in level:
        supported=np.asarray(d['environment_supported'],bool)
        availability='indicator' in level
        if not availability and not supported.all(): raise RuntimeError('ENV missing outside indicator model')
        terms=ENV if 'ENV' in level else ENV[:1]
        if 'volume_own' in level: terms=ENV[:2]
        if 'volume_chooser' in level: terms=[ENV[0],ENV[2]]
        for name in terms:
            v=np.asarray(d[name],float).copy()
            if not np.isfinite(v[supported]).all(): raise RuntimeError('Supported ENV value missing')
            if availability:v[~supported]=0
            values[name]=(v-v.mean())/max(float(v.std()),1e-12); selected.append(name)
        if availability:
            # Unscaled so its coefficient is a supported-minus-unsupported contrast.
            values['env_supported']=supported.astype(float);selected.append('env_supported')
    if recipient_fe: groups=groups+[d['recipient_id']]
    return np.column_stack([values[k] for k in selected]), selected, traits, groups

def metadata(d,sample,level,instrument,**extra):
    out=dict(control_level=level,instrument=instrument,sample=sample,n=len(d['row_id']),
        row_set_sha256=design.row_digest(d['row_id']),reference_score_SD=SD[instrument],
        native_residual_score_SD=None,units='percentage points per reference score SD',
        clustering='shared_account_OR_date_CR0',nominal_interim_intervals=True,
        diagnostic_after_reviewed_results=True,causal_identification_certified=False,
        generated_scores_treated_as_fixed=True)
    out.update(extra)
    return out

def load_columns(path, extra=()):
    wanted=list(dict.fromkeys([k for k in env_common.MODEL_COLUMNS if k not in env_common.ENTRY_COLUMNS]
            +env_common.COMP_COLUMNS+env_common.ENTRY_COLUMNS+ENV+
            ['environment_supported','complete','games','row_id','game_id','anchor_ms','received','y','reached','complete90',
             'ply_count','engine_eval_cp_disconnected','disconnected_clock_last_obs_s','recipient_disconnect_main']+list(extra)))
    names=pq.ParquetFile(path).schema_arrow.names
    return arrays(io.read(path,[k for k in wanted if k in names]))

def write_rows(folder,name,rows):
    """All result tables get JSON, CSV, Parquet; nested cells serialized in flat copies."""
    import csv
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    io.js(folder/(name+'.json'),rows)
    flat=[{k:json.dumps(io.clean(v),sort_keys=True) if isinstance(v,(list,dict,tuple)) else io.clean(v) for k,v in r.items()} for r in rows]
    keys=sorted(set().union(*(r.keys() for r in flat))) if flat else ['status']
    with (folder/(name+'.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader();w.writerows(flat)
    if flat:
        # Arrow's from_pylist otherwise takes only the first row's keys.
        table=pa.Table.from_pylist([{k:r.get(k) for k in keys} for r in flat])
    else:table=pa.table({'status':pa.array([],type=pa.string())})
    io.table(folder/(name+'.parquet'),table)


# Numeric columns actually required for A/B. Exclude game strings, move fields,
# unused entry flags and all other model-source payload from fitting workers.
FIT_COLUMNS = list(dict.fromkeys([
    'row_id','recipient_id','opponent_id','archive_start_ms','month_code','tc_base_s','tc_inc_s',
    'recipient_rating','opponent_rating','n_7d','counterparts_7d','expected_7d','adjusted_7d',
    'pre_games_30d','comp_n_7d','comp_counterparts_7d','comp_expected_7d','comp_adjusted_7d',
    'environment_supported','received','y','reached','complete90','analysis_entry_90',
    'recipient_disconnect_main','active_timeout'] + ENV +
    [f'{name}_{days}' for days in (30,90) for name in ('fair','kind','disconnect','receipt','claim')]))

def load_fit_columns(path, extra=()):
    names=set(pq.ParquetFile(path).schema_arrow.names)
    # Read one column at a time: Arrow cannot retain another full numeric table
    # while NumPy conversion/selection allocates the model arrays.
    result={}
    for name in dict.fromkeys(FIT_COLUMNS+list(extra)):
        if name in names:result[name]=io.arr(io.read(path,[name]),name)
    return result
