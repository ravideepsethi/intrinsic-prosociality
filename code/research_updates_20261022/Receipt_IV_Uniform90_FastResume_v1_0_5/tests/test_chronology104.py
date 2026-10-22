import unittest,tempfile,contextlib,io,shutil
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import fast_bootstrap as c
import fast_chronology_repair as repair
import fast_chronology_oracle as oracle
from test_chronology103 import raw_fixture,write

class Chronology104(unittest.TestCase):
    def setUp(self):self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()
    def tearDown(self):self.silence.__exit__(None,None,None)

    def test_full_raw_oracle_against_brute_force_with_duplicates_boundaries_and_absent_people(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);D=c.DAY;rng=np.random.default_rng(447)
            raw=[]
            for k in range(1200):
                w=int(rng.integers(1,17));b=int(rng.integers(1,17))
                raw.append(dict(game_id=f'G{k:07}',utc_ms=int(rng.integers(1,151))*D,
                                white_id=w,black_id=b))
            raw += [dict(game_id='boundary',utc_ms=70*D,white_id=1,black_id=2),
                    dict(game_id='upperone',utc_ms=100*D,white_id=1,black_id=3),
                    dict(game_id='uppertwo',utc_ms=100*D,white_id=1,black_id=4),
                    dict(game_id='upperone',utc_ms=100*D,white_id=1,black_id=3),
                    dict(game_id='bad00001',utc_ms=99*D,white_id=1,black_id=-1),
                    dict(game_id='bad00002',utc_ms=99*D,white_id=1,black_id=2**32),
                    dict(game_id='bad00003',utc_ms=0,white_id=1,black_id=2),
                    dict(game_id=None,utc_ms=99*D,white_id=2**32-1,black_id=1)]
            rawpath=root/'raw.parquet';pq.write_table(pa.Table.from_pylist(raw),rawpath)
            focal=[]
            for k in range(90):
                e=raw[int(rng.integers(0,1200))]
                focal.append(dict(game_id=e['game_id'],archive_start_ms=e['utc_ms'],recipient_id=e['white_id'],opponent_id=e['black_id']))
            focal += [dict(game_id='upperone',archive_start_ms=100*D,recipient_id=1,opponent_id=3)]*2
            focal += [dict(game_id='absent00',archive_start_ms=100*D,recipient_id=9999,opponent_id=2**32-1),
                      dict(game_id='old00000',archive_start_ms=D,recipient_id=1,opponent_id=2)]
            focalpath=root/'focal.parquet';pq.write_table(pa.Table.from_pylist(focal),focalpath)
            queries=[]
            for k,q in enumerate(focal):
                for role in (0,1):
                    queries.append(dict(sample_row=2**45+k,role=role,game_id=q['game_id'],archive_start_ms=q['archive_start_ms'],
                                        user_id=q['recipient_id' if role==0 else 'opponent_id']))
            querypath=root/'queries.parquet';pq.write_table(pa.Table.from_pylist(queries),querypath)
            latest=140*D
            valid=[r for r in raw if 0<r['utc_ms']<=latest and 0<=r['white_id']<2**32 and 0<=r['black_id']<2**32 and r['white_id']!=r['black_id']]
            matches={}
            for e in valid:
                for q in focal:
                    if e['game_id']==q['game_id'] and e['utc_ms']==q['archive_start_ms'] and sorted((e['white_id'],e['black_id']))==sorted((q['recipient_id'],q['opponent_id'])):
                        matches[e['game_id']]=matches.get(e['game_id'],0)+1
            expected=[]
            for q in queries:
                u=q['user_id'];t=q['archive_start_ms'];events=[e for e in valid if u in (e['white_id'],e['black_id'])]
                past=[e for e in events if e['utc_ms']<t];prev=max([e['utc_ms'] for e in past],default=None)
                prevs=[e for e in events if e['utc_ms']==prev]
                gids=[e['game_id'] for e in prevs if e['game_id'] is not None]
                expected.append(dict(sample_row=q['sample_row'],role=q['role'],prev_t=prev,
                    prev_count=len(prevs) if prevs else None,prev_gid=min(gids) if gids else None,
                    prev_opponent=min([e['black_id'] if e['white_id']==u else e['white_id'] for e in prevs],default=None),
                    focal_time_count=sum(e['utc_ms']==t for e in events),focal_matches=matches.get(q['game_id'],0),
                    pre_games_30d=sum(t-30*D<=e['utc_ms']<t for e in events) if q['role']==0 else 0))
            expectedpath=root/'expected.parquet';pq.write_table(pa.Table.from_pylist(expected),expectedpath)
            got=oracle.verify_raw(dict(path=str(rawpath),focal=str(focalpath),latest=latest),querypath,expectedpath,root/'verify',buckets=4)
            self.assertTrue(got['passed']);self.assertEqual(got['candidate_rows_checked'],len(queries));self.assertEqual(got['raw_rows_read'],len(raw))
            self.assertFalse((root/'verify/events').exists())

    def test_rejects_wrong_reconstruction_even_when_old_keys_are_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,_,job,_,_=raw_fixture(root);original=Path(job['output'])
            expected=pq.ParquetFile(original/'candidates.parquet').read();data=expected.to_pydict();data['sample_row'][0]=None
            def broken(tmp):
                pq.write_table(pa.table(data,schema=expected.schema),tmp/'candidates.parquet');shutil.copyfile(original/'pairs.parquet',tmp/'pairs.parquet')
            c.stage(root/'broken','scan',broken);job=dict(job,output=str(root/'broken'))
            sql=repair.candidate_sql()
            bad=sql.replace('coalesce(x.multiplicity,0)::BIGINT focal_time_count','(coalesce(x.multiplicity,0)+1)::BIGINT focal_time_count')
            with patch.object(repair,'candidate_sql',return_value=bad),self.assertRaisesRegex(RuntimeError,'raw-game verification rejected'):
                repair.validated_parts([job],root/'fix','parent',root/'report')
            self.assertFalse((root/'fix/broken/_DONE.json').exists())
            report=c.load(root/'report/chronology_repair104_failure.json')
            self.assertFalse(report['repair_accepted']);self.assertIn('raw-game verification rejected',report['error'])

    def test_missing_keys_and_changed_payload_repaired_with_unchanged_originals_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,_,job,_,_=raw_fixture(root);original=Path(job['output'])
            good=pq.ParquetFile(original/'candidates.parquet').read();data=good.to_pydict()
            data['sample_row'][0]=None;data['role'][0]=None;data['focal_time_count'][1]+=7
            def broken(tmp):
                pq.write_table(pa.table(data,schema=good.schema),tmp/'candidates.parquet');shutil.copyfile(original/'pairs.parquet',tmp/'pairs.parquet')
            c.stage(root/'broken','scan',broken);job=dict(job,output=str(root/'broken'))
            before={p:(repair.io.sig(p),c.sha(p)) for p in (root/'broken').iterdir() if p.is_file()}
            out=repair.validated_parts([job],root/'fix','parent',root/'report')[0]
            order=[('sample_row','ascending'),('role','ascending')]
            self.assertEqual(pq.ParquetFile(out/'candidates.parquet').read().sort_by(order).to_pydict(),good.sort_by(order).to_pydict())
            a=c.load(out/'repair_audit.json')['tables']['candidates']
            self.assertEqual(a['identified_original_rows_differing'],1);self.assertEqual(a['raw_verification']['candidate_rows_checked'],2)
            for p,record in before.items():self.assertEqual((repair.io.sig(p),c.sha(p)),record)
            with patch.object(oracle,'verify_raw',side_effect=AssertionError('Completed verification must resume')):
                self.assertEqual(repair.validated_parts([job],root/'fix','parent',root/'report'),[out])

    def test_unexpected_identified_old_key_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,_,job,_,_=raw_fixture(root);original=Path(job['output'])
            good=pq.ParquetFile(original/'candidates.parquet').read();data=good.to_pydict();data['sample_row'][0]=2**50
            def broken(tmp):
                pq.write_table(pa.table(data,schema=good.schema),tmp/'candidates.parquet');shutil.copyfile(original/'pairs.parquet',tmp/'pairs.parquet')
            c.stage(root/'broken','scan',broken)
            with self.assertRaisesRegex(RuntimeError,'outside the reconstructed'):
                repair.repair_scan(dict(job,output=str(root/'broken')),root/'fix','parent')

    def test_empty_events_produce_null_predecessor_and_zero_counts(self):
        schema=pa.schema([('user_id',pa.int64()),('utc_ms',pa.int64()),('game_id',pa.string()),('opponent_id',pa.int64())])
        q=pa.table(dict(sample_row=[1,2],role=[0,1],user_id=[7,8],archive_start_ms=[100,100],game_id=['a','b']))
        got=oracle.reference_rows(pa.Table.from_batches([],schema),q,pa.table(dict(game_id=pa.array([],type=pa.string()),matches=pa.array([],type=pa.int64()))))
        self.assertEqual(got['prev_t'].to_pylist(),[None,None]);self.assertEqual(got['pre_games_30d'].to_pylist(),[0,0])

    def test_complete_reconstruction_across_raw_batches_and_duplicate_focal_games(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);n=131100;rng=np.random.default_rng(104)
            w=rng.integers(1,257,n,dtype=np.int64);b=(w+rng.integers(1,256,n))%257+1
            b=np.where(b==w,258,b)
            times=rng.integers(1,151,n,dtype=np.int64)*c.DAY
            gids=np.array([f'g{k:07}' for k in range(n)],dtype=object)
            # Same focal game appears on opposite sides of the 65,536-row read boundary.
            w[-1]=w[0];b[-1]=b[0];times[-1]=times[0];gids[-1]=gids[0]
            raw=write(root/'raw.parquet',dict(game_id=gids,utc_ms=times,white_id=w,black_id=b))
            selected=np.r_[0,np.arange(n-3000,n-1)]
            query=write(root/'queries.parquet',dict(row_id=np.arange(len(selected))+2**43,
                game_id=gids[selected],recipient_id=w[selected],opponent_id=b[selected],
                archive_start_ms=times[selected],previous_frame=np.zeros(len(selected),bool)))
            prep,info=c.chron.previous.prepare_chronology(query,root/'prep','prep',.5)
            job=dict(path=str(raw),signature=repair.io.sig(raw),rows=n,file_index=711,latest=info['latest_start'],
                people=str(prep/'people.parquet'),pairs=str(prep/'pairs.parquet'),focal=str(prep/'focal.parquet'),roles=str(prep/'roles.parquet'),
                memory=.5,conf='scan',output=str(root/'original'))
            c.chron.chronology_job(job)
            good=pq.ParquetFile(root/'original/candidates.parquet').read()
            def broken(tmp):
                data=good.set_column(0,'sample_row',pa.nulls(len(good),type=good.schema.field('sample_row').type))
                pq.write_table(data,tmp/'candidates.parquet');shutil.copyfile(root/'original/pairs.parquet',tmp/'pairs.parquet')
            c.stage(root/'broken','scan',broken)
            out=repair.repair_scan(dict(job,output=str(root/'broken')),root/'repair','parent')
            audit=c.load(out/'repair_audit.json')['tables']['candidates']['raw_verification']
            self.assertTrue(audit['passed']);self.assertEqual(audit['candidate_rows_checked'],len(good))
            self.assertEqual(audit['raw_rows_read'],n)
            order=[('sample_row','ascending'),('role','ascending')]
            self.assertEqual(pq.ParquetFile(out/'candidates.parquet').read().sort_by(order).to_pydict(),good.sort_by(order).to_pydict())

if __name__=='__main__':unittest.main()
