import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

sys.path.insert(0,str(Path(__file__).resolve().parent))
import build_game_source as m


def dump(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=b''.join(json.dumps(r).encode()+b'\n' for r in rows)
    if path.name.endswith(('.zst','.zstd')):data=zstd.ZstdCompressor(write_checksum=True).compress(data)
    if path.name.endswith('.gz'):data=gzip.compress(data)
    path.write_bytes(data);old=time.time()-300;os.utime(path,(old,old));return path


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"root with space's";self.root.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def job(self,p):return {'path':str(p),'file_id':hashlib.sha256(str(p).encode()).hexdigest()[:24],'kind':m.kind(p.name),**m.fingerprint(p)}
    def index(self,ids):
        p=self.root/'ids.npy';np.save(p,np.array(sorted(ids),dtype='S8'));m.init_worker(p);return p
    def test_normalization_no_inference_and_conflicting_aliases(self):
        self.assertIsNone(m.normalize({'game':{'id':'Game0001','source':'pool'}}))
        self.assertIsNone(m.normalize({'game_id':'Game0001','source_block':'pool'})['source'])
        self.assertTrue(m.normalize({'id':'Game0001','source':'pool','api_source':'friend'})['invalid'])
        self.assertTrue(m.normalize({'id':'Game0001','source':True})['invalid'])
        self.assertEqual(m.normalize({'game_id':'Game0001','api_source':'pool'})['source'],'pool')
        with self.assertRaises(ValueError):m.normalize({'game_id':'Game0001','id':'Game0002','source':'pool'})
    def test_actual_compression_frames_and_truncation(self):
        row={'id':'Game0001','source':'pool'}
        encoded=json.dumps(row).encode()+b'\n'
        frame=zstd.ZstdCompressor().compress(encoded)
        self.assertEqual(len(list(m.stream_lines(io.BytesIO(frame+frame),'x.ndjson.zstd'))),2)
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            list(m.stream_lines(io.BytesIO(frame+frame[:-1]),'x.ndjson.zst'))
        self.assertEqual(list(m.stream_lines(io.BytesIO(gzip.compress(encoded)),'x.json.gz')),[encoded[:-1]])
    def test_mmap_membership_outside_bounds_and_resume_hashes(self):
        self.index(['Game0001','Game0002'])
        p=dump(self.root/'api/raw.ndjson',[{'id':'zzzzzzzz','source':'pool'},{'id':'00000000','source':'pool'},
                                         {'id':'Game0001','source':'pool'}])
        job=self.job(p);out=self.root/'parts'
        r=m.scan(job,out,{'test':1});self.assertEqual(r['counts']['matched_rows'],1)
        self.assertEqual(m.scan(job,out,{'test':1}),r)
        with open(r['output'],'ab') as f:f.write(b'corrupt')
        with self.assertRaises(ValueError):m.scan(job,out,{'test':1})
    def test_zip_tar_arrays_and_source_parquet(self):
        self.index(['Game0001','Game0002'])
        table=pa.table({'game_id':['Game0002'],'api_source':['pool']})
        sink=pa.BufferOutputStream();pq.write_table(table,sink)
        data=json.dumps([{'id':'Game0001','source':'friend'}]).encode()+b'\n'
        zpath=self.root/'api-export.zip'
        with zipfile.ZipFile(zpath,'w') as z:
            z.writestr('raw/games.ndjson.zst',zstd.ZstdCompressor().compress(data))
            z.writestr('response/data.parquet',sink.getvalue().to_pybytes())
            z.writestr('../raw/ignored.txt','no filesystem extraction')
        tarpath=self.root/'api-backup.tar.gz'
        with tarfile.open(tarpath,'w:gz') as tar:
            for name,content in [('games.ndjson',data),('responses/data.parquet',sink.getvalue().to_pybytes())]:
                info=tarfile.TarInfo(name);info.size=len(content);tar.addfile(info,io.BytesIO(content))
        for p in [zpath,tarpath]:
            r=m.scan(self.job(p),self.root/'parts',{'test':1})
            self.assertEqual(r['counts']['matched_rows'],2)
            self.assertEqual(r['input_sha256'],m.digest(p))
    def test_discovery_no_month_name_restriction_and_no_feedback(self):
        root=self.root/'api'
        want=dump(root/'month=2026-02/raw/a.ndjson',[{'id':'Game0001','source':'pool'}])
        dump(root/'quarantine/a.ndjson',[])
        dump(root/'game_source_24m_PRIVATE/a.ndjson',[])
        dump(root/'smoke-test/a.ndjson',[])
        pq.write_table(pa.table({'game_id':['Game0001'],'source_block':['pool']}),root/'data.parquet')
        old=time.time()-300;os.utime(root/'data.parquet',(old,old))
        run=self.root/'run';run.mkdir()
        result=m.discover([root],run)
        self.assertEqual([j['path'] for j in result['jobs']],[str(want)])
    def fixture(self,n=24):
        months=m.MONTHS[:n];paths=[]
        schema=pa.schema([('game_id',pa.string()),('month',pa.string()),('api_status',pa.string()),('api_winner',pa.string()),
                          ('api_created_at_ms',pa.int64()),('outcome_kind_draw',pa.bool_()),('engine_eval_cp_disconnected',pa.int32())])
        rows=[]
        for i,month in enumerate(months):
            row={'game_id':f'G{i:07d}','month':month,'api_status':'timeout','api_winner':None if i%3==0 else 'white',
                 'api_created_at_ms':1700000000000+i,'outcome_kind_draw':i%3==0,'engine_eval_cp_disconnected':0}
            p=self.root/f'panels/{month}/data.parquet';p.parent.mkdir(parents=True,exist_ok=True)
            pq.write_table(pa.Table.from_pylist([row],schema=schema),p);paths.append(p)
            rows.append({'id':row['game_id'],'source':'pool','status':'timeout','winner':row['api_winner'],'createdAt':row['api_created_at_ms']})
        expected={'rows':n,'kind_draws':sum(i%3==0 for i in range(n)),'fair_rows':n}
        return {'paths':paths,'months':months,'expected':expected},rows
    def test_full24_global_match_partial_and_exact_residual_ids(self):
        fixture,rows=self.fixture()
        # Later archive name deliberately differs from the target game months.
        api=self.root/'api_backup_2026'
        dump(api/'all.ndjson.zst',rows[:-2]+[rows[0],{**rows[1],'source':'friend'}])
        run=self.root/'run'
        report=m.pipeline(self.root,[api],run,workers=2,threads=2,memory='512MB',fixture=fixture)
        self.assertEqual(report['status'],'GAME_SOURCE_24M_PARTIAL',report['errors'])
        self.assertEqual(report['unresolved_games'],3)
        table=pq.ParquetFile(run/'source_by_game_id_24m.parquet').read().to_pylist()
        self.assertEqual(len(table),24)
        byid={r['game_id']:r for r in table}
        self.assertEqual(byid['G0000001']['source_status'],'conflict')
        self.assertIsNone(byid['G0000001']['source'])
        self.assertEqual(byid['G0000000']['evidence_rows'],2)
        missing=pq.ParquetFile(run/'unresolved_game_ids_24m.parquet').read()['game_id'].to_pylist()
        self.assertEqual(set(missing),{'G0000001','G0000022','G0000023'})
        rerun=m.pipeline(self.root,[api],run,workers=2,threads=2,memory='512MB',fixture=fixture,strict=True)
        self.assertEqual(rerun['coverage'],report['coverage'])
        self.assertEqual(rerun['status'],'GAME_SOURCE_24M_PARTIAL',rerun['errors'])
        with zipfile.ZipFile(next(run.glob('*.zip'))) as z:
            self.assertNotIn(b'G0000001',z.read(run.name+'/SUMMARY.json'))
            self.assertFalse(any('source_by_game_id' in n for n in z.namelist()))
    def test_complete24_then_source_metadata_conflict(self):
        fixture,rows=self.fixture()
        api=self.root/'api'
        dump(api/'all.jsonl',rows)
        report=m.pipeline(self.root,[api],self.root/'run',workers=2,threads=2,memory='512MB',fixture=fixture)
        self.assertEqual(report['status'],'GAME_SOURCE_24M_COMPLETE',report['errors'])
        dump(api/'other.jsonl',[{**rows[0],'status':'resign'},{**rows[1],'createdAt':1700000000500},
                               {**rows[2],'winner':'black'}])
        report=m.pipeline(self.root,[api],self.root/'run2',workers=2,threads=2,memory='512MB',fixture=fixture)
        self.assertEqual(report['unresolved_games'],3)
        table=pq.ParquetFile(self.root/'run2/unresolved_game_ids_24m.parquet').read().to_pylist()
        self.assertTrue(all(r['source_status']=='inconsistent_metadata' for r in table))
    def test_bad_baseline_and_truncated_input_fail_closed(self):
        fixture,rows=self.fixture(2)
        api=self.root/'api';p=dump(api/'bad.ndjson.zst',rows)
        p.write_bytes(p.read_bytes()[:-1]);old=time.time()-300;os.utime(p,(old,old))
        report=m.pipeline(self.root,[api],self.root/'run',workers=1,threads=1,memory='512MB',fixture=fixture)
        self.assertEqual(report['status'],'GAME_SOURCE_24M_PARTIAL')
        self.assertEqual(report['unresolved_games'],2)
        self.assertTrue(report['errors'])
        fixture['expected']['rows']=3
        report=m.pipeline(self.root,[api],self.root/'run2',workers=1,threads=1,memory='512MB',fixture=fixture)
        self.assertEqual(report['status'],'GAME_SOURCE_24M_BLOCKED')
    def test_real_bash_launcher_and_certificate_failure(self):
        fixture,rows=self.fixture()
        stage=self.root/'derived/replication/analysis_panel_24m_sf100k'
        manifests=stage/'_manifests';manifests.mkdir(parents=True)
        panel_paths=[];month_rows=[]
        for month,original in zip(m.MONTHS,fixture['paths']):
            p=stage/f'month={month}/analysis_panel.parquet';p.parent.mkdir()
            shutil.copyfile(original,p);panel_paths.append(p)
            month_rows.append({'month':month,'output_size_bytes':p.stat().st_size,'output_sha256':m.digest(p)})
        (manifests/'analysis_panel_paths.txt').write_text(''.join(str(p)+'\n' for p in panel_paths))
        import csv
        with (manifests/'month_status.csv').open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(month_rows[0]));writer.writeheader();writer.writerows(month_rows)
        cert={'status':'STAGE07_24M_CERTIFIED_OK','script_sha256':m.PRODUCER_SHA,'global_qa':fixture['expected']}
        (stage/'_SUCCESS.json').write_text(json.dumps(cert))
        dump(self.root/'output/api_backup/all.ndjson',rows)
        bundle=self.root/'bundle';bundle.mkdir()
        original_dir=Path(m.__file__).parent
        for name in ('recovery_support.py','RUN_GAME_SOURCE_24M.command'):
            shutil.copyfile(original_dir/name,bundle/name)
        code=Path(m.__file__).read_text()
        code=code.replace("EXPECTED = {'rows':47587020, 'kind_draws':669503, 'fair_rows':17328130}",
                          'EXPECTED = '+repr(fixture['expected']))
        code=code.replace(m.SUCCESS_SHA,m.digest(stage/'_SUCCESS.json'))
        (bundle/'build_game_source.py').write_text(code)
        files=sorted(bundle.iterdir())
        (bundle/'PACKAGE_MANIFEST.sha256').write_text(''.join(m.digest(p)+'  '+p.name+'\n' for p in files))
        env={**os.environ,'GAME_SOURCE_PROJECT_ROOT':str(self.root),'GAME_SOURCE_PYTHON':sys.executable,
             'GAME_SOURCE_WORKERS':'2','GAME_SOURCE_THREADS':'2','GAME_SOURCE_MEMORY':'512MB'}
        env.pop('GAME_SOURCE_RUN_DIR',None)
        result=subprocess.run(['/bin/bash',str(bundle/'RUN_GAME_SOURCE_24M.command'),'--desktop-root',str(self.root/'desktop')],
                              env=env,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('GAME_SOURCE_24M_COMPLETE',result.stdout)
        (stage/'_SUCCESS.json').write_text('{}')
        bad=subprocess.run(['/bin/bash',str(bundle/'RUN_GAME_SOURCE_24M.command'),'--desktop-root',str(self.root/'desktop')],
                           env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(bad.returncode,1,bad.stdout+bad.stderr)
        self.assertIn('certificate hash mismatch',bad.stdout)
        self.assertIn('UPLOAD:',bad.stdout)


if __name__=='__main__':unittest.main(verbosity=2)
