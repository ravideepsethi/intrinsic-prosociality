import sys,unittest,tempfile,copy,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from ul_common import *
import ul_scores,ul_models,ul_report,run_ul
sys.path.insert(0,str(prior.previous.ROOT/'vendor_r8/vendor_r7/tests'))
from test_r7 import fixture

def sample(n=2400):
    d=fixture(n);order=np.argsort(d['row_id']);d={k:v[order] for k,v in d.items()}
    n=len(d['row_id']);d['game_id']=np.array(['synthetic'+str(k) for k in range(n)])
    d['anchor_ms']=d['archive_start_ms']+1000;d['complete90']=np.ones(n,bool)
    return d

def scorefile(path,d):
    n=len(d['row_id']);v=d['adjusted_7d']
    a=dict(row_id=d['row_id'],n_all_time=np.full(n,30),adjusted_all_time=v*1.07+.001,
        n_before=np.full(n,12),n_after=np.full(n,18),adjusted_before=v*.91-.002,adjusted_after=v*1.2+.003)
    r.io.table(path,pa.table(a));return a

def history_fixture():
    rng=np.random.default_rng(414);n=28000;nq=280
    h=dict(j=rng.integers(1,16,n),i=rng.integers(16,55,n),t=rng.integers(-100,301,n),
        y=rng.integers(0,2,n),cell=rng.integers(0,500,n))
    q=dict(row_id=np.arange(nq,dtype=np.uint64),frame=rng.integers(0,2,nq,dtype=np.int8),
        opponent_id=rng.integers(1,16,nq),recipient_id=rng.integers(16,70,nq),
        archive_start_ms=rng.integers(0,100,nq),anchor_ms=rng.integers(110,200,nq),month_code=rng.integers(0,24,nq))
    ref=rng.uniform(.02,.4,(2,24,4,4,500))
    return h,q,ref

class ScoreTests(unittest.TestCase):
    def test_full_and_timing_against_bruteforce_every_query(self):
        h,q,ref=history_fixture();full,before,after,sel,gap=ul_scores.score(h,q,ref)
        checks=ul_scores.oracle_checks(h,q,ref,full,before,after,sel,limit=len(q['row_id']))
        self.assertEqual(checks['queries_checked'],len(q['row_id']))
        self.assertTrue(np.all(full['n'][sel]==before['n']+after['n']+gap))

    def test_both_directions_pair_mutation_has_zero_effect_and_future_other_matters(self):
        h=dict(j=np.array([1]*9),i=np.array([2,2,2,3,3,4,4,4,4]),t=np.array([-10,10,100,-1,0,10,11,80,100]),
            y=np.array([0,1,1,0,1,0,1,0,1]),cell=np.zeros(9,int))
        q=dict(row_id=np.array([1]),frame=np.array([0]),opponent_id=np.array([1]),recipient_id=np.array([2]),
            archive_start_ms=np.array([0]),anchor_ms=np.array([10]),month_code=np.array([0]))
        ref=np.full((2,24,4,4,500),.2);full,before,after,sel,gap=ul_scores.score(h,q,ref)
        self.assertEqual(full['n'][0],6);self.assertEqual(before['n'][0],1);self.assertEqual(after['n'][0],3);self.assertEqual(gap[0],2)
        modified=copy.deepcopy(h);modified['y'][:3]=1-modified['y'][:3]
        changed=ul_scores.score(modified,q,ref)[0]
        np.testing.assert_array_equal(full['adjusted'],changed['adjusted'])
        modified['y'][-1]=0;changed=ul_scores.score(modified,q,ref)[0]
        self.assertAlmostEqual(full['adjusted'][0]-changed['adjusted'][0],1/6)

    def test_empty_history_is_unsupported_not_zero_leniency(self):
        h,q,ref=history_fixture();h={k:v[:0] for k,v in h.items()}
        full,*_=ul_scores.score(h,q,ref)
        self.assertTrue(np.all(full['n']==0));self.assertTrue(np.isnan(full['adjusted']).all())

    def test_frozen_reference_excludes_both_focal_folds_in_both_roles(self):
        rng=np.random.default_rng(613);n=rng.integers(1,10,(2,24,4,4,500));s=n//2
        a=r.num.expanding_reference(n,s);nn=n.copy();ss=s.copy()
        nn[:,:,1,:,:]+=50;ss[:,:,1,:,:]+=10;nn[:,:,:,3,:]+=30;ss[:,:,:,3,:]+=20
        b=r.num.expanding_reference(nn,ss)
        np.testing.assert_array_equal(a[:,:,1,3,:],b[:,:,1,3,:])

    def test_streaming_queries_separate_frames_and_score_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'s.parquet',pa.table(d));r.io.table(p/'f.parquet',pa.table(d))
            paths={'S0':p/'s.parquet','F50':p/'f.parquet'};q=ul_scores.prepare_queries(paths,p/'queries','test')
            combined=pa.concat_tables([r.io.read(q/f'{s:02}.parquet') for s in range(16)])
            self.assertEqual(len(combined),2*len(d['row_id']))
            self.assertEqual(set(combined['frame'].to_pylist()),{0,1})
            for s in range(16):
                t=r.arrays(r.io.read(q/f'{s:02}.parquet'))
                self.assertTrue(np.all(r.num.user_hash(t['opponent_id'])%np.uint64(16)==s))

class ModelTests(unittest.TestCase):
    def test_controls_and_outcomes_frozen_timing_rows_identical_material_strict(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));a=scorefile(p/'z.parquet',d)
            a['n_before'][:3]=2;a['n_after'][3:8]=1;r.io.table(p/'z.parquet',pa.table(a))
            full=ul_models.load_scored(p/'d.parquet',p/'z.parquet')
            for key in full:
                if key!='adjusted_7d':np.testing.assert_array_equal(full[key],d[key])
            ids=[]
            for variant in ('all_time','before','after'):
                selected=ul_models.load_scored(p/'d.parquet',p/'z.parquet',variant,'timing_common');ids.append(selected['row_id'])
                self.assertEqual(len(selected['row_id']),len(d['row_id'])-8)
            for value in ids[1:]:np.testing.assert_array_equal(value,ids[0])
            mat=dict(row_id=d['row_id'],material_valid=np.ones(len(d['row_id']),bool),material_neutral=np.arange(len(d['row_id']))%3!=0)
            r.io.table(p/'m.parquet',pa.table(mat))
            neutral=ul_models.load_scored(p/'d.parquet',p/'z.parquet',material=p/'m.parquet',screen='neutral')
            self.assertEqual(len(neutral['row_id']),int(mat['material_neutral'].sum()))

    def test_new_fit_matches_direct_frozen_estimator_and_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));scorefile(p/'z.parquet',d)
            job=ul_models.make_job(p/'d.parquet',p/'z.parquet',p/'fit','test','S0','iv','X0')
            ul_models.fit_job(job);got=u.load(p/'fit/result.json')
            direct,_=models.estimate(ul_models.load_scored(p/'d.parquet',p/'z.parquet'),'iv','S0','X0',part_a=False,calibration=False)
            for a,b in zip(got['B_estimates'],direct['B_estimates']):
                for key in ('coefficient_pp','standard_error_pp','iv_coefficient_pp','iv_standard_error_pp'):
                    if key in b:self.assertAlmostEqual(a[key],b[key],10)
            stamp=(p/'fit/result.json').stat().st_mtime_ns;ul_models.fit_job(job)
            self.assertEqual(stamp,(p/'fit/result.json').stat().st_mtime_ns)
            d['received'][0]=1-d['received'][0];r.io.table(p/'d.parquet',pa.table(d))
            with self.assertRaisesRegex(RuntimeError,'input changed'):ul_models.fit_job(job)

    def test_ordinary_subset_and_role_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();o={k:v[::2] for k,v in d.items()}
            for name,data in [('f',d),('o',o)]:r.io.table(p/(name+'.parquet'),pa.table(data))
            scorefile(p/'z.parquet',d);paths={'F50':p/'f.parquet','O50':p/'o.parquet'}
            output,info=ul_scores.ordinary_scores(paths,p/'z.parquet',p/'ok','test',1)
            self.assertTrue(info['verified_subset']);self.assertEqual(pq.ParquetFile(output).metadata.num_rows,len(o['row_id']))
            o['recipient_id'][0]+=1;r.io.table(p/'bad.parquet',pa.table(o));paths['O50']=p/'bad.parquet'
            with self.assertRaisesRegex(RuntimeError,'mismatch'):ul_scores.ordinary_scores(paths,p/'z.parquet',p/'bad','test',1)

    def test_shared_covariance_contrast_same_inputs_cancels(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));scorefile(p/'z.parquet',d)
            for name,kind in [('S0','iv'),('O50','ordinary')]:
                ul_models.fit_job(ul_models.make_job(p/'d.parquet',p/'z.parquet',p/name,'test',name,kind,'X0'))
            ul_models.contrast_job(dict(left=str(p/'S0'),right=str(p/'O50'),level='X0',conf='test',output=str(p/'contrast')))
            for row in u.load(p/'contrast/result.json'):self.assertAlmostEqual(row['coefficient_pp'],0,9)

class IntegrationTests(unittest.TestCase):
    def test_all_fourteen_models_contrasts_and_final_report(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample(4400);r.io.table(p/'d.parquet',pa.table(d));scorefile(p/'z.parquet',d)
            n=len(d['row_id']);neutral=np.arange(n)%10!=0
            r.io.table(p/'m.parquet',pa.table(dict(row_id=d['row_id'],material_valid=np.ones(n,bool),material_neutral=neutral)))
            for level in LEVELS:
                for sample_name,kind in [('S0','iv'),('F50','entry'),('O50','ordinary')]:
                    for screen in (('all','neutral') if sample_name=='S0' else ('all',)):
                        out=p/'run/fits'/f'{sample_name}_{screen}_{level}'
                        job=ul_models.make_job(p/'d.parquet',p/'z.parquet',out,'test',sample_name,kind,level,screen,p/'m.parquet' if screen=='neutral' else None)
                        ul_models.fit_job(job)
                for variant in ('all_time','before','after'):
                    job=ul_models.make_job(p/'d.parquet',p/'z.parquet',p/'run/fits'/f'timing_{variant}_{level}','test',
                        'S0','iv',level,variant=variant,cohort='timing_common')
                    ul_models.fit_job(job)
                ul_models.contrast_job(dict(left=str(p/'run/fits'/f'S0_all_{level}'),right=str(p/'run/fits'/f'O50_all_{level}'),
                    level=level,conf='test',output=str(p/'run/contrasts'/level)))
            tables,done=ul_report.collect(p/'run');self.assertEqual(len(done),14)
            self.assertEqual(len(tables['B_placebo_contrasts']),4)
            (p/'evidence/cutoff').mkdir(parents=True);(p/'evidence/placebo').mkdir()
            r.io.js(p/'evidence/cutoff/B_estimates.json',[dict(v,history_cutoff='lag24h') for v in tables['B_estimates']])
            for name in ('B_placebo','B_entry','B_placebo_contrasts','B_joint_balance'):
                r.io.js(p/'evidence/placebo'/(name+'.json'),[dict(v,history_cutoff='lag24h') for v in tables[name]])
            with patch('ul_report.ROOT',p),patch.object(prior,'ROOT',p):
                summary=ul_report.export(p/'run',p/'desktop','synthetic',100,'CORE_COMPLETE_ORDINARY_MATERIAL_PENDING',dict(synthetic=True))
            self.assertEqual(summary['completed_new_models'],14)
            self.assertEqual(len(u.load(p/'run/report/same_row_checks.json')),16)
            timing=u.load(p/'run/report/B_timing.json')
            self.assertEqual({v['history_cutoff'] for v in timing},{'all_time','before','after'})
            self.assertEqual(len({v['row_set_sha256'] for v in timing}),1)

    def test_production_score_worker_excludes_authors_and_inactive_and_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);j=123;i=456;author=789;shard=int(r.num.user_hash(np.array([j]))[0]%np.uint64(16))
            h=dict(j=np.array([j]*15+[author]),i=np.array([i,i,author,900,901,902,903,904,905,906,907,908,909,910,911,911]),
                t=np.arange(16)*100,y=np.arange(16)%2,arm=np.array([True]*14+[False,True]),cell=np.arange(16)%4)
            r.io.table(p/'donor.parquet',pa.table(h))
            q=dict(row_id=np.array([5]),frame=np.array([0],np.int8),opponent_id=np.array([j]),recipient_id=np.array([i]),
                archive_start_ms=np.array([500]),anchor_ms=np.array([700]),month_code=np.array([5]),n_7d=np.array([5]))
            r.io.table(p/'q.parquet',pa.table(q));np.save(p/'ref.npy',np.full((2,24,4,4,500),.1),allow_pickle=False)
            job=dict(parts=[dict(path=str(p/'donor.parquet'),sha256=u.sha(p/'donor.parquet'),rows=16)],
                authors=[author],shard=shard,queries=str(p/'q.parquet'),reference=str(p/'ref.npy'),output=str(p/'score'),conf='test')
            got=ul_scores.score_job(job);self.assertEqual(got['eligible_author_clean_donor_rows'],13)
            score=r.io.read(p/'score/scores.parquet').to_pylist()[0]
            self.assertEqual(score['n_all_time'],11);self.assertEqual(score['n_before'],2);self.assertEqual(score['n_after'],6)
            stamp=(p/'score/scores.parquet').stat().st_mtime_ns;ul_scores.score_job(job)
            self.assertEqual(stamp,(p/'score/scores.parquet').stat().st_mtime_ns)

    def test_combiner_scopes_duplicate_row_numbers_to_frame_and_checks_benchmarks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();sources={};old={};parts=[]
            for frame,sample_name in enumerate(('S0','F50')):
                sources[sample_name]=p/(sample_name+'.parquet');r.io.table(sources[sample_name],pa.table(d))
                a=scorefile(p/(sample_name+'_tmp.parquet'),d)
                a['frame']=np.full(len(d['row_id']),frame,np.int8);a['n_focal_interval']=np.zeros(len(d['row_id']),int)
                path=p/(sample_name+'_scores.parquet');r.io.table(path,pa.table(a));parts.append(path)
                old[sample_name]=p/(sample_name+'_old.parquet')
                r.io.table(old[sample_name],pa.table(dict(row_id=d['row_id'],n_24h=np.full(len(d['row_id']),20),adjusted_24h=d['adjusted_7d'])))
            scores,info=ul_scores.combine(parts,sources,old,p/'combine','test',1)
            self.assertEqual(info['S0']['rows'],len(d['row_id']));self.assertEqual(info['timing']['common_supported_rows'],len(d['row_id']))
            self.assertEqual(pq.ParquetFile(scores['F50']).metadata.num_rows,len(d['row_id']))
            bad=r.io.read(old['S0']);r.io.table(p/'bad.parquet',pa.concat_tables([bad,bad.slice(0,1)]));old['S0']=p/'bad.parquet'
            with self.assertRaisesRegex(RuntimeError,'Duplicate'):ul_scores.combine(parts,sources,old,p/'bad','test',1)

    def test_report_gates_row_mismatch_and_exports_without_private_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'evidence/cutoff').mkdir(parents=True);(p/'evidence/placebo').mkdir()
            reference=dict(n=2500,row_set_sha256='abc',history_cutoff='lag24h',exposure_screen='all',
                control_level='X0',outcome='y',estimator='reduced_form')
            r.io.js(p/'evidence/cutoff/B_estimates.json',[reference])
            for name in ('B_placebo','B_entry','B_placebo_contrasts','B_joint_balance'):r.io.js(p/'evidence/placebo'/(name+'.json'),[])
            tables={k:[] for k in ('B_estimates','B_placebo','B_entry','B_timing')};tables['B_estimates']=[dict(reference,history_cutoff='all_time')]
            with patch('ul_report.ROOT',p),patch.object(prior,'ROOT',p):
                self.assertTrue(ul_report.verify_comparisons(tables)[0]['same_rows_as_reviewed'])
                tables['B_estimates'][0]['n']=2499
                with self.assertRaisesRegex(RuntimeError,'changed'):ul_report.verify_comparisons(tables)
                summary=ul_report.export(p/'run',p/'desktop','synthetic',25,'SYNTHETIC_TEST_ONLY',dict(synthetic=True))
            self.assertEqual(summary['completed_new_models'],0)
            for rec in u.load(p/'run/report/REPORT_MANIFEST.json'):self.assertEqual(u.sha(p/'run/report'/rec['path']),rec['sha256'])
            import zipfile
            with zipfile.ZipFile(next((p/'desktop').glob('*.zip'))) as z:
                self.assertIsNone(z.testzip());self.assertFalse(any('PRIVATE' in name for name in z.namelist()))

    def test_spawned_fit_respects_memory_and_collects_result(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));scorefile(p/'z.parquet',d)
            job=ul_models.make_job(p/'d.parquet',p/'z.parquet',p/'fits/job','test','F50','entry','X0')
            got=runtime.mapped(ul_models.fit_job,[job],2,4,'synthetic',1)
            self.assertEqual(got[0]['rows'],len(d['row_id']))
            tables,done=ul_report.collect(p);self.assertEqual(len(done),1)
            self.assertEqual({r['outcome'] for r in tables['B_entry']},{'analysis_entry_90','recipient_disconnect_main','active_timeout'})
            with self.assertRaisesRegex(RuntimeError,'exceeds'):runtime.capacity([dict(memory_gb=10)],10,11)

if __name__=='__main__':unittest.main()
