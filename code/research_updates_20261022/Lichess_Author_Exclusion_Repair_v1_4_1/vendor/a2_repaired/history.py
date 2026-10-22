"""Explicit adapter for independently constructed all-rated-game history features.

No automatic substitution of disconnections/opportunities from the certified pool panel.
The required producer/audit contract is documented in HISTORY_INPUT.md.
"""
from common import *
from lineage import RUN_KEY,SAMPLE
import re

def attach(d,manifest):
    if manifest is None:return d,dict(status='BLOCKED_INPUT',reason='No authenticated all-rated chronology feature manifest supplied.')
    manifest=Path(manifest).expanduser().resolve();m=load(manifest)
    require(m.get('contract')=='KAC_A2_HISTORY_V1','Unsupported history contract')
    require(m.get('target_run_key')==RUN_KEY and m.get('sample_fingerprint')==SAMPLE,'History target identity differs')
    require(m.get('disconnection_definition')=='active_resolution_timeout_all_sources','History numerator is not all-source active disconnections')
    require(m.get('denominator_definition')=='all_rated_standard_live_starts','History denominator must be all rated standard live starts')
    require(m.get('focal_game_excluded') is True and m.get('completion_known_before_focal_start') is True,'History must precede focal start')
    require(m.get('window90_days')==90 and m.get('prepanel_end_utc')=='2023-11-01T00:00:00Z','History windows differ')
    require(re.fullmatch('[0-9a-f]{64}',str(m.get('producer_code_sha256',''))) is not None,'History producer hash absent/invalid')
    audit=m.get('source_authentication',{})
    require(isinstance(audit,dict) and re.fullmatch('[0-9a-f]{64}',str(audit.get('manifest_sha256',''))) is not None and audit.get('audit_report'),'History source audit absent/invalid')
    p=(manifest.parent/m['parquet']).resolve();require(sha(p)==m['parquet_sha256'],'History Parquet checksum differs')
    columns=['game_id','asof_start_ms','prior90_disconnections','prior90_starts','prior90_complete',
             'prepanel_disconnections','prepanel_starts','prepanel_complete']
    h=pq.ParquetFile(p).read(columns=columns).to_pandas()
    require(len(h)==len(d) and h.game_id.nunique()==len(d) and set(h.game_id)==set(d.game_id),'History target support differs')
    for prefix in ['prior90','prepanel']:
        for suffix in ['disconnections','starts']:
            x=h[prefix+'_'+suffix]
            require(x.notna().all() and (x>=0).all() and (x==np.floor(x)).all(),'Invalid history counts')
        require((h[prefix+'_disconnections']<=h[prefix+'_starts']).all(),'Disconnections exceed starts')
        require(h[prefix+'_complete'].notna().all() and set(h[prefix+'_complete'].unique())<={True,False},'Invalid history coverage flag')
        h[prefix+'_rate']=h[prefix+'_disconnections'].div(h[prefix+'_starts'].replace(0,np.nan)).fillna(0)
        h.loc[~h[prefix+'_complete'].astype(bool),prefix+'_rate']=np.nan
    d=d.merge(h,on='game_id',validate='one_to_one',sort=False)
    require((d.game_ms==d.asof_start_ms).all(),'History cutoff differs from focal start')
    return d,dict(status='SUPPLIED_HISTORY_CONTRACT_VALIDATED',manifest_sha256=sha(manifest),
                  producer_code_sha256=m['producer_code_sha256'],source_authentication=m['source_authentication'],
                  note='Contract/checksums validated; upstream chronology construction remains part of the required source audit.',
                  prior90_covered=int(d.prior90_complete.sum()),prepanel_covered=int(d.prepanel_complete.sum()))
