"""Regression coverage for the production F50 projection and v1.0.3 migration."""
from test_r7 import fixture
from r7_common import *
import unittest,tempfile,copy
from unittest import mock
import r7_models,r7_outcomes,r7_preflight,r7_resume,run_r7,r7_report


def production_tables(folder,n=4200,incomplete=0):
    d=fixture(n);n=len(d['row_id'])
    # Match phase_features.combine: complete outcomes in wide features, then
    # remove all six follow-up columns from the published entry projection.
    d['complete90']=np.ones(n,bool)
    d['anchor_ms']=np.asarray(d['archive_start_ms'],np.int64)+60_000
    if incomplete:
        d['anchor_ms'][-incomplete:]=r7_outcomes.core.PANEL_END-90*DAY
        d['archive_start_ms'][-incomplete:]=d['anchor_ms'][-incomplete:]-60_000
        d['complete90'][-incomplete:]=False
    for key in ('outcome_gid','outcome_t','outcome_start','outcome_opponent'):
        d[key]=np.zeros(n,np.int64) if key!='outcome_gid' else np.full(n,'')
    wide=pa.table(dict(d,entry_eligible=np.ones(n,bool),previous_frame=np.zeros(n,bool),author_game=np.zeros(n,bool)))
    for key in ('y','reached'):
        wide=wide.set_column(wide.schema.get_field_index(key),key,pa.array(d[key],mask=~d['complete90']))
    omitted={'y','reached','outcome_gid','outcome_t','outcome_start','outcome_opponent'}
    entry=pa.table({k:v for k,v in d.items() if k not in omitted})
    ordinary=pa.table(d).filter(pa.array(d['complete90']))
    # Exercise a proper subset and deliberately shuffled source order.
    ordinary=ordinary.take(pa.array(np.arange(0,len(ordinary),2)))
    io.table(folder/'entry.parquet',entry)
    io.table(folder/'ordinary.parquet',ordinary)
    io.table(folder/'features.parquet',wide.take(pa.array(np.arange(n)[::-1])))
    return d


class OutcomeRevisionTests(unittest.TestCase):
    def test_real_projection_fails_preflight_then_attachment_restores_all_A4_columns(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=production_tables(p)
            jobs=run_r7.plan({'S0':p/'ordinary.parquet','F50':p/'entry.parquet','O50':p/'ordinary.parquet'},p,'fixture')
            entry_jobs=[j for j in jobs if j['kind']=='entry']
            with self.assertRaisesRegex(RuntimeError,'missing columns y'):r7_preflight.check(entry_jobs)
            out,info=r7_outcomes.attach(p/'entry.parquet',p/'ordinary.parquet',p/'features.parquet',p/'attached','fixture',3)
            self.assertEqual(info['rows_removed'],0);self.assertEqual(info['incomplete90_rows'],0)
            self.assertEqual(info['ordinary_bridge_rows'],len(io.read(p/'ordinary.parquet')))
            got=io.read(out);np.testing.assert_array_equal(io.arr(got,'row_id'),d['row_id'])
            np.testing.assert_array_equal(io.arr(got,'y'),d['y'])
            # Every pre-existing entry column is preserved exactly.
            self.assertTrue(got.select(pq.ParquetFile(p/'entry.parquet').schema_arrow.names).equals(io.read(p/'entry.parquet')))
            for j in entry_jobs:j['input']=str(out)
            self.assertEqual(r7_preflight.check(entry_jobs)['model_count'],len(entry_jobs))
            job=next(j for j in entry_jobs if j['sample']=='F50' and j['level']=='X0')
            r7_models.model_job(job)
            actual=io.load(Path(job['output'])/'result.json')
            expected,_=r7_models.estimate(d,'entry','F50',release_inputs=True)
            self.assertEqual(actual,io.clean(expected))
            self.assertEqual(len(actual['A_predicted_outcome']),12)
            self.assertEqual({r['predicted_outcome'] for r in actual['A_predicted_outcome']},{'analysis_entry_90','recipient_disconnect_main','y'})
            digest=io.sha(out)
            out2,_=r7_outcomes.attach(p/'entry.parquet',p/'ordinary.parquet',p/'features.parquet',p/'attached','fixture',3)
            self.assertEqual(io.sha(out2),digest)

    def test_incomplete_outcomes_stay_null_and_full_row_Y_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=production_tables(p,incomplete=3);n=len(d['row_id'])
            out,info=r7_outcomes.attach(p/'entry.parquet',p/'ordinary.parquet',p/'features.parquet',p/'attached','fixture',3)
            self.assertEqual(info['incomplete90_rows'],3)
            self.assertEqual(io.read(out,['y'])['y'].null_count,3)
            result,_=r7_models.estimate(load_fit_columns(out),'entry','F50',release_inputs=True)
            self.assertTrue(all(r['n']==n for r in result['B_estimates']))
            self.assertEqual(len(result['A_joint_balance']),67)
            unknown=[r for r in result['A_joint_balance'] if r.get('dependent')=='y']
            self.assertEqual(len(unknown),15)
            self.assertTrue(all(r['reason']=='INCOMPLETE_FOLLOWUP_ON_FROZEN_ROWS' and r['missing_outcome_rows']==3 and r['rows_removed']==0 for r in unknown))
            pred=[r for r in result['A_predicted_outcome'] if r['predicted_outcome']=='y']
            self.assertEqual(len(pred),4);self.assertTrue(all(not r['supported'] for r in pred))
            for r in pred:self.assertNotIn('coefficient_pp',r)
            model=p/'models/F50';model.mkdir(parents=True);io.js(model/'result.json',result)
            summary=r7_report.export(p,p/'desktop','fixture','AB_COMPLETE_C_PENDING',time.monotonic(),1)
            self.assertEqual(summary['full_row_F50_Y_unavailable_samples'],['F50'])
            self.assertIn('WITH_UNAVAILABLE_F50_Y',summary['status'])

    def test_attachment_rejects_missing_duplicate_identity_and_wrong_ordinary_outcome(self):
        for problem in ('missing','duplicate','identity','ordinary'):
            with self.subTest(problem=problem),tempfile.TemporaryDirectory() as td:
                p=Path(td);production_tables(p,n=30)
                table=io.read(p/'features.parquet')
                if problem=='missing':table=table.slice(1)
                if problem=='duplicate':table=pa.concat_tables([table,table.slice(0,1)])
                if problem=='identity':
                    values=io.arr(table,'opponent_id').copy();values[0]+=1
                    table=table.set_column(table.schema.get_field_index('opponent_id'),'opponent_id',pa.array(values))
                io.table(p/'features.parquet',table)
                if problem=='ordinary':
                    o=io.read(p/'ordinary.parquet');v=io.arr(o,'y').copy();v[0]=not v[0]
                    io.table(p/'ordinary.parquet',o.set_column(o.schema.get_field_index('y'),'y',pa.array(v)))
                with self.assertRaises(RuntimeError):r7_outcomes.attach(p/'entry.parquet',p/'ordinary.parquet',p/'features.parquet',p/'attached','fixture',3)

    def test_attachment_rejects_imputed_incomplete_and_missing_complete_outcomes(self):
        for problem in ('incomplete_filled','complete_null','wrong_cutoff'):
            with self.subTest(problem=problem),tempfile.TemporaryDirectory() as td:
                p=Path(td);production_tables(p,n=30,incomplete=1);t=io.read(p/'features.parquet')
                if problem=='wrong_cutoff':
                    values=io.arr(t,'anchor_ms').copy();values[0]-=2*DAY
                    t=t.set_column(t.schema.get_field_index('anchor_ms'),'anchor_ms',pa.array(values))
                else:
                    values=t['y'].to_pylist();values[0 if problem=='incomplete_filled' else 1]=False if problem=='incomplete_filled' else None
                    t=t.set_column(t.schema.get_field_index('y'),'y',pa.array(values,type=t.schema.field('y').type))
                io.table(p/'features.parquet',t)
                with self.assertRaises(RuntimeError):r7_outcomes.attach(p/'entry.parquet',p/'ordinary.parquet',p/'features.parquet',p/'attached','fixture',3)

    def test_prepare_authenticates_the_archived_feature_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);production_tables(p,n=30)
            def build(tmp):io.table(tmp/'features.parquet',io.read(p/'features.parquet'))
            stable_stage(p/'phase/assembled','phasefixture',build,[p/'features.parquet'])
            binding={'phase50':{'root':str(p/'phase'),'conf':'phasefixture'}}
            paths={'F50':p/'entry.parquet','O50':p/'ordinary.parquet'}
            got,info=r7_outcomes.prepare(paths,binding,p/'attach','fixture',3)
            self.assertTrue(got['F50'].exists())
            with (p/'phase/assembled/features.parquet').open('ab') as f:f.write(b'changed')
            with self.assertRaises(RuntimeError):r7_outcomes.prepare(paths,binding,p/'attach2','fixture',3)

    def test_preflight_checks_all_32_models_and_flags_each_control_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=production_tables(p);io.table(p/'all.parquet',pa.table(d))
            paths={k:p/'all.parquet' for k in ('S0','F50','O50')}
            jobs=run_r7.plan(paths,p,'fixture')
            self.assertEqual(r7_preflight.check(jobs)['model_count'],32)
            for missing in ('claim_30','comp_counterparts_7d','environment_supported','received','y'):
                io.table(p/'all.parquet',pa.table({k:v for k,v in d.items() if k!=missing}))
                with self.assertRaisesRegex(RuntimeError,'missing columns'):r7_preflight.check(jobs)

    def test_production_gate_reuse_is_pinned_read_only_and_resumable(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);old=p/'old';old.mkdir();source=p/'data';source.write_text('authenticated')
            binding={'paths':{'entry':str(source)}}
            config=dict(version='1.0.2',package_sha256=r7_resume.GATE_PACKAGE,spec_sha256=io.sha(ROOT/'R7_SPEC.md'))
            conf=io.cfgsha(config);io.js(old/'config.json',config);io.js(old/'INPUTS_PRIVATE.json',binding)
            def build(tmp):
                io.js(tmp/'checks.json',[dict(check=str(i),passed=True) for i in range(9)])
                io.js(tmp/'original_panel_A.json',{'reproduced':True});io.js(tmp/'original_primary_balance.json',{'reproduced':True})
                return dict(status='REPRODUCTION_GATE_PASSED')
            stable_stage(old/'reproduction',conf,build,[source])
            files={name:io.sha(old/'reproduction'/name) for name in r7_resume.GATE_FILES}
            before={str(q):io.sha(q) for q in old.rglob('*') if q.is_file()}
            with mock.patch.object(r7_resume,'GATE_CONF',conf),mock.patch.object(r7_resume,'GATE_FILES',files):
                reuse=r7_resume.bind_reproduction(old,binding)
                new,receipt=r7_resume.reuse_reproduction(reuse,binding,p/'new','newfixture')
                self.assertEqual(receipt['checks'],9)
                for name,digest in files.items():self.assertEqual(io.sha(new/name),digest)
                r7_resume.reuse_reproduction(reuse,binding,p/'new','newfixture')
                self.assertEqual(before,{str(q):io.sha(q) for q in old.rglob('*') if q.is_file()})
                with self.assertRaisesRegex(RuntimeError,'binding differs'):r7_resume.bind_reproduction(old,{'paths':{}})
                source.write_text('changed')
                with self.assertRaisesRegex(RuntimeError,'dependency changed'):r7_resume.bind_reproduction(old,binding)
            with self.assertRaisesRegex(RuntimeError,'reviewed R7'):r7_resume.bind_reproduction(old,binding)

if __name__=='__main__':unittest.main()
