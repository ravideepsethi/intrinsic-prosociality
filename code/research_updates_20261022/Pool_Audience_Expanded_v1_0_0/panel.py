"""Frozen main-panel verification reused from audience v1.0.0."""
import concurrent.futures
from common import qs, sha, log, one

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
