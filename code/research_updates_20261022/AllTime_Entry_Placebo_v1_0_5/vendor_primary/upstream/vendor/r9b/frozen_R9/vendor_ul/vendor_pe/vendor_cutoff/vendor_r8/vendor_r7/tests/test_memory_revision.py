"""Regression tests for the v1.0.1 memory and resume changes."""
from test_r7 import *
del NumericalTests, MoveTests, OperationalTests
import r7_memory,r7_resume,r7_schedule
from unittest import mock

def scheduler_probe(job):
    folder=Path(job['output']);folder.mkdir()
    io.js(folder/'pid.json',{'pid':os.getpid()})
    return {'rows':1}

class MemoryRevisionTests(unittest.TestCase):
    def test_owned_FE_solver_matches_frozen_checked_algorithm(self):
        rng=np.random.default_rng(882);n=1500
        a=rng.normal(size=(n,22));a[:,0]*=1000
        groups=[rng.integers(0,35,n),rng.integers(0,12,n),rng.integers(0,6,n)]
        want,old_diag=env_numerics.absorb(a,groups)
        owned=np.array(a,order='F',copy=True)
        got,diag=r7_memory.absorb_owned(owned,groups)
        self.assertIs(got,owned)
        np.testing.assert_array_equal(got,want)
        self.assertEqual(diag['iterations'],old_diag['iterations'])
        with self.assertRaises(ValueError):r7_memory.absorb_owned(a[:,::2],groups)

    def test_lower_memory_covariance_against_frozen_and_explicit(self):
        rng=np.random.default_rng(997);n=105
        i=rng.integers(1,30,n);j=rng.integers(1,30,n);j[i==j]+=40
        date=rng.integers(1,10,n);s=rng.normal(size=(n,15))
        codes=stats.cmp.covariance_codes(i,j,date)
        H=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(date[:,None]==date)
        np.testing.assert_allclose(r7_memory.shared_meat(s,codes),s.T@H@s,atol=2e-12)
        with mock.patch.object(r7_memory,'COV_BLOCK_BYTES',5000):
            np.testing.assert_allclose(r7_memory.shared_meat(s,codes),s.T@H@s,atol=2e-12)
        np.testing.assert_allclose(r7_memory.shared_meat(s,codes),stats.stats.shared_meat(s,codes),atol=2e-12)
        np.testing.assert_allclose(r7_memory.shared_meat(s,codes,False),stats.stats.shared_meat(s,codes,False),atol=2e-12)

    def test_all_numerical_outputs_against_frozen_v100_reference(self):
        references=io.load(ROOT/'evidence/v100_synthetic_reference.json')
        identity=['sample','control_level','instrument','recipient_FE','outcome','estimator','analysis','dependent',
                  'trait','test_set','predicted_outcome','calibration_controls','method']
        def key(row):return json.dumps([row.get(k) for k in identity],sort_keys=True)
        def compare(got,want,label):
            if isinstance(want,dict):
                self.assertEqual(set(got),set(want),label)
                for k in want:compare(got[k],want[k],label+'.'+k)
            elif isinstance(want,list):
                self.assertEqual(len(got),len(want),label)
                for a,b in zip(got,want):compare(a,b,label)
            elif isinstance(want,float):
                self.assertTrue(np.isclose(got,want,rtol=2e-7,atol=2e-9,equal_nan=True),f'{label}: {got} != {want}')
            else:self.assertEqual(got,want,label)
        for case,want in references.items():
            kind,level,selection,instrument,fe=case.split('|');fe=fe=='True'
            d=fixture(4800);d['environment_supported'][::13]=False
            for name in ENV:d[name][::13]=np.nan
            d=r7_models.select_sample(d,selection)
            got,_=r7_models.estimate(d,kind,'oracle',level,instrument,fe,part_a=not fe,release_inputs=True)
            got=io.clean(got)
            for table in want:
                a=sorted(got[table],key=key);b=sorted(want[table],key=key)
                compare(a,b,case+'/'+table)

    def test_joint_class_strings_match_direct_labels(self):
        d=fixture(4000);n=len(d['row_id']);rng=np.random.default_rng(828)
        d.update(moves_available=rng.random(n)>.2,net_material_change_4ply=rng.integers(-5,5,n),
                 ply_count=rng.integers(0,100,n),engine_eval_cp_disconnected=rng.normal(0,300,n))
        d['disconnected_clock_last_obs_s']=d['tc_base_s']*rng.random(n)
        cls=r7_composition.classify(d)
        wanted=['|'.join(v) for v in zip(cls['ply_band'],cls['material_band'],cls['merit_code'],cls['clock_band'])]
        self.assertEqual(cls['joint_class'].tolist(),wanted)

    def test_large_job_reservations_fit_eleven_GiB_budget(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            class Metadata:num_rows=7371688
            class Parquet:metadata=Metadata()
            with mock.patch.object(pq,'ParquetFile',return_value=Parquet()):
                jobs=run_r7.plan({k:p/'source' for k in ['S0','F50','O50']},p,'fixture')
            self.assertLess(max(j['memory_estimate_gb'] for j in jobs)+1.5,11)
            self.assertGreater(max(j['memory_estimate_gb'] for j in jobs)+1.5,9)

    def test_completed_reuse_is_read_only_and_rejects_changed_inputs_or_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);source=p/'source';source.write_text('authenticated')
            def build(tmp):
                (tmp/'model.txt').write_text('prepared table')
                return {'rows':10}
            stable_stage(p/'stage','fixture',build,[source])
            before={q.name:io.sha(q) for q in (p/'stage').iterdir()}
            r7_resume.verify_completed(p/'stage','fixture')
            self.assertEqual(before,{q.name:io.sha(q) for q in (p/'stage').iterdir()})
            with self.assertRaises(RuntimeError):r7_resume.verify_completed(p/'stage','wrong_conf')
            with (p/'stage/model.txt').open('a') as f:f.write('changed')
            with self.assertRaises(RuntimeError):r7_resume.verify_completed(p/'stage','fixture')
            (p/'stage/model.txt').write_text('prepared table');source.write_text('different')
            with self.assertRaises(RuntimeError):r7_resume.verify_completed(p/'stage','fixture')

    def test_resume_binding_accepts_verified_tables_and_pins_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            physical=Path(td)/'physical';physical.mkdir()
            p=Path(td)/'alias';p.symlink_to(physical,target_is_directory=True)
            # Exercise macOS-style logical/physical path differences on every OS.
            self.assertNotEqual(p,p.resolve())
            original=p/'original.parquet'
            io.table(original,pa.table({'row_id':list(range(12))}))
            binding={'paths':{'original':str(original),'receipt':str(original)}}
            config={'version':'1.0.0','package_sha256':r7_resume.PREVIOUS_PACKAGE,'spec_sha256':io.sha(ROOT/'R7_SPEC.md')}
            conf=io.cfgsha(config);io.js(p/'config.json',config);io.js(p/'INPUTS_PRIVATE.json',binding)
            def gate(tmp):
                io.js(tmp/'checks.json',[{'passed':True}]);return {'status':'REPRODUCTION_GATE_PASSED'}
            stable_stage(p/'reproduction',conf,gate,[original])
            def prepared(tmp):
                io.table(tmp/'model.parquet',io.read(original));return {'rows':12}
            for sample in ['F50','O50']:stable_stage(p/'prepared'/sample,conf,prepared,[original])
            before={str(q):io.sha(q) for q in p.rglob('*') if q.is_file()}
            with mock.patch.object(r7_resume,'PREVIOUS_CONF',conf),mock.patch.dict(r7_resume.EXPECTED_ROWS,{'F50':12,'O50':12}):
                paths,receipt=r7_resume.bind(p,binding)
                self.assertEqual(paths['F50'],(p/'prepared/F50/model.parquet').resolve(strict=True))
                self.assertEqual(receipt['config_sha256'],conf)
                self.assertEqual(before,{str(q):io.sha(q) for q in p.rglob('*') if q.is_file()})
                with self.assertRaisesRegex(RuntimeError,'source binding differs'):r7_resume.bind(p,{'paths':{}})
            with self.assertRaisesRegex(RuntimeError,'reviewed R7'):r7_resume.bind(p,binding)

    def test_scheduler_recycles_workers_without_losing_queued_jobs(self):
        from performance_runtime import Runtime
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            jobs=[{'output':str(p/str(k)),'memory_estimate_gb':.5} for k in range(5)]
            r7_schedule.fit_map(scheduler_probe,jobs,Runtime(p),2,4,'scheduler reuse test',lambda:None)
            pids=[io.load(p/str(k)/'pid.json')['pid'] for k in range(5)]
            if sys.version_info>=(3,11):self.assertEqual(len(set(pids)),5)

    def test_all_true_selection_does_not_duplicate_inputs(self):
        d=fixture();self.assertIs(r7_models.select_sample(d,''),d)

if __name__=='__main__':unittest.main()
