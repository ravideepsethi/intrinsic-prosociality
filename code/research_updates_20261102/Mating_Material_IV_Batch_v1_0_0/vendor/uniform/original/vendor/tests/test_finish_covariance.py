import unittest,tempfile,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import rebuild_models as old
import finish_covariance as new
import run_finish as runner


def data(root,n=87):
    rng=np.random.default_rng(149);i=rng.integers(1,19,n);j=rng.integers(1,19,n)
    j=np.where(i==j,j+40,j);dates=rng.integers(1,10,n);v=rng.normal(size=(n,4))
    # Overlapping sample rows, reversed pairs and same-account/different-date
    # observations all contribute to the independent pairwise OR reference.
    i[-4:]=i[:4];j[-4:]=j[:4];dates[-4:]=dates[:4]
    v[:n//2,1::2]=0.;v[n//2:,::2]=0.
    path=root/'input.parquet'
    pq.write_table(pa.table(dict(recipient_id=i,opponent_id=j,date=dates,
        a=v[:,0],b=v[:,1],c=v[:,2],d=v[:,3])),path)
    share=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(dates[:,None]==dates)
    return path,v.T@share.astype(float)@v


class BoundedCovariance(unittest.TestCase):
    def test_partitioned_covariance_equals_direct_OR_and_old_SQL(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,expected=data(root)
            got=new.covariance(p,['a','b','c','d'],root/'new',.2,buckets=4)
            original=old.sql_covariance(p,['a','b','c','d'],root/'old',.2)
            np.testing.assert_allclose(got,expected,atol=1e-10)
            np.testing.assert_allclose(got,original,atol=1e-10)
            self.assertNotEqual(got[0,1],0.)

    def test_adaptive_memory_split_keeps_complete_groups(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,expected=data(root);calls=[];original=new.grouped_outer
            def limited(c,source,keys,columns):
                calls.append(source)
                if 'person' in keys and ' WHERE ' not in source:
                    raise new.duckdb.OutOfMemoryException('forced test memory limit')
                return original(c,source,keys,columns)
            with patch.object(new,'grouped_outer',side_effect=limited):
                got=new.covariance(p,['a','b','c','d'],root/'work',.2,buckets=2)
            self.assertTrue(any(' WHERE hash(person,date)' in q for q in calls))
            np.testing.assert_allclose(got,expected,atol=1e-10)

    def test_interruption_resumes_leaves_and_rejects_tampered_partition(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,expected=data(root);original=new.grouped_outer;count=0
            def interrupted(*args):
                nonlocal count
                count+=1
                if count==4:raise KeyboardInterrupt()
                return original(*args)
            with patch.object(new,'grouped_outer',side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):new.covariance(p,['a','b','c','d'],root/'work',.2,buckets=4)
            before={p:p.stat().st_mtime_ns for p in (root/'work').rglob('_DONE.json')}
            got=new.covariance(p,['a','b','c','d'],root/'work',.2,buckets=4)
            np.testing.assert_allclose(got,expected,atol=1e-10)
            self.assertTrue(all(p.stat().st_mtime_ns==t for p,t in before.items()))
            with patch.object(new,'partition',side_effect=AssertionError('partition reran')),patch.object(new,'grouped_outer',side_effect=AssertionError('leaf reran')):
                np.testing.assert_array_equal(new.covariance(p,['a','b','c','d'],root/'work',.2,buckets=4),got)
            part=next((root/'work').rglob('data.parquet'));part.write_bytes(part.read_bytes()+b'x')
            with self.assertRaises(RuntimeError):new.covariance(p,['a','b','c','d'],root/'work',.2,buckets=4)

    def test_invalid_self_pair_and_nulls_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'bad.parquet'
            for i,j,date,value in [(1,1,1,.1),(None,2,1,.1),(1,2,None,.1),(1,2,1,float('nan'))]:
                pq.write_table(pa.table(dict(recipient_id=[i],opponent_id=[j],date=[date],a=[value])),p)
                with self.assertRaises(RuntimeError):new.covariance(p,['a'],root/'work',.2,buckets=2)

    def test_contrast_matches_original_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,_=data(root);t=pq.read_table(p);n=len(t)//2
            for side,table,beta in [('left',t.slice(0,n),.12),('right',t.slice(n),.03)]:
                dest=root/side;dest.mkdir();use='a' if side=='left' else 'b'
                pq.write_table(table.select(['recipient_id','opponent_id','date',use]).rename_columns(['recipient_id','opponent_id','date','y']),dest/'influence_PRIVATE.parquet')
                save(dest/'result.json',dict(estimates=[dict(outcome='y',estimator='reduced_form',coefficient=beta,n=len(table))]))
            job=dict(left=str(root/'left'),right=str(root/'right'),outcomes=['y'],label='test',level='X0',conf='unit',output=str(root/'old'))
            old.contrast_job(job);job.update(output=str(root/'new'),work=str(root/'work'))
            new.contrast_job(job)
            a=load(root/'old/result.json')[0];b=load(root/'new/result.json')[0]
            np.testing.assert_allclose(a['covariance_matrix'],b['covariance_matrix'],atol=1e-12)
            for key in ('coefficient','standard_error','p_value_asymptotic'):
                self.assertAlmostEqual(a[key],b[key],places=12)
            stamp=(root/'new/result.json').stat().st_mtime_ns
            with patch.object(new,'covariance',side_effect=AssertionError('contrast reran')):new.contrast_job(job)
            self.assertEqual(stamp,(root/'new/result.json').stat().st_mtime_ns)


class ParentAuthentication(unittest.TestCase):
    def test_authentication_rejects_tampering_and_changed_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';source.write_text('original')
            stage(root/'model','unit',lambda t:(save(t/'result.json',dict(a=1)) or {}),[source])
            runner.Authentication().stage(root/'model','unit',['result.json'],[source])
            with self.assertRaises(RuntimeError):runner.Authentication().stage(root/'model','other',['result.json'],[source])
            with self.assertRaises(RuntimeError):runner.Authentication().stage(root/'model','unit',['result.json'],[root/'different'])
            source.write_text('changed!')
            with self.assertRaises(RuntimeError):runner.Authentication().stage(root/'model','unit',['result.json'],[source])
            source.write_text('original');(root/'model/result.json').write_text('{}')
            with self.assertRaises(RuntimeError):runner.Authentication().stage(root/'model','unit',['result.json'],[source])

    def test_default_parent_is_reviewed_and_no_download_options(self):
        args=runner.parser().parse_args([])
        self.assertEqual(runner.PARENT_CONF[:12],'5eca56c416c5')
        self.assertIsNone(args.reuse_completed)
        self.assertFalse(hasattr(args,'workers'));self.assertFalse(hasattr(args,'audit_only'))
        self.assertEqual(sha(ROOT/'evidence/v103_075_REPORT_MANIFEST.json'),runner.PARENT_REPORT)


if __name__=='__main__':unittest.main()
