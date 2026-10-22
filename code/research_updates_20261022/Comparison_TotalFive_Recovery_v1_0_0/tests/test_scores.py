import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import score_worker as s
np=s.np
class Scores(unittest.TestCase):
    def test_alltime_excludes_every_focal_pair_including_future(self):
        h=dict(j=np.array([2]*8),i=np.array([1,1,3,4,5,6,7,8]),t=np.arange(8,dtype=np.int64)+1700000000000,y=np.array([1,1,1,0,0,1,0,1]),cell=np.ones(8,dtype=np.int64))
        q=dict(row_id=np.array([1]),recipient_id=np.array([1]),opponent_id=np.array([2]))
        with patch.object(s.pc.frozen.r9_scores,'reference_map',return_value=({},{})),patch.object(s.pc.frozen.r9_scores,'donor_weights',side_effect=lambda h,r,f,m:(np.full(len(h['j']),.25),{})):
            score,_=s.pc.inputs.alltime(h,q,np.array([]))
        self.assertEqual(score['n'][0],6);self.assertEqual(score['counterparts'][0],6);self.assertAlmostEqual(score['expected'][0],.25);self.assertAlmostEqual(score['adjusted'][0],.25)
    def test_actual_score_worker_removes_authors_and_focal_pair(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);part=root/'donors.parquet';query=root/'query.parquet';ref=root/'reference.npy'
            h=dict(j=np.array([2]*9+[99]),i=np.array([1,1,3,4,5,6,7,8,99,3]),t=np.arange(10,dtype=np.int64)+1700000000000,y=np.array([1,1,1,0,0,1,0,1,1,1]),cell=np.ones(10,dtype=np.int64),arm=np.ones(10,bool),fair=np.zeros(10,bool))
            s.pq.write_table(s.pa.table(h),part);s.pq.write_table(s.pa.table(dict(row_id=[1],recipient_id=[1],opponent_id=[2])),query);np.save(ref,np.array([0.]))
            job=dict(parts=[dict(path=str(part),sha256=s.u.sha(part),bytes=part.stat().st_size)],query=str(query),reference=str(ref),authors=[99],out=str(root/'out'),conf='x')
            with patch.object(s.pc.frozen.r9_scores,'reference_map',return_value=({},{})),patch.object(s.pc.frozen.r9_scores,'donor_weights',side_effect=lambda h,r,f,m:(np.full(len(h['j']),.25),{})):
                info=s.score_job(job)
            values=s.pq.read_table(root/'out/scores.parquet').to_pylist()[0]
            self.assertEqual(values['n_A'],6);self.assertEqual(values['counterparts_A'],6);self.assertAlmostEqual(values['adjusted_A'],.25);self.assertEqual(info['oracle_checks'],1)
if __name__=='__main__':unittest.main()
