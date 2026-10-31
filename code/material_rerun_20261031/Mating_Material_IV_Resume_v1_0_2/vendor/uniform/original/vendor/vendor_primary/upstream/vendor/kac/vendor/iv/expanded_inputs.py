"""Authenticate the two reviewed reports and their private checkpoint files."""
from pathlib import Path
import pyarrow.parquet as pq
import local_io as io
import audit_inputs as inherited

PKG=Path(__file__).resolve().parent


def authenticate(project):
    inputs=inherited.authenticate(project)
    authority=io.load(PKG/'evidence/expanded_authority.json')
    roots={}
    for label,folder in [('audit','chooser_iv_repeated_audit_v100_PRIVATE'),
                         ('followup','chooser_iv_selection_followup_v100_PRIVATE')]:
        a=authority[label];root=project/'derived/replication'/folder/a['config_sha256'][:12]
        inputs['snapshots'].append(io.checked(root/'config.json'))
        if io.cfgsha(io.load(root/'config.json'))!=a['config_sha256']:
            raise RuntimeError(label+' configuration differs from the reviewed report')
        inputs['snapshots'].append(io.checked(root/'report/_DONE.json',a['report_receipt_sha256']))
        io.complete(root/'report',a['config_sha256'])
        inputs['snapshots'].append(io.checked(root/'analysis/_DONE.json'))
        receipt=io.complete(root/'analysis',a['config_sha256'])
        if not receipt:raise RuntimeError(label+' private analysis is incomplete')
        roots[label]=root
    # The follow-up report explicitly pins both private analysis Parquets.
    f=io.load(PKG/'evidence/followup_summary.json')
    for rec in f['validation']['files']:
        inputs['snapshots'].append(io.checked(roots['followup']/'analysis'/rec['path'],rec['sha256'],rec['bytes']))
    inputs['audit']=str(roots['audit']/'analysis/analysis.parquet')
    inputs['followup_comparison']=str(roots['followup']/'analysis/comparison.parquet')
    inputs['followup_iv']=str(roots['followup']/'analysis/iv.parquet')
    inputs['snapshots'].append(io.checked(inputs['audit']))
    if pq.ParquetFile(inputs['audit']).metadata.num_rows!=14058373:
        raise RuntimeError('Audited first-pair universe row count changed')
    if pq.ParquetFile(inputs['followup_comparison']).metadata.num_rows!=1661563:
        raise RuntimeError('Reviewed pool comparison row count changed')
    inputs['expanded_authority']=authority
    return inputs


def bridge(c,view,baseline,expected):
    c.execute('CREATE OR REPLACE VIEW previous AS SELECT * FROM '+io.parq([baseline]))
    n=c.execute(f'SELECT count(*) FROM {view} WHERE first_recipient AND complete90').fetchone()[0]
    if n!=expected:raise RuntimeError('Baseline cohort row count differs')
    bad=c.execute(f'''SELECT count(*) FROM (SELECT * FROM {view} WHERE first_recipient AND complete90) a FULL OUTER JOIN previous b USING(game_id)
       WHERE a.row_id IS NULL OR b.pilot_row IS NULL OR a.recipient_id<>b.recipient_id OR a.opponent_id<>b.chooser_id
       OR a.received IS DISTINCT FROM b.received OR a.archive_start_ms<>b.archive_start_ms OR a.anchor_ms<>b.anchor_ms
       OR a.observed_y IS DISTINCT FROM b.other_started_after_y OR a.reached IS DISTINCT FROM b.other_started_after_reached
       OR a.outcome_gid IS DISTINCT FROM b.outcome_gid OR a.outcome_t IS DISTINCT FROM b.outcome_t
       OR a.fair_90<>b.own_fair_n OR a.kind_90<>b.own_kind_n
       OR a.disconnect_90<>b.prior_disconnects OR a.receipt_90<>b.prior_receipts''').fetchone()[0]
    if bad:raise RuntimeError('Expanded data disagree with reviewed first-exposure outcomes/history')
    for lag in (7,30):
        for name in ('n','counterparts','pair_removed','raw','expected','adjusted'):
            field=f'{name}_{lag}d'
            bad=c.execute(f'''SELECT count(*) FROM {view} a JOIN previous b USING(game_id)
              WHERE (isfinite(a.{field}) IS DISTINCT FROM isfinite(b.{field}))
                 OR (isfinite(a.{field}) AND abs(a.{field}-b.{field})>1e-11)''').fetchone()[0]
            if bad:raise RuntimeError('Historical score differs from baseline: '+field)
    return dict(status='FIRST_EXPOSURE_BRIDGE_OK',rows=n)
