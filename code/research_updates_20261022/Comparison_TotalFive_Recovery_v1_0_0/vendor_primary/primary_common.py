"""New all-time cohort namespace; upstream statistical producers are unchanged."""
from pathlib import Path
import os, sys, json, time, gc, hashlib
PACKAGE = Path(__file__).resolve().parent
UPSTREAM = PACKAGE / 'upstream'
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.path.insert(0, str(UPSTREAM))
import local_common as lc
from local_common import (np, DAY, SD, require, log, heartbeat, sha, key, load, save,
                         csv_out, quote, parq, db, copy_query, cached, seal, inference)
import iv_followups as iv
from iv_followups import inputs, models, frozen
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = '1.0.0'
EXPECTED_N = 3103280
EXPECTED_RECIPIENTS = 1835628
R12_PREFIX = '4df83f1178f3'
DEFINITION = dict(
    support='At least five eligible grant-or-claim decisions by opponent j across the observed 24-month panel, after excluding every j-to-i decision and both author accounts in both roles; finite adjusted score and expected rate.',
    no_pre_exposure_opponent_support_screen=True,
    spacing='Recipient/start/row_id order; accept only if start is strictly greater than previous accepted anchor + gap days; unsupported exposures do not start a window. Spacing precedes complete90/history-window cuts.',
    first_exposure='Original first_recipient flag: first observed candidate exposure, followed by all-time support and observation-window cuts. Not first supported exposure.',
    history='Existing 97-day coverage and seven-day-buffered recipient history controls retained; distinct from opponent score eligibility.',
    score='All-time Score A, donor-own-month held-out-pair-fold state reference, every focal-pair decision removed.',
    covariance='shared-account-OR-exposure-date CR0; generated scores treated as fixed',
    score_scale=SD,
    scale_note='Fixed R9 reference SD retained for comparability; native residual SD also reported. This is not claimed to be the new cohort SD.',
    primary_controls='X0_ENV_indicator', secondary_controls='X0',
    intervals='95% normal Wald; no Anderson-Rubin',
    author_accounts='Excluded in both exposure roles, donors, and behavioral histories')

def verified_receipt(path, expected_key=None):
    path=Path(path); receipt=load(str(path)+'.ok.json')
    if expected_key is not None: require(receipt['key']==expected_key, 'Checkpoint key differs: '+str(path))
    require(sha(path)==receipt['sha256'], 'Checkpoint bytes changed: '+str(path))
    return receipt

def ensure_unique(c, view, expected=None):
    n,u=c.execute('SELECT count(*),count(DISTINCT row_id) FROM '+view).fetchone()
    require(n==u, 'Duplicate row IDs in '+view)
    if expected is not None: require(n==expected, 'Unexpected row count in '+view)
    return n

def bridge(c, left, right, columns, label, expected=None):
    n=c.execute('SELECT count(*) FROM '+left+' JOIN '+right+' USING(row_id)').fetchone()[0]
    if expected is not None: require(n==expected, label+': overlap changed')
    terms=['a."'+x+'" IS DISTINCT FROM b."'+x+'"' for x in columns]
    bad=c.execute('SELECT count(*) FROM '+left+' a JOIN '+right+' b USING(row_id) WHERE '+' OR '.join(terms)).fetchone()[0]
    require(bad==0,label+': identity/history/outcome mismatch')
    return n

def cached_json(path, ck, producer):
    if cached(path,ck): return load(path)
    value=producer();save(path,value);seal(path,ck);return value

def verify_package():
    manifest=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1);path=(PACKAGE/name).resolve()
        require(path.is_relative_to(PACKAGE),'Unsafe manifest member')
        require(sha(path)==digest,'Package checksum differs: '+name)
    return sha(manifest)
