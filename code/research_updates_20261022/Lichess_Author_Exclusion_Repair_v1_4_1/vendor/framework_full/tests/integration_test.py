#!/usr/bin/env python3
"""Synthetic end-to-end estimation, plotting, privacy export and verified resume."""
from run_tests import *
from types import SimpleNamespace
import fw_b_profiles,fw_d

def main(destination):
    root=Path(destination);root.mkdir(parents=True,exist_ok=True);d=synthetic_panel(160)
    inputs=[]
    for year in (1,2):
        p=root/f'year{year}.parquet';parquet(p,d.loc[d.year==year]);inputs.append(p)
    a=SimpleNamespace(workers=2,memory_gb=4,bootstrap=29)
    accounts=fw_inputs.aggregate_accounts(inputs,root/'accounts','accounts',4)
    parts=fw_inputs.partitions(inputs,root/'parts','parts',4,shards=4)
    first=fw_f.run(a,root,accounts,None,'synthetic')
    second=fw_f.run(a,root,accounts,None,'synthetic');assert first==second
    adjusted=fw_adjust.adjust(parts,root/'F/adjustment','adjust',a)
    # Simulate interruption after scores were committed but before the parent receipt.
    previous=stamp(root/'F/adjustment/fits.npz');(root/'F/adjustment/_DONE.json').unlink()
    fw_adjust.adjust(parts,root/'F/adjustment','adjust',a)
    assert stamp(root/'F/adjustment/fits.npz')==previous
    fw_f.run(a,root,accounts,adjusted,'synthetic')
    raw=frame(accounts).sort_values(['chooser','year','late','state']).reset_index(drop=True)
    adj=frame(adjusted).sort_values(['chooser','year','late','state']).reset_index(drop=True)
    pd.testing.assert_frame_equal(raw[['chooser','year','late','state','n']],adj[['chooser','year','late','state','n']],check_dtype=False)
    fw_b.run(a,root,parts,accounts,'synthetic')
    fw_b_profiles.run(a,root,parts,'synthetic')
    fw_d.run(a,root,parts,'synthetic')
    fw_c.run(a,root,inputs,'synthetic')
    future_source=root/'exposures.parquet'
    e=pd.DataFrame(dict(cohort_row_id=[1,2],recipient_user_id=[1,2],exposure_anchor_utc_ms=[d.event_ms.min()-1]*2));parquet(future_source,e)
    future=fw_e.future_clean(a,root,inputs,future_source,'synthetic');f=frame(future).sort_values('cohort_row_id')
    assert f.delta_ms.tolist()==[1,1]
    from run_framework import state_readout
    (root/'report').mkdir(exist_ok=True);state_readout(root)
    # The public aggregate folders must not contain chooser/game/name fields.
    for p in root.glob('*/report/*.parquet'):
        assert not {'chooser','game_id','chooser_name','recipient_id','opponent_id'}&set(pq.ParquetFile(p).schema_arrow.names),str(p)
    save(root/'INTEGRATION_PASSED.json',dict(passed=True,synthetic_accounts=160,synthetic_rows=len(d),bootstrap=29,
        production_bootstrap=999,checks=['B models and plots','C likelihoods and plot','D branching','F raw/adjusted matrices','whole-account partition integrity','no-opportunity rules','strict future times','resume','aggregate output schema']))
    print('INTEGRATION_PASSED',root,flush=True)

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else tempfile.mkdtemp(prefix='framework-smoke-'))
