"""Synthetic numeric/oracle tests; no private production data or network."""
import os,sys,tempfile,unittest,subprocess,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ['UNIFORM90_WORKERS']='1';os.environ['UNIFORM90_MEMORY_GIB']='4'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common5 import *
import fit_badge as fit
import link_badge as link
from badge_fixture import fixture
from scipy.linalg import lstsq

def write(path,data):pq.write_table(pa.table(data) if isinstance(data,dict) else pa.Table.from_pylist(data),path)
def dense_meat(S,i,j,date):
    edge=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(date[:,None]==date)
    return S.T@edge.astype(float)@S

def numeric_fixture(root,n=2400):
    root.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(871)
    recipient=rng.integers(1,76,n);opponent=(recipient+rng.integers(1,75,n)-1)%75+1
    z=rng.normal(0,.06,n);d=(rng.random(n)<np.clip(.3+3*z,.05,.95)).astype(float)
    src=dict(row_id=np.arange(n,dtype=np.int64),recipient_id=recipient,opponent_id=opponent,
        received=d,y=(rng.random(n)<.12+.08*d).astype(float),reached=(rng.random(n)<.8).astype(float),
        patron=recipient<=20,sampling_fraction=np.where(recipient%3==0,1.,.4),
        model5_exposures_per_recipient=np.bincount(recipient)[recipient],
        archive_start_ms=(19500+rng.integers(0,12,n))*c.DAY+rng.integers(0,24,n)*3600000,
        month_code=np.zeros(n,np.int64),tc_base_s=np.full(n,300),tc_inc_s=np.zeros(n,np.int64),
        recipient_rating=rng.normal(1500,100,n),opponent_rating=rng.normal(1500,100,n),
        fair_90=rng.integers(1,20,n),kind_90=rng.integers(0,2,n),disconnect_90=rng.integers(0,20,n),
        receipt_90=rng.integers(0,2,n),claim_90=rng.integers(0,20,n),pre_games_90d=rng.integers(10,300,n),environment_supported=np.ones(n,bool))
    for name in c.frozen.r.ENV:src[name]=rng.random(n)
    scores=dict(row_id=src['row_id'],adjusted_A=z,n_A=rng.integers(5,100,n),counterparts_A=rng.integers(2,5,n),expected_A=rng.uniform(.1,.3,n))
    source=root/'source.parquet';score=root/'scores.parquet';write(source,src);write(score,scores)
    return source,score,src

class PatronTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
    def tearDown(self):self.t.cleanup()
    def args(self):
        run=self.root/'run';(run/'report').mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True)
        return SimpleNamespace(run=run,conf='synthetic',workers=1,memory_gb=4.,project=self.root)
    def test_weighted_fwl_matches_explicit_dummy_wls_in_ram_and_memmap(self):
        rng=np.random.default_rng(3);n=500;v=rng.normal(size=(n,7));v[:,-1]=v[:,-2]*2
        groups=[rng.integers(0,12,n),rng.integers(0,8,n)];w=rng.uniform(.1,8,n)
        X=np.column_stack([v[:,3:]]+[np.eye(int(g.max())+1)[g] for g in groups]);sw=np.sqrt(w)
        expected=v[:,:3]-X@lstsq(X*sw[:,None],v[:,:3]*sw[:,None],cond=1e-12,lapack_driver='gelsy')[0]
        for disk in (False,True):
            root=self.root/str(disk);root.mkdir()
            x=model.disk.disk_matrix(root/'test.dat',n,7) if disk else np.empty_like(v,order='F');x[:]=v
            actual,rank,diag=fit.weighted_project(x,groups,w,3,root)
            np.testing.assert_allclose(actual,expected,atol=2e-8,rtol=0);self.assertEqual(rank,3)
            self.assertEqual(diag['status'],'CONVERGED');del actual,x
    def test_full_weighted_fit_points_and_covariance_match_independent_dense_oracle(self):
        src,sc,data=numeric_fixture(self.root/'data');a=self.args()
        job=fit.make_job(a,'weighted',src,sc,['received','patron'],weight='ipw',iv='patron')
        out=fit.fit(job);raw,groups,actors,targets,_,_=model.build_buffer(job,self.root)
        # Recode dates before forming the independent dummy matrix (their values need not start at zero).
        X=np.column_stack([raw[:,3:]]+[np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups])
        w=1/data['sampling_fraction'];w/=w.mean();sw=np.sqrt(w)
        residual=raw[:,:3]-X@lstsq(X*sw[:,None],raw[:,:3]*sw[:,None],cond=1e-12,lapack_driver='gelsy')[0]
        z,d,y=residual.T;zz=np.sum(w*z*z);zd=np.sum(w*z*d)
        betas=np.array([np.sum(w*z*d)/zz,np.sum(w*z*y)/zz,np.sum(w*z*y)/zd])
        S=np.column_stack([w*z*(d-betas[0]*z)/zz,w*z*(y-betas[1]*z)/zz,w*z*(y-betas[2]*d)/zd])
        V=dense_meat(S,actors['recipient_id'],actors['opponent_id'],actors['date'])
        saved=load(Path(job['output'])/'result.json')
        np.testing.assert_allclose([r['coefficient'] for r in out],betas*np.array([100*SD,100*SD,100]),rtol=2e-7,atol=2e-7)
        np.testing.assert_allclose(saved['native_covariance'],V,rtol=3e-7,atol=3e-10)
        self.assertEqual(out[0]['unique_patrons'],20)
        self.assertEqual(fit.fit(job),out)
    def test_baseline_reproduction_and_subprocess_worker_match_frozen_model(self):
        src,sc,_=numeric_fixture(self.root/'data');a=self.args()
        job=fit.make_job(a,'reference',src,sc,['received','y','reached'],iv='y');job['iv']=True
        model.fit(job)
        save(a.run/'PRIVATE/BINDING.json',dict(source=str(src),scores=str(sc),baseline=str(Path(job['output'])/'result.json')))
        result=subprocess.run([sys.executable,str(ROOT/'code/fit_badge.py'),'--mode','baseline','--run',str(a.run),'--conf',a.conf,'--workers','1','--memory-gb','4'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        checks=load(a.run/'report/model5_reproduction.json');self.assertTrue(all(r['passed'] for r in checks));self.assertEqual(len(checks),12)
    def test_bounded_covariance_shared_account_or_date_pairwise_oracle(self):
        rng=np.random.default_rng(43);n=90;i=rng.integers(1,13,n);j=(i+rng.integers(1,12,n)-1)%12+1;date=rng.integers(0,15,n);S=rng.normal(size=(n,3))
        path=self.root/'scores.parquet';write(path,dict(recipient_id=i,opponent_id=j,date=date,**{'s'+str(k):S[:,k] for k in range(3)}))
        actual=model.covariance(path,['s0','s1','s2'],self.root/'cov',memory=1.,buckets=8)
        np.testing.assert_allclose(actual,dense_meat(S,i,j,date),atol=1e-10)
    def test_primary_selection_and_sensitivity_pipeline(self):
        src,sc,data=numeric_fixture(self.root/'data');n=len(data['row_id']);a=self.args()
        data.update(profile_returned=np.ones(n,bool),positive_support=np.ones(n,bool),in_original_chooser_universe=np.ones(n,bool));write(src,data)
        save(a.run/'PRIVATE/BADGE_PATHS.json',dict(linked=str(src),scores=str(sc)))
        save(a.run/'report/prior_chooser_support.json',dict(zero_support_exposures=0,observed_exposures=n))
        fit.primary(a);fit.sensitivities(a)
        main=load(a.run/'report/Patron_primary_estimates.json');sens=load(a.run/'report/Patron_sensitivity_estimates.json')
        self.assertEqual([r['term'] for r in main],['first_stage','rf_patron','iv_patron'])
        self.assertEqual(len(load(a.run/'report/selection_diagnostics.json')),3);self.assertEqual(len(sens),9)
        prior=[r for r in sens if r['sample']=='patron_prior_chooser_ipw']
        np.testing.assert_allclose([r['coefficient'] for r in main],[r['coefficient'] for r in prior],atol=1e-10)
    def badge_setup(self):
        inp,counts=fixture(self.root/'badges')
        source=self.root/'new.parquet';rows=[dict(row_id=k,recipient_id=i,opponent_id=300+k,archive_start_ms=1700000000000,fair_90=int(i<4),month_code=3) for k,i in enumerate([1,1,2,3,4,5,6,7])];write(source,rows)
        con=link.badge.connect(self.root/'db',1,4)
        link.badge.build_accounts(con,inp,None,self.root/'accounts',counts,frame_paths=[source])
        return con,source,self.root/'accounts/recipient_profiles_PRIVATE.parquet',inp,counts
    def test_rebuilt_badge_roster_original_sampling_missingness_and_row_counts(self):
        con,source,accounts,_,_=self.badge_setup()
        try:
            link.attach(con,source,accounts,self.root/'linked.parquet')
            data=con.execute('SELECT recipient_id,sampling_fraction,patron,coverage_status,model5_exposures_per_recipient FROM linked ORDER BY row_id').fetchall()
            self.assertEqual([r[1] for r in data],[1,1,.75,.75,.75,.75,0,0]);self.assertEqual([r[4] for r in data],[2,2,1,1,1,1,1,1])
            self.assertEqual(data[-1][3],'outside_original_chooser_universe');self.assertTrue(all(r[2] is None for r in data[4:]))
        finally:con.close()
    def test_full_link_stage_exports_aggregate_coverage_and_resumes(self):
        con,source,accounts,inp,counts=self.badge_setup();con.close();a=self.args()
        save(a.run/'PRIVATE/BINDING.json',dict(source=str(source),scores='not_used_at_link'))
        deps={k:str(v) for k,v in inp.items() if k not in ('dictionary','dictionary_column')};deps['dict']=str(inp['dictionary'][0])
        orig=link.load
        def loader(p):return dict(counts=counts) if Path(p).name=='badge_authority.json' else orig(p)
        with patch.object(link,'authenticate',return_value=(inp,deps)),patch.object(link,'load',side_effect=loader),patch.object(link.cert,'N',8),patch.object(link.cert,'PEOPLE',7):
            folder=link.prepare(a);self.assertEqual(link.prepare(a),folder)
        summary=load(a.run/'report/coverage_summary.json');self.assertEqual(summary['observed_exposures'],4);self.assertEqual(summary['observed_recipients'],3);self.assertEqual(summary['observed_unique_patrons'],1)
        self.assertEqual(load(a.run/'report/profile_pull_assessment.json')['new_requests'],0)
        export(a.run,self.root,50,'IN_PROGRESS')
        with zipfile.ZipFile(next(self.root.glob('*.zip'))) as z:self.assertTrue(all('PRIVATE' not in n for n in z.namelist()))
    def test_badge_link_rejects_duplicate_mapping(self):
        con,source,accounts,_,_=self.badge_setup()
        try:
            rows=pq.read_table(accounts).to_pylist();rows.append(rows[0]);write(accounts,rows)
            with self.assertRaisesRegex(RuntimeError,'Duplicate acc'):link.attach(con,source,accounts,self.root/'linked.parquet')
        finally:con.close()
    def test_badge_link_rejects_missing_returned_badge_and_preexposure_query(self):
        con,source,accounts,_,_=self.badge_setup();con.close();base=pq.read_table(accounts).to_pylist()
        for k,patch_values in enumerate([dict(patron=None),dict(query_ms=1600000000000)]):
            rows=[dict(r) for r in base];next(r for r in rows if r['recipient_id']==1).update(patch_values);target=self.root/('accounts'+str(k)+'.parquet');write(target,rows)
            con=link.badge.connect(self.root/('db'+str(k)),1,4)
            try:
                with self.assertRaisesRegex(RuntimeError,'Invalid badge'):link.attach(con,source,target,self.root/('linked'+str(k)+'.parquet'))
            finally:con.close()
    def test_author_exclusion_remains_a_hard_gate(self):
        inp,counts=fixture(self.root/'badges');source=self.root/'bad.parquet';write(source,[dict(recipient_id=1,opponent_id=101)])
        con=link.badge.connect(self.root/'db',1,4)
        try:
            with self.assertRaisesRegex(RuntimeError,'Author account'):link.badge.build_accounts(con,inp,None,self.root/'accounts',counts,frame_paths=[source])
        finally:con.close()
    def test_recipient_weights_use_full_frame_counts_and_reject_zero_support(self):
        path=self.root/'weights.parquet';write(path,dict(sampling_fraction=[.5,.5,1.],model5_exposures_per_recipient=[2,2,1]))
        np.testing.assert_equal(fit.weights_for(path,'recipient_ipw'),[1,1,1]);np.testing.assert_equal(fit.weights_for(path,'ipw'),[2,2,1])
        write(path,dict(sampling_fraction=[0.],model5_exposures_per_recipient=[1]))
        with self.assertRaisesRegex(RuntimeError,'Invalid original'):fit.weights_for(path,'ipw')
    def test_resume_rejects_changed_dependency_or_corrupt_output(self):
        dep=self.root/'dep';dep.write_text('source');calls=[]
        def builder(tmp):calls.append(1);save(tmp/'result.json',dict(ok=True));return dict(n=2)
        folder,_=stage(self.root/'stage','config',builder,[dep]);stage(folder,'config',builder,[dep]);self.assertEqual(len(calls),1)
        dep.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'inputs changed'):stage(folder,'config',builder,[dep])
        dep.write_text('source');(folder/'result.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'Checksum/size'):stage(folder,'config',builder,[dep])
    def test_public_report_refuses_private_file(self):
        a=self.args();(a.run/'report/identities_PRIVATE.parquet').write_bytes(b'private')
        with self.assertRaisesRegex(RuntimeError,'Private data'):export(a.run,self.root,25,'IN_PROGRESS')
    def test_nonpositive_covariance_remains_unsupported(self):
        self.assertFalse(model.inference90(.1,-.01)['supported']);self.assertFalse(model.inference90(.1,0)['supported'])

if __name__=='__main__':unittest.main()
