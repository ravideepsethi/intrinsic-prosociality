import sys, tempfile, unittest, copy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase100_common import *
import phase100_recovery as recovery


class Quarantine75Tests(unittest.TestCase):
    def fixture(self,root):
        prior=root/'prior';coverage=root/'coverage';months=['2024-04','2025-01','2025-06']
        labels=['april','january','june'];quarantine=[];meta=[]
        for k,(month,label) in enumerate(zip(months,labels)):
            flag=f'F{k:07}';old=f'O{k:07}';new=f'N{k:07}'
            quarantine.append(dict(month=month,game_id=flag,disposition='CACHE_CONFLICT_OR_PRIOR_FLAG'))
            record=dict(game_id=flag,anchor_ms=100+k,cached_conflict_or_prior_flag=True)
            meta.append(record)
            old_members=pa.table(dict(game_id=[flag,old],retrieval_rank=[bytes(32)]*2))
            old_pool=pa.table(dict(game_id=[old],recipient_id=[k],recipient_rating=[1500.]))
            def build(tmp,old_members=old_members,old_pool=old_pool):
                io.table(tmp/'membership_PRIVATE.parquet',old_members);io.table(tmp/'pool.parquet',old_pool)
            io.stage(prior/'coverage'/month,'previous',build)
            io.table(coverage/month/'membership_PRIVATE.parquet',pa.table(dict(game_id=[flag,old,new],retrieval_rank=[bytes(32),bytes(32),threshold(75)])))
            io.table(coverage/month/'pool.parquet',pa.table(dict(game_id=[old,new],recipient_id=[k,k+10],recipient_rating=[1500.,1700.])))
            io.table(coverage/month/'unresolved_PRIVATE.parquet',pa.table(dict(game_id=[flag],disposition=['CACHE_CONFLICT_OR_PRIOR_FLAG'])))
            io.table(prior/'quarantine'/(label+'_merged_PRIVATE.parquet'),pa.Table.from_pylist([record]))
        io.table(prior/'quarantine/quarantined_records_PRIVATE.parquet',pa.Table.from_pylist(quarantine))
        io.js(prior/'quarantine/summary.json',dict(quarantined_rows=3,records=[],fixed_frame_rows_retained=True,substitute_rows_added=0))
        io.js(prior/'quarantine/_DONE.json',{})
        metadata=root/'merged/metadata.parquet';io.table(metadata,pa.Table.from_pylist(meta))
        return prior,coverage,months,dict(metadata=str(metadata))

    def test_exact_prior_set_and_pool_reproduced_and_resumable(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prior,coverage,months,phase=self.fixture(root)
            with mock.patch.object(recovery,'bind_previous',return_value=dict(root=str(prior),conf='previous')),mock.patch.object(ex,'MONTHS',months):
                got=recovery.audit_quarantine(None,None,phase,coverage,root/'quarantine','new',.5)[1]
                self.assertEqual(got['quarantined_rows'],3)
                self.assertEqual(got['counts_by_cohort']['increment_75_100'],0)
                self.assertTrue(got['certified75_pool_and_membership_reproduced'])
                again=recovery.audit_quarantine(None,None,phase,coverage,root/'quarantine','new',.5)[1]
                self.assertEqual(got,again)

    def test_new_flag_does_not_get_dropped_and_diagnostic_survives(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prior,coverage,months,phase=self.fixture(root)
            p=coverage/months[0]/'unresolved_PRIVATE.parquet'
            io.table(p,pa.table(dict(game_id=['F0000000','X0000000'],disposition=['CACHE_CONFLICT_OR_PRIOR_FLAG']*2)))
            with mock.patch.object(recovery,'bind_previous',return_value=dict(root=str(prior),conf='previous')),mock.patch.object(ex,'MONTHS',months):
                with self.assertRaisesRegex(RuntimeError,'identities differ'):
                    recovery.audit_quarantine(None,None,phase,coverage,root/'quarantine','new',.5)
            self.assertFalse((root/'quarantine/_DONE.json').exists())
            self.assertEqual(io.load(root/'quarantine_diagnostic.json')['current_unresolved'],4)

    def test_changed_prior_metadata_cannot_pass_as_same_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prior,coverage,months,phase=self.fixture(root)
            p=coverage/months[0]/'pool.parquet';data=io.read(p).to_pydict();data['recipient_rating'][0]=1501.;io.table(p,pa.table(data))
            with mock.patch.object(recovery,'bind_previous',return_value=dict(root=str(prior),conf='previous')),mock.patch.object(ex,'MONTHS',months):
                with self.assertRaisesRegex(RuntimeError,'features changed'):
                    recovery.audit_quarantine(None,None,phase,coverage,root/'quarantine','new',.5)

if __name__=='__main__':unittest.main()
