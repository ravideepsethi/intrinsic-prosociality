"""Verify read-only adoption of all twenty saved session models end to end."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import engine as e
import session_bounded as s
sys.path.insert(0,str(e.ROOT/'vendor/session'))
import repetition,util
from fixtures import focal_frame

class SessionRepairTests(unittest.TestCase):
    def test_saved_twenty_models_are_reused_without_parent_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent';old=parent/'PRIVATE/results/excluded/session';out=root/'repaired'
            d=focal_frame(3000);files=[];history=[]
            for j,month in enumerate(e.MONTHS):
                p=old/'PRIVATE/history'/month/'focal_history.parquet';p.parent.mkdir(parents=True)
                d.loc[d.month_code==j].to_parquet(p,index=False);files.append(str(p));history.append(e.record(p))
            for j,month in enumerate(['2023-10']+e.MONTHS):
                p=old/'PRIVATE/history'/month/'sessions30.parquet';p.parent.mkdir(parents=True,exist_ok=True)
                e.pd.DataFrame(dict(chooser=[1,2,22],start30=[1699000000000+j*100000000]*3,observed_session_length=[2,3,18],left_censored=[False]*3,last_t=[1699003000000+j*100000000]*3)).to_parquet(p,index=False)
                history.append(e.record(p))
            auth={'fingerprint':'synthetic-auth'};shared={'key':'synthetic-history','files':history}
            e.write(parent/'PRIVATE/session_history_reuse/DONE.json',shared)
            key=e.digest([auth['fingerprint'],shared['key']])
            repetition.run(files,old,key,2,4)
            (old/'report/history_reuse_audit.csv').write_text('status\nSYNTHETIC\n')
            before={str(p):e.signature(p) for p in old.rglob('*') if p.is_file()}
            result=s.finish(SimpleNamespace(workers=2,memory_gb=5),auth,out,parent)
            self.assertEqual(result['specifications'],20)
            for name in ('coefficients','joint_tests','count_scenario_comparison','session_length_by_account_grant_rate'):
                a=e.pd.read_csv(old/'report/repetition'/(name+'.csv'));b=e.pd.read_csv(out/'report/repetition'/(name+'.csv'))
                e.pd.testing.assert_frame_equal(a,b,check_dtype=False,rtol=1e-12,atol=1e-12)
            self.assertEqual(before,{str(p):e.signature(p) for p in old.rglob('*') if p.is_file()})
            self.assertEqual(e.read(out/'report/REPAIR.json')['new_regression_fits'],0)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.set_start_method('spawn')
    unittest.main(verbosity=2)
