"""Exercise orchestration, exports and original-kernel replay on synthetic data."""
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
from test_estimators import fixture
from types import SimpleNamespace
import models

class ModelSequenceTests(unittest.TestCase):
    def test_models_supplements_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);(run/'report').mkdir()
            src,sc=fixture(run)
            data=pq.read_table(src).to_pydict();n=len(data['row_id'])
            for field in ('uniform_keep','legacy_primary','spaced90','legacy_windows','spaced30','first_recipient'):
                data[field]=[True]*n
            for field in ('fair','kind','disconnect','receipt','claim'):
                data['legacy_'+field+'_90']=data[field+'_90']
            data['pre_games_30d']=[max(1,x//3) for x in data['pre_games_90d']]
            pq.write_table(pa.table(data),src)
            a=SimpleNamespace(memory_gb=4.,workers=2)
            models.main(a,run,'sequence_fixture',src,sc)
            models.supplements(a,run,'sequence_fixture',src,sc)
            self.assertTrue(read(run/'report/SUPPLEMENT_REPLAY.json')['passed'])
            self.assertEqual(read(run/'report/EXPOSURE_COUNTS.json')['rows'],n)
            self.assertTrue((run/'report/CONTRASTS.csv').is_file())
            self.assertTrue((run/'report/SUPPLEMENT_CONTRASTS.csv').is_file())
            import companions
            companions.bins(a,run,'sequence_fixture',src,sc)
            self.assertTrue((run/'report/fig5_iv_bins_material.pdf').is_file())
            # The original badge estimator must reproduce the new baseline.
            sys.path.insert(0,str(ROOT/'vendor/patron/code'))
            import fit_badge
            badge=run/'badge_fixture';(badge/'report').mkdir(parents=True)
            save(badge/'PRIVATE/BINDING.json',dict(source=str(src),scores=str(sc),baseline=str(run/'PRIVATE/models/uniform_unspaced/result.json')))
            fit_badge.baseline(SimpleNamespace(memory_gb=4.,workers=2,run=badge,conf='badge_fixture'))
            # Completed fits must be verified and reused on the next invocation.
            before=(run/'PRIVATE/models/uniform_unspaced/result.json').stat().st_mtime_ns
            models.main(a,run,'sequence_fixture',src,sc)
            self.assertEqual(before,(run/'PRIVATE/models/uniform_unspaced/result.json').stat().st_mtime_ns)

if __name__=='__main__':unittest.main()
