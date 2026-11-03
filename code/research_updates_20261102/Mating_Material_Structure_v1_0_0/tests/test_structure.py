from pathlib import Path
import sys,tempfile,unittest,copy,zipfile,json,hashlib,shutil
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from util import *
import numpy as np,pandas as pd
from sources import producers,designs,union_design
from estimation import moments,write_npz
from reporting import row,vector,stage_vector,baseline_check,write_reports,estimable

def fixture(n=6400,accounts=160,seed=731):
    rng=np.random.default_rng(seed);r11=producers()[0]
    chooser=np.repeat(np.arange(accounts),n//accounts)
    # The panel includes one singleton, which must count in G but not slope moments.
    chooser[-1]=accounts
    position=rng.integers(0,5,n);stage=rng.integers(0,8,n)
    ply=np.array([2,5,7,9,15,30,55,95])[stage];ply[::23]=3
    board=np.array([-400,-200,0,200,400])[position]
    return pd.DataFrame(dict(chooser=chooser,y=(rng.random(n)<(.06+.06*(position>=2))).astype(int),board=board,ply=ply,
        position=position,stage=np.select([ply<=4,ply<=6,ply<=8,ply<=10,ply<=20,ply<=40,ply<=80],range(7),7),
        gap=rng.normal(0,320,n),clock_c=rng.uniform(0,300,n),clock_d=rng.uniform(5,300,n),premium=np.exp(rng.uniform(0,4,n)),
        rd_c=np.exp(rng.uniform(2,5,n)),rd_d=np.exp(rng.uniform(2,5,n)),month_code=rng.integers(0,24,n),speed_code=rng.integers(1,5,n)))

def fits_for(d):
    _,names,indices=union_design(d);engine=producers()[2];one=moments(d,1);fits={}
    for model,ix in indices.items():
        f=engine.solve(one['xx'][np.ix_(ix,ix)],one['xy'][ix]);f['names']=[names[j] for j in ix];fits[model]=f
    two=moments(d,2,fits)
    for model,f in fits.items():
        f['covariance']=f['bread']@two[model]@f['bread']*int(one['g'])/(int(one['g'])-1)
        f.update({k:int(one[k]) for k in ('n','g','grants','within_n','within_g')})
    return fits,one,two

class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=fixture();cls.fits,cls.one,cls.two=fits_for(cls.d)

    def test_recovered_r10_hashes(self):
        authority=read(ROOT/'authority/R10_REUSE_AUTHORITY.json')
        for name in ('common.py','design.py','estimate.py','report.py'):
            self.assertEqual(sha(ROOT/'vendor/r10'/name),authority['code'][name])

    def test_union_exact_original_model_columns(self):
        U,names,indices=union_design(self.d);a,b,_,_,_=producers()
        for model,m,col in [('clock_pooled',a,'column1'),('stage_speed',b,'column4')]:
            x,n,ix=m.design(self.d)
            np.testing.assert_array_equal(U[:,indices[model]],x[:,ix[col]])
            self.assertEqual([names[j] for j in indices[model]],[n[j] for j in ix[col]])
        x,n=designs(self.d)['clock_region'];base,bn=designs(self.d)['clock_pooled']
        np.testing.assert_array_equal(x[:,:len(bn)],base)
        for j,side in enumerate(('c','d')):
            np.testing.assert_array_equal(x[:,len(bn)+j],np.log1p(self.d['clock_'+side])*(self.d.position>=2))

    def test_dense_dummy_ols_and_chooser_covariance_oracle(self):
        # Independent explicit chooser dummy projection + SVD OLS. This does
        # not use the production within-group routine or Gram solver.
        dummy=pd.get_dummies(self.d.chooser,dtype=float).to_numpy()
        projection=dummy/np.sqrt(dummy.sum(axis=0))
        for model,(X,names) in designs(self.d).items():
            y=100*self.d.y.to_numpy(float);W=X-projection@(projection.T@X);z=y-projection@(projection.T@y)
            scale=np.linalg.norm(W,axis=0);scale=np.where(scale>1e-12,scale,1)
            P=np.linalg.pinv(W/scale,rcond=1e-7)/scale[:,None]
            beta=P@z;residual=z-W@beta
            bread=P@P.T
            score=dummy.T@(W*residual[:,None]);V=bread@score.T@score@bread*len(dummy.T)/(len(dummy.T)-1)
            fit=self.fits[model]
            np.testing.assert_allclose(W@beta,W@fit['beta'],atol=3e-6,rtol=2e-6)
            for j in range(len(names)):
                L=np.eye(len(names))[j]
                if estimable(fit,L):
                    self.assertAlmostEqual(float(beta[j]),float(fit['beta'][j]),places=5)
                    self.assertAlmostEqual(float(np.sqrt(max(0,V[j,j]))),float(np.sqrt(max(0,fit['covariance'][j,j]))),places=5)

    def test_chooser_partition_moments_equal_whole_frame(self):
        for phase in (1,2):
            total={}
            for b in range(4):
                sub=self.d[self.d.chooser%4==b].reset_index(drop=True)
                values=moments(sub,phase,self.fits)
                for name,v in values.items():total[name]=total.get(name,0)+v
            for name,expected in (self.one if phase==1 else self.two).items():
                np.testing.assert_allclose(total[name],expected,rtol=2e-8,atol=2e-5)
        self.assertEqual(int(self.one['g']),161)
        self.assertEqual(int(self.one['within_n']),len(self.d)-1)

    def test_absent_speed_not_reported_as_identified_zero(self):
        f=self.fits['stage_speed']
        self.assertFalse(estimable(f,stage_vector(f,'ultrabullet',6)))
        for speed in ('bullet','blitz','rapid','classical'):self.assertTrue(estimable(f,stage_vector(f,speed,6)))

    def test_core_reference_gate_rejects_drift(self):
        f=self.fits['clock_pooled']
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);reference=out/'reference.npz'
            write_npz(reference,names=np.array(f['names']),beta=f['beta'],covariance=f['covariance'])
            self.assertTrue(baseline_check(f,out,reference)['all_passed'])
            changed=copy.deepcopy(f);changed['beta'][0]+=.01
            with self.assertRaisesRegex(RuntimeError,'reproduce'):baseline_check(changed,out,reference)

    def test_equal_weights_against_dense_weighted_fe(self):
        from equal_weights import analyze
        d=self.d
        frame=d.groupby('chooser').apply(lambda q:pd.Series(dict(n=len(q),k=int(q.y.sum()),f=int((q.position>=2).sum()),
            l=int((q.position==0).sum()),a=int(q.loc[q.position>=2,'y'].sum()),b=int(q.loc[q.position==0,'y'].sum()))),include_groups=False).reset_index()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);frame.to_parquet(out/'counts.parquet',index=False);analyze(out/'counts.parquet',out)
            result=pd.read_csv(out/'tab_app_equalweights.csv');V=pd.read_csv(out/'equalweight_covariance_pp2.csv').iloc[:,1:].to_numpy()
            sub=d[(d.position>=2)|(d.position==0)].copy();nc=sub.groupby('chooser').size();sub['C']=(sub.position>=2).astype(float)
            D=pd.get_dummies(sub.chooser,dtype=float).to_numpy();means=(D.T@sub.C.to_numpy())/D.sum(axis=0)
            countmap=frame.set_index('chooser');n=countmap.f+countmap.l;w=countmap.f*countmap.l/n
            for j,weights in enumerate([np.ones(len(sub)),sub.chooser.map(1/n).to_numpy(),sub.chooser.map(1/w).to_numpy()]):
                mask=np.isfinite(weights);x=sub.C.to_numpy()[mask];y=sub.y.to_numpy(float)[mask]*100;fe=D[mask]
                W=np.column_stack([fe,x])*np.sqrt(weights[mask,None]);target=y*np.sqrt(weights[mask]);beta=np.linalg.lstsq(W,target,rcond=1e-10)[0]
                self.assertAlmostEqual(result.iloc[j].estimate_pp,beta[-1],places=8)
            pairs=pd.read_csv(out/'equalweight_paired_differences.csv')
            for row_,(j,k) in zip(pairs.itertuples(),((1,0),(2,0),(2,1))):
                self.assertAlmostEqual(row_.se_pp,np.sqrt(max(0,V[j,j]+V[k,k]-2*V[j,k])),places=10)

    def test_month_projection_original_alias_and_raw_stage(self):
        from panel import project,descriptions
        d=self.d.copy();d['month_code']=0
        source=pd.DataFrame(dict(chooser_user_id=d.chooser,outcome_kind_draw=d.y,engine_eval_cp_disconnected=d.board,ply_count=d.ply,
            chooser_clock_last_obs_s=d.clock_c,disconnected_clock_last_obs_s=d.clock_d,chooser_win_premium_v2=d.premium,
            chooser_pre_rd_v2=d.rd_c,disconnected_pre_rd_v2=d.rd_d,chooser_elo=1500.,disconnected_elo=1500.+d.gap,
            month='2023-11',api_speed=d.speed_code.map({1:'bullet',2:'blitz',3:'rapid',4:'classical'}),
            sf100k_nodes_requested=100000,sf100k_fen_turn_matches_disconnected_color=True,disconnected_color='black',
            sf100k_disconnected_color_for_perspective='black',side_to_move_after_last='black',api_status='timeout',
            five_second_rule_passed=True,api_rated=True,api_variant='standard'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source.parquet';source.to_parquet(src,index=False)
            record_=dict(path=str(src),signature=signature(src),sha256=sha(src),month='2023-11',rows=len(d),grants=int(d.y.sum()))
            t=dict(record=record_,parent=str(root/'months'),key='synthetic_projection',memory=1)
            result=project(t);x=pd.read_parquet(result['path'])
            pd.testing.assert_frame_equal(x,d,check_dtype=False,check_exact=False,atol=1e-12)
            self.assertEqual(project(t)['n'],len(d))
            counts=dict(opportunities=len(d),grants=int(d.y.sum()),choosers=d.chooser.nunique(),competitive=int((d.position>=2).sum()))
            descriptions([result['path']],root/'raw',1,1,counts)
            rows=pd.read_csv(root/'raw/report/tab_app_state_ply.csv')
            self.assertEqual(int(rows.query("stage=='ply_2'").opportunities.iloc[0]),int(((d.position>=2)&(d.ply==2)).sum()))
            self.assertEqual(int(rows.query("panel=='B_roughly_equal'").opportunities.sum()),int((d.position==2).sum()))
            source.loc[0,'sf100k_nodes_requested']=10;source.to_parquet(src,index=False)
            t['key']='bad';record_.update(signature=signature(src),sha256=sha(src));t['parent']=str(root/'bad')
            with self.assertRaisesRegex(RuntimeError,'field meanings'):project(t)

    def test_full_pipeline_checkpoints_covariance_exports_and_privacy(self):
        from checkpoints import stage
        from panel import partition,descriptions
        from equal_weights import analyze
        from estimation import fit_models
        from run_structure import bundle,coverage
        d=self.d
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run';(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
            source=run/'PRIVATE/input.parquet';d.to_parquet(source,index=False)
            counts=dict(opportunities=len(d),grants=int(d.y.sum()),choosers=d.chooser.nunique(),competitive=int((d.position>=2).sum()))
            desc,summary=stage(run/'PRIVATE','descriptives','fixture',lambda out:descriptions([source],out,1,1,counts))
            analyze(desc/'chooser_counts_PRIVATE.parquet',desc/'report')
            for p in (desc/'report').iterdir():shutil.copy2(p,run/'report'/p.name)
            by=partition([source],run,'fixture',4,2,1,len(d))
            fits=fit_models(by,run,'fixture',2,2,4,counts)
            f=self.fits['clock_pooled'];reference=run/'PRIVATE/ref.npz'
            write_npz(reference,names=np.array(f['names']),beta=f['beta'],covariance=f['covariance'])
            summary=write_reports(fits,run/'report',reference)
            self.assertEqual(summary['models'],3);self.assertEqual(summary['speed_contrasts'],39)
            for model in fits:
                saved=read(run/'report/models'/f'{model}.json');V=np.array(saved['covariance'])
                np.testing.assert_allclose(V,self.fits[model]['covariance'],atol=1e-6,rtol=1e-6)
                np.testing.assert_allclose(V,V.T,atol=1e-12)
            coverage(run)
            zip_path=bundle(run,Path(tmp)/'return',True)
            with zipfile.ZipFile(zip_path) as z:
                self.assertFalse(any('/PRIVATE/' in n or n.endswith('_PRIVATE.parquet') for n in z.namelist()))
                for r in json.loads(z.read('REPORT_MANIFEST.json')):self.assertEqual(hashlib.sha256(z.read(r['path'])).hexdigest(),r['sha256'])
            before={str(p):signature(p) for p in (run/'PRIVATE').glob('phase*/*/moments.npz')}
            with patch('estimation.moments',side_effect=AssertionError('recomputed')):again=fit_models(by,run,'fixture',2,2,4,counts)
            self.assertEqual(before,{str(p):signature(p) for p in (run/'PRIVATE').glob('phase*/*/moments.npz')})
            target=next((run/'PRIVATE/phase1').glob('*/moments.npz'));target.write_bytes(b'broken')
            with self.assertRaisesRegex(RuntimeError,'checksum'):fit_models(by,run,'fixture',2,2,4,counts)

    def test_stage_atomicity_and_key_rejection(self):
        from checkpoints import stage
        with tempfile.TemporaryDirectory() as tmp:
            def failed(out):save(out/'partial.json',dict(x=1));raise ValueError('stopped')
            with self.assertRaises(ValueError):stage(tmp,'stage','one',failed)
            self.assertFalse((Path(tmp)/'stage').exists())
            def done(out):save(out/'done.json',dict(x=1));return dict(ok=True)
            path,s=stage(tmp,'stage','one',done)
            with self.assertRaisesRegex(RuntimeError,'inputs changed'):stage(tmp,'stage','two',done)

    def test_launcher_completion_resume_and_corrupt_cache_rejection(self):
        import run_structure as runner
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'project';destination=Path(tmp)/'desktop';project.mkdir()
            source=project/'source';source.write_text('fixture')
            auth=dict(parent_run_id=read(ROOT/'authority/REVIEW.json')['run_id'],manifest_sha256=sha(source),
                      records=[dict(month='2023-11',sha256=sha(source),rows=6400,grants=100)])
            calls=[]
            def execute(auth_,run,*args):
                calls.append(1);table(run/'report/fixture.csv',[dict(estimate=.1,se=.02)])
                save(run/'PRIVATE/fixture.json',dict(verified=True));return dict(test_fixture=True),dict(test=0.)
            args=['--project-root',str(project),'--results-dir',str(destination),'--workers','1','--shards','4','--memory-gb','4']
            with patch.object(runner,'verify_package'),patch.object(runner,'authenticate',return_value=auth),patch.object(runner,'census',return_value=dict(opportunities=6400)),patch.object(runner,'guard'),patch.object(runner,'execute',side_effect=execute):
                self.assertEqual(runner.main(args),0);self.assertEqual(len(calls),1)
                latest=read(destination/'MATERIAL_STRUCTURE_LATEST_PRIVATE.json');root=Path(latest['root']);completed=sha(root/'_SUCCESS.json')
                self.assertEqual(runner.main(args),0);self.assertEqual(len(calls),1)
                (root/'PRIVATE/fixture.json').write_text('corrupt')
                self.assertEqual(runner.main(args),1);self.assertEqual(len(calls),1)
                self.assertEqual(completed,sha(root/'_SUCCESS.json'))
                failed=next(destination.glob('*_FAILED.zip'))
                with zipfile.ZipFile(failed) as z:self.assertFalse(json.loads(z.read('RETURN_STATUS.json'))['successful_return'])

if __name__=='__main__':unittest.main()
