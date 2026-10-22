"""Optional full synthetic pipeline, including resume and supplied-history branches.

Runtime: roughly 15–40 seconds. No game network requests or engine process.
Temporary files are outside production paths and removed automatically.
"""
from common import *
from self_test import synthetic
from run import run_models,coverage
from report import render
from history import attach
from lineage import RUN_KEY,SAMPLE
import tempfile

def main():
    started=time.monotonic();d=synthetic(64,30)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);r=root/'run';(r/'PRIVATE').mkdir(parents=True);(r/'report').mkdir()
        coverage(d,r/'report')
        s,f,m=run_models(d,r,'integration-no-history',4,False);assert len(s)==53
        render(r/'report',s,f,m,dict(status='BLOCKED_INPUT'))
        files=sorted((r/'PRIVATE').glob('pass*/*.npz'));stamps={str(p):p.stat().st_mtime_ns for p in files}
        _,f2,m2=run_models(d,r,'integration-no-history',4,False)
        assert all(p.stat().st_mtime_ns==stamps[str(p)] for p in files),'Completed regression checkpoints were recomputed'
        for a,b,x,y in zip(f,f2,m,m2):
            np.testing.assert_array_equal(a['beta'],b['beta']);np.testing.assert_array_equal(x,y)
        # A real-form contract on synthetic rows exercises cutoff/count/support checks.
        h=d[['game_id','game_ms']].rename(columns={'game_ms':'asof_start_ms'}).copy()
        rng=np.random.default_rng(1904)
        for prefix in ['prior90','prepanel']:
            h[prefix+'_starts']=rng.integers(0,1000,len(h))
            h[prefix+'_disconnections']=rng.binomial(h[prefix+'_starts'],.015)
            h[prefix+'_complete']=rng.random(len(h))>.08
        p=root/'history.parquet';h.to_parquet(p,index=False)
        manifest=root/'history.json';dump(manifest,dict(contract='KAC_A2_HISTORY_V1',target_run_key=RUN_KEY,sample_fingerprint=SAMPLE,
             disconnection_definition='active_resolution_timeout_all_sources',denominator_definition='all_rated_standard_live_starts',
             focal_game_excluded=True,completion_known_before_focal_start=True,window90_days=90,prepanel_end_utc='2023-11-01T00:00:00Z',
             producer_code_sha256=sha(Path(__file__)),source_authentication=dict(manifest_sha256='0'*64,audit_report='SYNTHETIC_TEST_ONLY'),
             parquet=p.name,parquet_sha256=sha(p)))
        stripped=d.drop(columns=[n for n in d if n.startswith('prior90_') or n.startswith('prepanel_')])
        dh,status=attach(stripped,manifest)
        r2=root/'history_run';(r2/'PRIVATE').mkdir(parents=True);(r2/'report').mkdir()
        sh,fh,mh=run_models(dh,r2,'integration-history',4,True);assert len(sh)==62
        render(r2/'report',sh,fh,mh,status)
        # Reject cutoff leakage rather than falling back to zero histories.
        h.loc[0,'asof_start_ms']+=1;h.to_parquet(p,index=False)
        meta=load(manifest);meta['parquet_sha256']=sha(p);dump(manifest,meta)
        try:attach(stripped,manifest)
        except RuntimeError as e:assert 'cutoff' in str(e)
        else:raise AssertionError('Accepted wrong history cutoff')
    print(f'INTEGRATION_TEST_OK: 53 default models; 62 history models; exact resume parity; cutoff gate. {time.monotonic()-started:.1f} seconds.',flush=True)
if __name__=='__main__':main()
