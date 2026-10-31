"""Exercise the actual pinned Arrow API and complete opportunity model path."""
from pathlib import Path
from unittest.mock import patch
import sys,tempfile,contextlib,io
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
import engine
sys.path.insert(0,str(ROOT/'vendor/patron_remaining'))
sys.path.insert(0,str(ROOT/'vendor/patron_remaining/source'))
from patron_compat import record_batches,install
from source import opportunity_models_cov_v100 as models,synthetic_fixture_v101 as fixture
from runner import opportunity,families
from source import wave3b1_helpers as h
import resume_previous
import duckdb,numpy as np,pandas as pd


def main():
    install(models)
    rng=np.random.default_rng(612);rows=[];expanded=[]
    for g in range(30):
        for x in [0,1]:
            n=int(rng.integers(2,8));k=int(rng.integers(0,n+1))
            rows.append(dict(cluster_code=g,opportunities=n,kind_draws=k,x=x))
            expanded.extend((g,x,y) for y in [100.]*k+[0.]*(n-k))
    c=duckdb.connect();c.register('cells',pd.DataFrame(rows))
    # Deliberately cut across clusters, including a final one-row batch.
    models.record_batches=lambda con,query:record_batches(con,query,7)
    fit,_=models.fit_collapsed_model(c,table='cells',condition='TRUE',model_name='stream',
        terms=[('1.0','intercept'),('x','x')],primary_terms=['x'])
    d=np.array(expanded);X=np.column_stack([np.ones(len(d)),d[:,1]]);y=d[:,2]
    inv=np.linalg.inv(X.T@X);beta=inv@X.T@y;e=y-X@beta
    hc=len(y)/(len(y)-2)*inv@(X.T@(X*e[:,None]**2))@inv
    scores=np.array([X[d[:,0]==g].T@e[d[:,0]==g] for g in range(30)])
    cr=30/29*(len(y)-1)/(len(y)-2)*inv@(scores.T@scores)@inv
    np.testing.assert_allclose(fit['estimate_vector'],beta,rtol=1e-11)
    np.testing.assert_allclose(fit['covariance_matrices']['HC1'],hc,rtol=1e-11)
    np.testing.assert_allclose(fit['covariance_matrices']['CR1_chooser'],cr,rtol=1e-11)
    c.close();install(models)
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);state=root/'state';state.mkdir()
        panel,users=fixture.build_panel(groups=24)
        panel['ply_count']=np.resize([0,4,5,10,11,20,21,40,41,80,81,120],len(panel))
        snapshot=fixture.build_snapshot(panel,users)
        p=root/'panel.parquet';s=root/'snapshot.parquet';panel.to_parquet(p,index=False);snapshot.to_parquet(s,index=False)
        c=duckdb.connect();cells=root/'cells.parquet'
        qa=opportunity.build_cache(c,[p],s,cells)
        for ply,n in [(False,3),(True,12)]:
            public=root/str(ply);public.mkdir()
            result=opportunity.fit_families(c,cells,s,state,'fixture',public,ply=ply)
            assert result['models']==n
        mtimes={str(p):p.stat().st_mtime_ns for p in state.rglob('fit.json')}
        opportunity.fit_families(c,cells,s,state,'fixture',root/'False',ply=False)
        assert mtimes=={str(p):p.stat().st_mtime_ns for p in state.rglob('fit.json')}
        # Compare the collapsed implementation with the same estimator before
        # adding the ply collapse dimension; every coefficient/covariance agrees.
        c.execute('CREATE TABLE no_ply AS SELECT * EXCLUDE(ply_band,opportunities,kind_draws),sum(opportunities) opportunities,sum(kind_draws) kind_draws FROM opportunity_analysis GROUP BY ALL')
        controls=models.control_terms(c,'opportunity_analysis');name,condition,primary=opportunity.model_specs()[0]
        model,_=models.fit_collapsed_model(c,table='no_ply',condition=condition,model_name='check',terms=controls+primary,primary_terms=[k for _,k in primary])
        saved=engine.read(root/'False/opportunity_models_and_covariance.json')[0]
        np.testing.assert_allclose(model['estimate_vector'],saved['estimate_vector'],atol=1e-7,rtol=1e-8)
        np.testing.assert_allclose(model['covariance_matrices']['CR1_chooser'],saved['covariance_matrices']['CR1_chooser'],atol=1e-7,rtol=1e-7)
        c.close()
        # Reuse real committed rematches under the unchanged input key.
        prior=root/'prior';old=prior/'PRIVATE/stages/patron/PRIVATE';old.mkdir(parents=True)
        old_public=root/'old_public';old_public.mkdir()
        frame=pd.DataFrame([dict(matched_kind_chooser_id=str(g),control_slot=s,is_kind_role=int(s==0),
            match_cell='a' if g%2 else 'b',patron=int((g+s)%7==0),patron_pp=100*int((g+s)%7==0))
            for g in range(16) for s in range(4)])
        groups={'all':[],'standardize':[]}
        families.rematches(frame,groups,old,'unchanged',old_public,replicates=3)
        originals={str(p):p.stat().st_mtime_ns for p in old.rglob('fit.json')}
        with patch.object(resume_previous,'prior_root',return_value=prior):
            assert resume_previous.copy_patron_checkpoints(root,state,h.prior)==6
        public=root/'copied_rematches';public.mkdir()
        families.rematches(frame,groups,state,'unchanged',public,replicates=3)
        assert (public/'rematch_summary.csv').read_bytes()==(old_public/'rematch_summary.csv').read_bytes()
        assert originals=={str(p):p.stat().st_mtime_ns for p in old.rglob('fit.json')}
        target=next(old.rglob('fit.json'));target.write_text('{}')
        with patch.object(resume_previous,'prior_root',return_value=prior):
            try:resume_previous.copy_patron_checkpoints(root,state,h.prior)
            except RuntimeError:pass
            else:raise AssertionError('Corrupt prior Patron fit was copied')
    print('Patron actual-API, expanded-data covariance, all 15 models, and resume: PASS')

if __name__=='__main__':main()
