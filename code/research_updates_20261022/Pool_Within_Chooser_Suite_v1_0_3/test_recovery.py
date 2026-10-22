"""Production-width synthetic S4 verification and authenticated result recovery."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits
import fe_suite as fe
import parallel_fe as parallel
import checked_math as checked
import recovery_math as independent
import recover_v102 as recovery
from test_suite import fixture,independent_reference


def run_tests():
    checks=[];d,meta=fixture();n=len(d['y']);rng=np.random.default_rng(90923)
    speeds=['blitz','bullet','classical','rapid']
    meta['calendar']=[[f'{2023+(10+m)//12:04d}-{(10+m)%12+1:02d}',s] for m in range(24) for s in speeds]
    meta['speeds']=speeds;d['speed']=rng.integers(0,4,n,dtype=np.int8)
    d['calendar']=(4*rng.integers(0,24,n)+d['speed']).astype(np.int16)
    bounds=[(2,5),(5,7),(7,9),(9,11),(11,21),(21,41),(41,81),(81,121)]
    d['exact_ply']=np.array([rng.integers(*bounds[int(p)]) for p in d['ply']],dtype=np.int32)
    meta['early_levels']=[3,4,6,8,10]+list(range(12,21))
    # Realistic exact collinearity in centered premium splines.
    d['premium']=4+np.exp(rng.uniform(-2,5,n))
    assert (d['exact_ply']==13).any() and len(meta['calendar'])==96
    with tempfile.TemporaryDirectory(prefix='within_chooser_recovery_test_') as td:
        root=Path(td);cache=root/'synthetic_PRIVATE.parquet';pq.write_table(pa.table(d),cache,row_group_size=79)
        paths,_=parallel.shards(cache,root/'shards',2)
        with parallel.pool(2) as executor:
            fitted=parallel.fit_group(paths,meta,root/'exact','exact_ply_recovery',executor,127)
        checks.append(independent_reference(d,meta,fitted,'exact_ply_recovery'))
        fe.export(fitted,meta,root/'exact')
        reference=fe.fit_group(cache,meta,root/'serial','states',191)[-1]
        np.testing.assert_allclose(fitted[0]['beta'],reference['beta'],atol=5e-9,rtol=2e-8)
        np.testing.assert_allclose(fitted[0]['cov'],reference['cov'],atol=5e-10,rtol=2e-8)
        audit=json.loads((root/'exact/ARITHMETIC_AUDIT.json').read_text())
        independent.check_design_hashes(audit['moment_workers'],audit['score_workers'])
        checks.append({'test':'96_calendar_cells_14_exact_ply_terms_int32_collinear_splines_two_spawn_workers','passed':True})
        # Inject cross-pass design corruption: certification must stop.
        bad=[dict(a) for a in audit['score_workers']];bad[0]['centered_design_sha256']='wrong'
        try:independent.check_design_hashes(audit['moment_workers'],bad)
        except ValueError:pass
        else:raise AssertionError('Mismatched design hash accepted')
        # Prediction disagreement must be recorded, and independent values used.
        x=rng.normal(size=(57,13));b=rng.normal(size=13);stats={};old=checked.matvec
        try:
            checked.matvec=lambda x,b:old(x,b)+.1
            answer=independent.predict(x,b,stats)
        finally:checked.matvec=old
        np.testing.assert_allclose(answer,x@b,atol=1e-12)
        assert stats['prediction_method_disagreements']==1
        G=checked.gram(x);G[1,0]+=.1
        try:independent.check_response_products(x,G,{})
        except ValueError:pass
        else:raise AssertionError('Bad response cross-product accepted')
        checks.append({'test':'injected_design_prediction_and_response_product_faults_detected','passed':True})
        source,real_meta,entries=recovery.authenticate_returned(root/'source')
        saved=recovery.recover_completed_states(source,real_meta,root/'recovered')
        assert len(saved)==4 and entries==252
        assert all(f['counts']['rows']==41534331 for f in saved)
        primary=next(f for f in saved if f['name']=='S3_full')
        definition=next(c for c in fe.contrast_definitions(primary,real_meta) if c['label']=='competitive_vs_losing_standardized')
        result=fe.summarize_contrast(primary,definition['C'])
        np.testing.assert_allclose(result['estimate_pp'],1.7739192269,atol=1e-8)
        checks.append({'test':'returned_v102_archive_252_hashes_and_four_saved_state_models','passed':True})
    result={'status':'PASS','private_panel_run_here':False,'checks':checks}
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__=='__main__':
    with threadpool_limits(limits=1):run_tests()
