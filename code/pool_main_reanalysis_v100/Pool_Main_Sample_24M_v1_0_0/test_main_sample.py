"""Offline fixtures exercising the sample decision, joins, accounting and resume."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

import build_main_sample as app
from audit_io import (sha, canonical_sha, json_bytes, read_json, write_json,
                      pq_sql, stage, verify_stage, report_bytes, signature)
from sample_rules import CANDIDATE, NONADJACENT, MISSING, AMBIGUOUS, SAMPLES


def fixture(root):
    panel_root = root/'original'; panel_root.mkdir()
    join_root = root/'join'; join_root.mkdir()
    source_root = root/'source'; source_root.mkdir()
    # Includes repeat choosers across months, all four predecessor statuses,
    # non-pool sources, exact centipawn boundaries and a two-ply observation.
    values = [
        ('A0000001','2024-01','pool',NONADJACENT,-100,True,1,2),
        ('A0000002','2024-01','pool',CANDIDATE,300,False,1,25),
        ('A0000003','2024-01','pool',MISSING,100,True,2,10),
        ('A0000004','2024-01','pool',AMBIGUOUS,-300,False,3,1),
        ('A0000005','2024-01','friend',NONADJACENT,-301,True,4,0),
        ('A0000006','2024-01','pool',NONADJACENT,-101,False,2,12),
        ('B0000001','2024-02','pool',NONADJACENT,101,False,1,2),
        ('B0000002','2024-02','pool',NONADJACENT,299,True,4,11),
        ('B0000003','2024-02','pool',MISSING,0,False,5,3),
        ('B0000004','2024-02','pool',CANDIDATE,-300,True,2,20),
        ('B0000005','2024-02','arena',NONADJACENT,0,False,6,None),
        ('B0000006','2024-02','pool',AMBIGUOUS,301,True,3,2),
    ]
    panel=[]; joined=[]; sources=[]; previous={}; source_counts={}; membership={}
    for i,(gid,month,source,status,cp,kind,chooser,plies) in enumerate(values):
        when = int(dt.datetime.fromisoformat(month+'-05T12:00:00+00:00').timestamp()*1000)+i*1000
        row = {'game_id':gid,'month':month,'chooser_user_id':chooser,'disconnected_user_id':chooser+100,
               'utc_ms':when,'api_status':'timeout','outcome_kind_draw':kind,
               'engine_eval_cp_disconnected':cp,'chooser_elo':1000+i*50,'disconnected_elo':1100+i*25,
               'chooser_draw_payoff_v2':i/10.,'ply_count':plies,
               'api_speed':'blitz' if i%2 else 'rapid','disconnected_clock_last_obs_s':float(i),
               'preserved_engine_nodes':100000,'preserved_text':"extra 'value', "+gid,
               'preserved_nullable':None if i%2 else i,'preserved_float':3.141592653589793+i}
        panel.append(row)
        raw = status==CANDIDATE or (status==AMBIGUOUS and month=='2024-01')
        clean = True if status==CANDIDATE else False if status==NONADJACENT else None
        joined.append({'game_id':gid,'month':month,'source':source,'source_provenance':'fixture:'+gid,
                       'p1':chooser,'p2':chooser+100,'focal_start_ms':when,'focal_mapping_ok':True,
                       'previous_classification_status':status,'previous_game_id':'Z'+gid[1:] if raw else None,
                       'mutual_previous_same_pair':clean,'mutual_previous_observed':raw,
                       'previous_start_order_ambiguous':status==AMBIGUOUS,
                       # These deliberately disagree across otherwise identical cases.
                       'next_classification_status':CANDIDATE if i%2 else MISSING,
                       'previous_start_gap_ms':999999999 if status==CANDIDATE else None})
        sources.append({k:joined[-1][k] for k in ('game_id','month','source','source_provenance')})
        key=(month,source,status)
        previous[key]=previous.get(key,0)+1
        key=(month,source)
        count=source_counts.setdefault(key,dict(month=month,source=source,rows=0,kind_draws=0,fair_rows=0,fair_kind_draws=0))
        count['rows']+=1; count['kind_draws']+=int(kind)
        count['fair_rows']+=int(cp>=-100); count['fair_kind_draws']+=int(kind and cp>=-100)
        member={'original':True,'pool':source=='pool','main_pool_nonadjacent':source=='pool' and status==NONADJACENT,
                'pool_restore_missing_previous':source=='pool' and status in (NONADJACENT,MISSING)}
        for sample,eligible in member.items():
            membership.setdefault(month,{k:0 for k,_ in SAMPLES})[sample]+=int(eligible)
    entries=[]
    def save(path,rows,kind,exact=True):
        table=pa.Table.from_pylist(rows); pq.write_table(table,path)
        entry=dict(path=str(path),sha256=sha(path),size_bytes=path.stat().st_size,rows=len(rows),kind=kind,
                   schema={f.name:app.sql_type(f.type) for f in table.schema},exact_schema=exact)
        entries.append(entry)
        return entry
    jp=join_root/'joined.parquet'; save(jp,joined,'join',False)
    sp=source_root/'source.parquet'; save(sp,sources,'source')
    prev=[dict(month=k[0],source=k[1],classification_status=k[2],rows=n) for k,n in previous.items()]
    months=[]
    for month in sorted(membership):
        pp=panel_root/(month+'.parquet'); save(pp,[r for r in panel if r['month']==month],'panel')['month']=month
        months.append(dict(month=month,panel_path=str(pp),expected_counts=membership[month],
                           source_counts=[r for r in source_counts.values() if r['month']==month],
                           statuses=[r for r in prev if r['month']==month]))
    plan=dict(entries=entries,metadata=[],source_path=str(sp),join_paths=[str(jp)],source_root=str(source_root),
              join_root=str(join_root),panel_root=str(panel_root),months=months,previous=prev,
              source_counts=list(source_counts.values()),
              expected_counts={s:sum(m[s] for m in membership.values()) for s,_ in SAMPLES},evidence_sha256={'fixture':'offline'})
    return plan,panel,joined


def rewrite(plan,path,rows):
    path=Path(path)
    table=pa.Table.from_pylist(rows,schema=pq.ParquetFile(path).schema_arrow)
    pq.write_table(table,path)
    entry=next(r for r in plan['entries'] if r['path']==str(path))
    entry.update(sha256=sha(path),size_bytes=path.stat().st_size,rows=len(rows))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pool_main_fixture_')
        self.root=Path(self.temp.name); self.plan,self.panel,self.joined=fixture(self.root)
        self.out=self.root/'built'; self.reports=self.root/'reports'

    def tearDown(self): self.temp.cleanup()

    def run_fixture(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return app.run(self.plan,self.out,self.reports,workers=2,threads=2,memory='256MB',check_space=False)

    def connection(self):
        con=duckdb.connect()
        con.execute('SET threads=2'); con.execute("SET memory_limit='256MB'")
        con.execute('CREATE VIEW j AS SELECT * FROM '+pq_sql(self.plan['join_paths']))
        con.execute('CREATE VIEW s AS SELECT * FROM '+pq_sql([self.plan['source_path']]))
        self.addCleanup(con.close)
        return con

    def test_full_run_preserves_schema_and_every_retained_value(self):
        result=self.run_fixture()
        self.assertEqual(result['status'],'POOL_MAIN_SAMPLE_24M_CERTIFIED_OK')
        self.assertFalse(result['literal_immediate_rematches_certified'])
        got=[]
        for month in self.plan['months']:
            path=self.out/'panel'/('month='+month['month'])/'analysis_panel.parquet'
            written=pq.ParquetFile(path).read()
            self.assertEqual(written.schema,pq.ParquetFile(month['panel_path']).schema_arrow)
            got+=written.to_pylist()
        expected=[r for r in self.panel if r['game_id'] in {'A0000001','A0000006','B0000001','B0000002'}]
        self.assertEqual(sorted(got,key=lambda r:r['game_id']),sorted(expected,key=lambda r:r['game_id']))

    def test_global_counts_deduplicate_choosers_and_pool_rates(self):
        result=self.run_fixture(); stats={r['sample']:r for r in result['sample_counts']}
        expected={'original':(12,6,8,4,6),'pool':(10,5,7,4,5),
                  'main_pool_nonadjacent':(4,2,3,2,3),'pool_restore_missing_previous':(6,3,5,3,4)}
        for sample,values in expected.items():
            self.assertEqual(tuple(stats[sample][k] for k in ['rows','kind_draws','fair_rows','fair_kind_draws','choosers']),values)
        main=stats['main_pool_nonadjacent']
        self.assertEqual(main['fair_choosers'],2)
        self.assertAlmostEqual(main['fair_kindness_pct'],200/3)
        self.assertEqual(sum(r['choosers'] for r in result['monthly_counts'] if r['sample']=='main_pool_nonadjacent'),4)
        self.assertEqual(main['chooser_rating_mean'],1225)
        # Check a denominator that differs across months; never average monthly fair rates.
        self.assertNotEqual(main['fair_kindness_pct'],sum(r['fair_kindness_pct'] for r in result['monthly_counts'] if r['sample']=='main_pool_nonadjacent')/2)

    def test_report_is_aggregate_and_checksummed(self):
        result=self.run_fixture()
        data=report_bytes(Path(result['report_zip']),result['report_zip_sha256'])
        self.assertIn('MAIN_SAMPLE_REPORT.json',data)
        self.assertIn('SAMPLE_COUNTS.parquet',data)
        for name,content in data.items():
            if name.endswith(('.json','.md')):
                self.assertNotIn(b'A0000001',content)
                self.assertNotIn(b'fixture:A',content)
        self.assertEqual(read_json(self.out/'_SUCCESS.json')['contract_sha256'],sha(self.out/'RUN_CONTRACT.json'))

    def test_unknown_history_and_ties_are_not_recoded_nonadjacent(self):
        result=self.run_fixture(); got=[]
        for p in (self.out/'eligibility/parts').rglob('*.parquet'):
            got+=pq.ParquetFile(p).read().to_pylist()
        byid={r['game_id']:r for r in got}
        for gid in ('A0000003','B0000003','A0000004','B0000006'):
            self.assertIsNone(byid[gid]['mutual_previous_same_pair'])
            self.assertFalse(byid[gid]['eligible_main'])
        self.assertTrue(byid['A0000003']['eligible_pool_restore_missing_previous'])
        self.assertFalse(byid['A0000004']['eligible_pool_restore_missing_previous'])
        self.assertEqual(result['eligibility_qa']['rows'],12)

    def test_future_repairing_and_candidate_start_gap_do_not_determine_membership(self):
        con=self.connection()
        from sample_rules import mask_query
        before=con.execute(mask_query()+' ORDER BY game_id').fetchall()
        for row in self.joined:
            row['next_classification_status']=NONADJACENT
            row['previous_start_gap_ms']=0
        rewrite(self.plan,self.plan['join_paths'][0],self.joined)
        after=con.execute(mask_query()+' ORDER BY game_id').fetchall()
        self.assertEqual(before,after)
        mainids=con.execute('SELECT game_id FROM ('+mask_query()+') WHERE eligible_main').fetchall()
        self.assertNotIn(('A0000002',),mainids)

    def test_duplicate_join_id_rejected(self):
        self.joined[1]['game_id']=self.joined[0]['game_id']
        rewrite(self.plan,self.plan['join_paths'][0],self.joined)
        with self.assertRaisesRegex(ValueError,'uniqueness'):
            app.mask_validation(self.connection(),self.plan)

    def test_per_game_source_mismatch_rejected_even_with_same_source_totals(self):
        path=self.plan['source_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['source'],rows[4]['source']=rows[4]['source'],rows[0]['source']
        rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'per-game source'):
            app.mask_validation(self.connection(),self.plan)

    def test_source_id_set_mismatch_rejected_at_same_row_count(self):
        path=self.plan['source_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['game_id']='X0000001'; rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'per-game source'):
            app.mask_validation(self.connection(),self.plan)

    def test_source_provenance_mismatch_rejected(self):
        path=self.plan['source_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['source_provenance']='different'; rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'per-game source'):
            app.mask_validation(self.connection(),self.plan)

    def test_false_in_place_of_unknown_rejected(self):
        self.joined[2]['mutual_previous_same_pair']=False
        rewrite(self.plan,self.plan['join_paths'][0],self.joined)
        with self.assertRaisesRegex(ValueError,'invalid joined'):
            app.mask_validation(self.connection(),self.plan)

    def test_role_mismatch_rejected(self):
        path=self.plan['months'][0]['panel_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['chooser_user_id']=999; rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'role, or start-time mismatch'): self.run_fixture()

    def test_start_mismatch_rejected(self):
        path=self.plan['months'][0]['panel_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['utc_ms']+=1; rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'start-time mismatch'): self.run_fixture()

    def test_null_kind_or_evaluation_rejected(self):
        path=self.plan['months'][0]['panel_path']; rows=pq.ParquetFile(path).read().to_pylist()
        rows[0]['outcome_kind_draw']=None; rewrite(self.plan,path,rows)
        with self.assertRaisesRegex(ValueError,'invalid analysis'): self.run_fixture()

    def test_input_bytes_changed_after_receipt_rejected(self):
        p=Path(self.plan['months'][0]['panel_path'])
        with p.open('ab') as f: f.write(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'): self.run_fixture()

    def test_monthly_restart_reuses_completed_stage(self):
        real=app.build_month
        def interrupt(con,m,*args):
            if m['month']=='2024-02': raise KeyboardInterrupt()
            return real(con,m,*args)
        with patch.object(app,'build_month',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.run_fixture()
        p=self.out/'panel/month=2024-01/analysis_panel.parquet'; before=signature(p)
        self.assertFalse((self.out/'_SUCCESS.json').exists())
        self.run_fixture()
        self.assertEqual(signature(p),before)

    def test_completed_run_revalidates_output_and_keeps_original_files(self):
        self.run_fixture(); original={r['path']:sha(r['path']) for r in self.plan['entries']}
        p=self.out/'panel/month=2024-01/analysis_panel.parquet'; before=signature(p)
        self.run_fixture(); self.assertEqual(signature(p),before)
        self.assertEqual(original,{r['path']:sha(r['path']) for r in self.plan['entries']})
        with p.open('ab') as f: f.write(b'corruption')
        with self.assertRaisesRegex(ValueError,'Completed stage file changed'): self.run_fixture()

    def test_unrecognized_output_preserved(self):
        self.out.mkdir(); sentinel=self.out/'keep.txt'; sentinel.write_text('keep')
        with self.assertRaisesRegex(ValueError,'Unrecognized existing output'): self.run_fixture()
        self.assertEqual(sentinel.read_text(),'keep')

    def test_completed_receipt_change_rejected(self):
        self.run_fixture(); p=self.out/'panel/month=2024-01/_DONE.json'
        row=read_json(p); row['info']['qa']['written_main_rows']=99; write_json(p,row)
        with self.assertRaisesRegex(ValueError,'receipt changed'): self.run_fixture()


class EvidenceCase(unittest.TestCase):
    def test_completed_source_union_covers_late_months(self):
        e=app.load_evidence(Path(__file__).resolve().parent)
        self.assertEqual(len(e['panel_schema']),157)
        for month,original,pool,main in [('2025-08',1930170,1791836,1695692),
                                         ('2025-09',1881564,1754805,1660248),
                                         ('2025-10',1999063,1860545,1761386)]:
            self.assertEqual(sum(r['rows'] for r in e['source']['source_counts'] if r['month']==month),original)
            self.assertEqual(sum(r['rows'] for r in e['source']['source_counts'] if r['month']==month and r['source']=='pool'),pool)
            self.assertEqual(sum(r['rows'] for r in e['previous'] if r['month']==month and r['source']=='pool' and r['classification_status']==NONADJACENT),main)

    def test_canonical_contract_digest_is_not_pretty_file_digest(self):
        import hashlib
        row={'algorithm':'fixture','buckets':128}
        self.assertNotEqual(canonical_sha(row),hashlib.sha256(json_bytes(row)).hexdigest())
        self.assertEqual(canonical_sha(row),canonical_sha(dict(reversed(list(row.items())))))


if __name__=='__main__': unittest.main()
