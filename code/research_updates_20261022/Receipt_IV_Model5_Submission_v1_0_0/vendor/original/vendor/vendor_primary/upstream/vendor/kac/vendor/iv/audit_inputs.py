"""Read-only validation of the certified main sample and completed IV rebuild."""
import csv
from pathlib import Path
import pyarrow.parquet as pq
import local_io as io
from preliminary_core import MONTHS
PKG=Path(__file__).resolve().parent
DEFAULT=Path('/Volumes/XT_Pro/lichess_kindness')
def relocate(project,path):
    p=Path(path)
    if p.is_absolute():
        try:p=p.relative_to(DEFAULT)
        except ValueError:raise RuntimeError('Authority path lies outside the recorded project')
    return io.child(project,p)

def authenticate(project):
    authority=io.load(PKG/'evidence/followup_authority.json')
    prior=io.load(PKG/'evidence/prior_authority.json')
    main=io.load(PKG/'evidence/main_sample_report.json')
    reviewed=io.load(PKG/'evidence/rebuild_summary.json')
    root=io.child(project,authority['rebuild_root_relative']);snaps=[]
    config=root/'config.json';snaps.append(io.checked(config))
    if io.cfgsha(io.load(config))!=authority['rebuild_config_sha256']:
        raise RuntimeError('The completed rebuild configuration differs from the reviewed result')
    paths={}
    for name in ('iv.parquet','comparison.parquet'):
        rec=next(x for x in reviewed['validation']['files'] if x['path']==name)
        p=root/'analysis'/name;snaps.append(io.checked(p,rec['sha256'],rec['bytes']))
        paths[name]=str(p)
    if pq.ParquetFile(paths['iv.parquet']).metadata.num_rows!=2112795 or pq.ParquetFile(paths['comparison.parquet']).metadata.num_rows!=1661563:
        raise RuntimeError('Reviewed analysis row counts changed')
    mroot=relocate(project,main['private_output_root']);panels=[]
    with io.heartbeat('Verifying certified main-sample files'):
        for entry in main['panel_outputs']:
            p=io.child(mroot,entry['relative_path']);snaps.append(io.checked(p,entry['sha256'],entry['size_bytes']))
            if pq.ParquetFile(p).metadata.num_rows!=entry['rows']:raise RuntimeError('Main panel row count changed')
            panels.append(str(p))
    if len(panels)!=24 or sum(pq.ParquetFile(p).metadata.num_rows for p in panels)!=41534331:
        raise RuntimeError('Wrong main panel coverage')
    lineage=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'lineage_PRIVATE.json'
    snaps.append(io.checked(lineage,prior['comparison_lineage_sha256']));line=io.load(lineage)
    projection=[]
    with io.heartbeat('Verifying all-source opportunity histories'):
        for shard,parts in enumerate(line['projections']):
            for entry in parts:
                p=relocate(project,entry['path']);snaps.append(io.checked(p,entry['sha256'],entry['bytes']))
                if pq.ParquetFile(p).metadata.num_rows!=entry['rows']:raise RuntimeError('History row count changed')
                projection.append(dict(path=str(p),month=entry['month'],shard=shard,rows=entry['rows']))
    if {(x['month'],x['shard']) for x in projection}!={(m,s) for m in MONTHS for s in range(16)} or sum(x['rows'] for x in projection)!=47587020:
        raise RuntimeError('Full opportunity-history coverage changed')
    manifest=project/authority['chronology_manifest_relative']
    snaps.append(io.checked(manifest,authority['chronology_manifest_sha256']))
    with manifest.open() as f:chron=list(csv.DictReader(f,delimiter='\t'))
    if len(chron)!=852 or sum(int(x['rows']) for x in chron)!=7763847245:
        raise RuntimeError('Canonical chronology manifest coverage changed')
    with io.heartbeat('Checking canonical chronology metadata'):
        for k,r in enumerate(chron):
            p=relocate(project,r['path']);pf=pq.ParquetFile(p)
            if int(r['file_index'])!=k or p.stat().st_size!=int(r['bytes']) or pf.metadata.num_rows!=int(r['rows']) or pf.metadata.num_row_groups!=int(r['row_groups']):
                raise RuntimeError('Canonical chronology metadata differs: '+str(p))
            if not {'utc_ms','white_id','black_id'}<=set(pf.schema_arrow.names):raise RuntimeError('Canonical chronology fields unavailable')
            r.update(path=str(p),signature=io.sig(p))
    pilot=project/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/prior['iv_run']
    success=io.load(pilot/'_SUCCESS.json')
    if success.get('config_sha256')!=prior['iv_config_sha256'] or success.get('report_zip_sha256')!=prior['iv_report_sha256']:
        raise RuntimeError('Verified historical reference source changed')
    deltas=[]
    for month in MONTHS:
        directory=pilot/'projection'/('month='+month)
        receipt=directory/'_COMPLETE.json';snaps.append(io.checked(receipt));r=io.load(receipt)
        if r.get('config_sha256')!=prior['iv_config_sha256']:raise RuntimeError('Wrong reference configuration')
        entries=[x for x in r['files'] if x['path']=='reference_deltas.npz']
        if len(entries)!=1:raise RuntimeError('Missing historical reference deltas')
        e=entries[0];p=directory/'reference_deltas.npz';snaps.append(io.checked(p,e['sha256'],e['bytes']));deltas.append(str(p))
    return dict(authority=authority,reviewed=reviewed,iv=paths['iv.parquet'],comparison=paths['comparison.parquet'],panels=panels,projection=projection,chron=chron,snapshots=snaps,deltas=deltas,expected_first_events=2369530,expected_fair=15207423,expected_fair_receipts=419463,expected_baseline=2112795)
