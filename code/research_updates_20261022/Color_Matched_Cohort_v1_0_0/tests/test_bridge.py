from pathlib import Path
import tempfile,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import shared_membership as bridge

class BridgeTests(unittest.TestCase):
    def test_completed_shared_membership_key_reused_and_corruption_rejected(self):
        c=bridge.c
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'work';auth=root/'auth';src=root/'source/_DONE.json';adj=root/'adj/_DONE.json'
            c.write_json(src,dict(result=dict(scan_issues=0)))
            c.write_json(adj,dict(result=dict(bridge='passed')))
            inputs=[bridge.producer.snapshot(src),bridge.producer.snapshot(adj)]
            code=bridge.producer.code_signature();key=c.digest(dict(code=code,inputs=inputs,source_result=c.load(src)['result']))
            mr=work/'membership'/key;files=[]
            for month in ('2025-11','2025-12','2026-01'):
                rel=f'membership/month={month}/membership_PRIVATE.parquet';p=mr/rel;p.parent.mkdir(parents=True,exist_ok=True)
                c.pq.write_table(c.pa.table(dict(game_id=['testgame'],source=['pool'])),p)
                files.append(dict(c.receipt(p),path=rel))
            c.write_json(mr/'_DONE.json',dict(key=key,inputs=inputs,files=files,result=dict(flow=[])))
            before=c.stamp(mr/files[0]['path']);hit=bridge.fast_membership(work,auth,code)
            self.assertEqual(hit[0],mr);self.assertEqual(before,c.stamp(mr/files[0]['path']))
            self.assertIsNone(bridge.fast_membership(work,auth,'different-code'))
            with (mr/files[0]['path']).open('ab') as f:f.write(b'changed')
            with self.assertRaisesRegex(RuntimeError,'changed'):bridge.fast_membership(work,auth,code)

if __name__=='__main__':unittest.main(verbosity=2)
