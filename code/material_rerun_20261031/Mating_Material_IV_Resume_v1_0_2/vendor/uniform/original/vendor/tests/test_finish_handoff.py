"""Exercise the actual authentication, six-contrast finish, export and resume.

Small certified model fixtures stand in for the unavailable private drive.
Only the missing receipt X0 estimator is stubbed; covariance and report code
execute normally. Numerical agreement is independently tested in the companion
covariance tests and the inherited frozen-estimator replay tests.
"""
import unittest,tempfile,sys,contextlib,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import run_finish as runner
import rebuild_models as previous


def fit_fixture(job):
    n=pq.ParquetFile(job['input']).metadata.num_rows
    kind=job['kind'];outs=['analysis_entry_90','recipient_disconnect_main','active_timeout'] if kind=='entry' else ['y','reached']
    def build(tmp):
        estimates=[dict(sample=job['sample'],control_level=job['level'],n=n,row_set_sha256='test-rows-'+str(n),
            outcome=name,estimator='reduced_form',coefficient=.01,standard_error=.002,
            ci_low=.00608,ci_high=.01392,p_value_asymptotic=.01,supported=True) for name in outs]
        if kind=='iv':estimates.append(dict(estimator='2SLS',outcome='y',n=n,
            iv_coefficient_pp=.36280640903671635,iv_standard_error_pp=.096407515226692))
        balance=[dict(sample=job['sample'],control_level=job['level'],n=n,trait='fixture_trait',
                      coefficient=.01,standard_error=.002,supported=True)]
        joint=[dict(sample=job['sample'],control_level=job['level'],n=n,rank=1,
                    wald_chi2=25.,p_value_asymptotic=.001,supported=True)]
        save(tmp/'result.json',dict(estimates=estimates,balance=balance,joint_balance=joint,figure5=[]))
        cols=dict(row_id=np.arange(n),recipient_id=np.arange(n),opponent_id=np.arange(n)+100,date=np.arange(n)%3)
        for k,name in enumerate(outs):cols[name]=(np.arange(n)+1.)*(k+1)*.00001/n
        pq.write_table(pa.table(cols),tmp/'influence_PRIVATE.parquet')
        return dict(n=n)
    return stage(job['output'],job['conf'],build,[job['input'],job['scores']])[1]


class FinishHandoff(unittest.TestCase):
    def test_handoff_with_aliased_temporary_directory(self):
        # macOS returns /var/... from tempfile but Path.resolve() returns
        # /private/var/... . Reproduce that alias on every platform.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();physical=root/'private/var';physical.mkdir(parents=True)
            alias=root/'var';alias.symlink_to(physical,target_is_directory=True)
            with patch.object(tempfile,'tempdir',str(alias)):
                self.test_reviewed_handoff_finishes_and_resumes_without_any_comparison_refit()

    def test_reviewed_handoff_finishes_and_resumes_without_any_comparison_refit(self):
        with tempfile.TemporaryDirectory() as td:
            # Match production configuration creation, which canonicalizes all
            # project roots before binding them into the configuration hash.
            base=Path(td).resolve();project=base/'project';project.mkdir();results=base/'results';results.mkdir()
            config=dict(version='1.0.3',project=str(project),package_manifest_sha256=runner.PARENT_PACKAGE,rule=RULE)
            parentconf=key(config);parent=project/'derived/replication/alltime_entry_placebo_v103_PRIVATE'/parentconf[:12]
            (parent/'PRIVATE').mkdir(parents=True);(parent/'report').mkdir();(parent/'RUN.lock').touch();save(parent/'config.json',config)
            inputs=base/'inputs';inputs.mkdir()
            sizes={'legacy_F':5,'legacy_O':3,'totalfive_F':6,'totalfive_O':4}
            def table(path,n):pq.write_table(pa.table(dict(row_id=np.arange(n))),path)
            oldpaths={};oldscores={}
            for s in ('F','O'):
                oldpaths[s]=str(inputs/('old'+s+'.parquet'));oldscores[s]=str(inputs/('old'+s+'_scores.parquet'))
                table(oldpaths[s],sizes['legacy_'+s]);table(oldscores[s],sizes['legacy_'+s])
            source=inputs/'source';source.write_text('completed source')
            def frames(tmp):
                for s in ('F','O'):
                    table(tmp/(s+'.parquet'),sizes['totalfive_'+s]);table(tmp/(s+'_scores.parquet'),sizes['totalfive_'+s])
                save(tmp/'overlap.json',[]);return {}
            stage(parent/'PRIVATE/frames',parentconf,frames,[source])
            prim=inputs/'primary.parquet';ps=inputs/'primary_scores.parquet';table(prim,7);table(ps,7)
            oldroot=base/'old';b=dict(old_paths=oldpaths,old_scores=oldscores,comparison_root=str(oldroot),comparison_conf='old',
                                    primary=dict(primary=str(prim),primary_scores=str(ps)))
            save(parent/'PRIVATE/BINDING.json',b);plan=[]
            for level in r9.LEVELS:
                for sample,kind in [('F','entry'),('O','ordinary')]:
                    for legacy in (True,False):
                        label=('legacy_' if legacy else 'totalfive_')+sample
                        inp=oldpaths[sample] if legacy else parent/'PRIVATE/frames'/(sample+'.parquet')
                        scores=oldscores[sample] if legacy else parent/'PRIVATE/frames'/(sample+'_scores.parquet')
                        job=fits.make_job(inp,scores,parent/'PRIVATE/models'/(label+'__'+level),parentconf,label,kind,level)
                        job.update(memory=4.,memory_gb=9.);plan.append(job);fit_fixture(job)
                        if legacy:
                            oldjob=dict(job,output=str(oldroot/'fits'/(sample+'100__A__'+level)),conf='old');fit_fixture(oldjob)
            save(parent/'PRIVATE/MODEL_PLAN.json',plan)
            receipt=parent/'PRIVATE/models/receipt__X0_ENV_indicator'
            fit_fixture(fits.make_job(prim,ps,receipt,parentconf,'receipt_total5','iv','X0_ENV_indicator'))
            previous.contrast_job(dict(left=str(receipt),right=str(parent/'PRIVATE/models/totalfive_O__X0_ENV_indicator'),
                output=str(parent/'PRIVATE/contrasts/new_receipt_minus_new_ordinary__X0_ENV_indicator'),conf=parentconf,
                level='X0_ENV_indicator',label='new_receipt_minus_new_ordinary',outcomes=['y','reached']))
            save(parent/'report/model_validation.json',dict(comparison_models_complete=8,comparison_models_planned=8,
                corrected_primary_reproduced=True,contrasts_complete=1,legacy_models_reproduced=[]))
            state={k:dict(status='COMPLETE') for k in ('authenticate','candidates','chronology','metadata_audit','metadata','frames')}
            state['models']=dict(status='FAILED')
            runner.exporter.export(SimpleNamespace(audit_only=False,result_dir=results),parent,parentconf,state,75,'fixture OOM')
            pkg=base/'package';(pkg/'evidence').mkdir(parents=True)
            shutil.copyfile(parent/'report/REPORT_MANIFEST.json',pkg/'evidence/v103_075_REPORT_MANIFEST.json')
            reportsha=sha(parent/'report/REPORT_MANIFEST.json')
            before={p:(sha(p),p.stat().st_mtime_ns) for p in parent.rglob('*') if p.is_file()}
            argv=['run_finish.py','--project',str(project),'--reuse-completed',str(parent),'--result-dir',str(results)]
            missing=[]
            def only_missing_receipt(job):
                self.assertEqual((job['kind'],job['level']),('iv','X0'))
                if not (Path(job['output'])/'_DONE.json').exists():missing.append(job['level'])
                return fit_fixture(job)
            with contextlib.ExitStack() as stack:
                for name,value in [('PARENT_CONF',parentconf),('PARENT_REPORT',reportsha),('EXPECTED_ROWS',sizes),('ROOT',pkg)]:
                    stack.enter_context(patch.object(runner,name,value))
                stack.enter_context(patch.object(sys,'argv',argv))
                stack.enter_context(patch.object(runner.exporter,'verify',return_value='test-finish-package'))
                stack.enter_context(patch.object(runner.shutil,'disk_usage',return_value=SimpleNamespace(free=80*2**30)))
                stack.enter_context(patch.object(runner.fits,'fit_job',side_effect=only_missing_receipt))
                stack.enter_context(patch.object(previous,'fit_job',side_effect=AssertionError('comparison refit')))
                self.assertEqual(runner.main(),0)
                newroot=Path(load(results/'ALLTIME_ENTRY_PLACEBO_LATEST_PRIVATE.json')['root'])
                self.assertEqual(load(newroot/'report/STATUS.json')['status'],'COMPLETE')
                self.assertTrue(load(newroot/'report/STATUS.json')['entry_and_ordinary_populations_rebuilt'])
                self.assertEqual(load(newroot/'report/model_validation.json')['contrasts_complete'],6)
                done={p:p.stat().st_mtime_ns for p in newroot.rglob('_DONE.json')}
                with patch.object(runner.bounded,'covariance',side_effect=AssertionError('completed covariance recomputed')):
                    self.assertEqual(runner.main(),0)
                self.assertTrue(all(p.stat().st_mtime_ns==v for p,v in done.items()))
                self.assertEqual(missing,['X0'])
                self.assertTrue(all((sha(p),p.stat().st_mtime_ns)==v for p,v in before.items()))
                archive=next(results.glob('ALLTIME_ENTRY_PLACEBO_'+newroot.name+'_100.zip'))
                with zipfile.ZipFile(archive) as z:
                    for item in load(newroot/'report/REPORT_MANIFEST.json'):
                        self.assertEqual(len(z.read('report/'+item['path'])),item['bytes'])
                # An altered saved comparison input must stop before calculations.
                Path(oldpaths['F']).write_bytes(b'changed')
                self.assertEqual(runner.main(),1)
                self.assertEqual(load(newroot/'report/STATUS.json')['status'],'STOPPED')


if __name__=='__main__':unittest.main()
