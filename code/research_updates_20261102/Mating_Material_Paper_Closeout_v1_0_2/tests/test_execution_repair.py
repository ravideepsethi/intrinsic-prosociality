import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'closeout'))
import test_closeout as fixtures
import mechanism as new
import reference_mechanism_v100 as old
import bounded_io as bio
from closeout_common import *
import pyarrow.compute as pc

def ordered(path):
    t=pq.read_table(path);return t.take(pc.sort_indices(t,sort_keys=[('row_id','ascending')]))

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CloseoutTests();self.fixture.setUp()
        self.root=self.fixture.root;self.a=self.fixture.a
        self.parts=patch.object(bio,'PARTITIONS',7);self.parts.start()
    def tearDown(self):self.parts.stop();self.fixture.tearDown()
    def test_same_rows_weights_coefficients_and_covariance_as_v100(self):
        auth=self.fixture.ordinary(3000)
        before=old.prepare(self.a,self.root/'old','old',auth)
        after=new.prepare(self.a,self.root/'new','new',auth)
        a,b=ordered(before),ordered(after)
        self.assertEqual(a.schema,b.schema)
        for name in a.column_names:
            if pa.types.is_floating(a[name].type):np.testing.assert_allclose(a[name].to_numpy(),b[name].to_numpy(),atol=1e-14,rtol=1e-14)
            else:self.assertEqual(a[name].to_pylist(),b[name].to_pylist(),name)
        for spec in ('overlap','exact_time_control','within_recipient'):
            x=old.fit(self.a,self.root/'old','old',before,spec)
            y=new.fit(self.a,self.root/'new','new',after,spec)
            for rx,ry in zip(x['estimates'],y['estimates']):
                for field in ('rows','strata','recipient_clusters','inference_status'):self.assertEqual(rx[field],ry[field])
                for field in ('estimate_pp','standard_error_pp','ci95_low','ci95_high','recipient_cluster_se_pp'):
                    np.testing.assert_allclose(rx[field],ry[field],atol=1e-9,rtol=1e-9)
            for rx,ry in zip(x['support'],y['support']):
                for field in rx:np.testing.assert_allclose(rx[field],ry[field],atol=1e-9,rtol=1e-9)
            xsel=ordered(self.root/'old/PRIVATE/ordinary_models'/spec/'selected.parquet')
            ysel=ordered(self.root/'new/PRIVATE/ordinary_models'/spec/'selected.parquet')
            np.testing.assert_array_equal(xsel['row_id'].to_numpy(),ysel['row_id'].to_numpy())
            np.testing.assert_allclose(xsel['weight'].to_numpy(),ysel['weight'].to_numpy(),atol=0,rtol=0)
    def test_interrupted_join_reuses_verified_partitions(self):
        auth=self.fixture.ordinary();run=self.root/'run';original=new.stage
        def stopped(path,*args,**kwargs):
            if Path(path).name=='002' and Path(path).parent.name=='joined':raise RuntimeError('Synthetic interruption')
            return original(path,*args,**kwargs)
        with patch.object(new,'stage',stopped):
            with self.assertRaisesRegex(RuntimeError,'Synthetic interruption'):new.prepare(self.a,run,'resume',auth)
        part=run/'PRIVATE/ordinary_prepare_v101/joined/000/source.parquet';stamp=signature(part)
        result=new.prepare(self.a,run,'resume',auth)
        self.assertEqual(signature(part),stamp);self.assertEqual(rows(result),1200)
    def test_different_row_groups_align_and_duplicate_score_fails(self):
        auth=self.fixture.ordinary();path=Path(auth['paths']['frame_scores']);t=pq.read_table(path)
        pq.write_table(t,path,row_group_size=17)
        self.assertEqual(rows(new.prepare(self.a,self.root/'aligned','ok',auth)),1200)
        t=pa.concat_tables([t.slice(0,5),t.slice(4)])
        pq.write_table(t,path,row_group_size=17)
        with self.assertRaisesRegex(RuntimeError,'duplicate row_id'):new.prepare(self.a,self.root/'bad','bad',auth)
    def test_partition_keys_agree_across_types_batches_and_counts(self):
        source=self.root/'source.parquet';t=pa.table(dict(row_id=np.arange(100),game_id=['g'+str(i%13) for i in range(100)]))
        pq.write_table(t,source,row_group_size=9)
        parts,info=bio.partition(source,self.root/'parts','part','game_id')
        seen={}
        for k,p in enumerate(parts):
            for value in pq.read_table(p)['game_id'].to_pylist():
                self.assertEqual(seen.setdefault(value,k),k)
        self.assertEqual(sum(info['bucket_rows']),100)
        self.assertLessEqual(info['maximum_queued_arrow_bytes'],bio.BUFFER_BYTES+bio.BATCH*100)
    def test_repair_keeps_reviewed_configuration_identity(self):
        # The frozen estimator fixtures legitimately import their own module
        # named pipeline. Load the repaired launcher under a unique test name.
        import importlib.util
        spec=importlib.util.spec_from_file_location('_repair_pipeline_test',ROOT/'closeout/pipeline.py')
        pipeline=importlib.util.module_from_spec(spec);spec.loader.exec_module(pipeline)
        parent='/Volumes/XT_Pro/lichess_kindness/derived/replication/mating_material_iv_batch_v100_PRIVATE/'+PARENT_CONF[:16]
        config=dict(version='1.0.0',package_sha256=pipeline.BASE_PACKAGE_SHA,parent=parent,parent_configuration=PARENT_CONF,production_network=False)
        self.assertEqual(c.key(config),pipeline.BASE_CONF)

if __name__=='__main__':unittest.main()
