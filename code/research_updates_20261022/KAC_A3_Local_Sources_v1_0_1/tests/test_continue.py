import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import continue_a3 as a


def fixture(project):
    records=[{'month':m,'path':str(project/'old'/m),'sha256':'a'*64,'bytes':100,
              'receipt_sha256':'b'*64} for m in a.old.MONTHS]
    contract=a.old.digest({'package':a.OLD_PACKAGE,'inputs':records,'policy':a.old.POLICY})
    base=project/'derived/replication/kac_a3_readiness_v100_PRIVATE'/contract[:20]
    a.old.write_json(base/'INPUTS.json',{'records':records,'contract':contract,'author_policy':a.old.POLICY,
       'arena_build_sha256':a.OLD_BUILD,'arena_contract':a.old.EXPECTED_CONTRACT})
    for rec in records:
        m=rec['month'];folder=base/('month='+m);folder.mkdir()
        rows=[{'game_id':m+str(i),'month':m,'chooser':ch,'opponent':99,'tournament_id':m+tr,
               'eval_cp':ev,'ply':12,'speed':'blitz'}
              for i,(ch,tr,ev) in enumerate([(1,'A',0),(1,'A',500),(1,'B',-500),
                                             (2,'C',-500),(2,'C',-500),(3,'D',-200)])]
        p=folder/'target_keys_PRIVATE.parquet';pq.write_table(pa.Table.from_pylist(rows),p)
        a.old.write_json(folder/'DONE.json',{'key':a.old.digest({'record':rec,'contract':contract}),
           'projection_sha256':a.old.sha(p),'summary':{'input_sha256':rec['sha256'],'kept_rows':6}})
    return base


class ContinuationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_cached_lineage_and_tampering(self):
        base=fixture(self.p);found,inputs=a.find_cached_inputs(self.p);self.assertEqual(found,base)
        rec=inputs['records'][0];folder=base/('month='+rec['month'])
        self.assertEqual(a.verify_projection((folder,rec,inputs['contract']))[1]['kept_rows'],6)
        with (folder/'target_keys_PRIVATE.parquet').open('ab') as f:f.write(b'tampered')
        with self.assertRaisesRegex(RuntimeError,'Completed projection changed'):
            a.verify_projection((folder,rec,inputs['contract']))
    def test_every_root_enumerated_and_schema_only_inspection(self):
        for root in ['derived','output','raw']:(self.p/root).mkdir()
        for i in range(9):
            path=self.p/'derived'/('part-'+str(i)+'.parquet')
            pq.write_table(pa.table({'irrelevant':[1]}),path)
        target=self.p/'output'/'tournament_records.parquet'
        pq.write_table(pa.table({'berserk':[True],'tournament_id':['privateID']}),target)
        groups,scopes=a.enumerate_assets(self.p)
        self.assertEqual(sum(s['candidate_files'] for s in scopes),10)
        g=next(g for g in groups if g['family']=='output/tournament_records.parquet')
        _,p,s=g['representatives'][0]
        r=a.inspect_representative((g['family'],g['kind'],p,s))
        self.assertEqual(json.loads(r['matched_fields_json'])['berserk'],['berserk'])
        self.assertNotIn('privateID',json.dumps(r))
        shards=next(g for g in groups if g['family']=='derived/part-*.parquet')
        self.assertEqual(len(shards['representatives']),3)
    def test_project_alias_preserves_families_and_deduplicates_roots(self):
        project=self.p/'physical_project'
        for name in ['derived','output','raw']:(project/name).mkdir(parents=True)
        alias=self.p/'project_alias';alias.symlink_to(project.resolve(),target_is_directory=True)
        external=self.p/'external_sources';external.mkdir()
        external_alias=self.p/'external_alias'
        external_alias.symlink_to(external.resolve(),target_is_directory=True)
        for path in [project/'derived/part-0.parquet',project/'output/tournament_records.parquet',
                     external/'tournament_records.parquet']:
            pq.write_table(pa.table({'berserk':[True]}),path)
        direct_groups,direct_scopes=a.enumerate_assets(project,[external])
        alias_groups,alias_scopes=a.enumerate_assets(alias,
            [alias/'derived',external_alias,external,project/'raw'])
        self.assertEqual(alias_groups,direct_groups)
        self.assertEqual(alias_scopes,direct_scopes)
        self.assertEqual(len(alias_scopes),4)
        self.assertEqual(sum(s['candidate_files'] for s in alias_scopes),3)
        self.assertEqual({g['family'] for g in alias_groups},
            {'derived/part-*.parquet','output/tournament_records.parquet',
             a.family_key(str(external.resolve()/'tournament_records.parquet'))})
    def test_nested_fields_json_privacy_and_bounded_pgn(self):
        s=pa.schema([('players',pa.struct([('white',pa.struct([('berserk',pa.bool_())]))]))])
        self.assertIn('players.white.berserk',a.field_paths(s))
        keys=a.json_paths({'players':{'white':{'user':{'id':'a_private_name'},'berserk':True}},
                           'a_private_name':{'score':5}})
        self.assertNotIn('a_private_name',json.dumps(keys))
        self.assertIn('players.white.berserk',keys)
        p=self.p/'game.pgn';p.write_text('[Event "Rated tournament https://lichess.org/tournament/Ab12Cd34"]\n[WhiteTitle "GM"]\n'+('x'*300000))
        r=a.inspect_representative(('raw/game.pgn','pgn',str(p),a.old.signature(p)))
        self.assertEqual(r['prefix_bytes_read'],a.PREFIX_BYTES)
        self.assertNotIn('Ab12Cd34',json.dumps(r))
        self.assertEqual(json.loads(r['matched_fields_json'])['title'],['WhiteTitle'])
        self.assertEqual(a.selected_fields(['sf100k_score_value_side_to_move'])['tournament_scoring'],[])
    def test_full_reuse_pipeline_and_state_support(self):
        fixture(self.p)
        args=argparse.Namespace(project=str(self.p),workers=2,extra_root=[],report_dir=str(self.p/'portable'))
        with patch.object(a,'REVIEWED_ROWS',144),patch.object(a,'verify_package',return_value='synthetic'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(a.run(args),0)
        z=next((self.p/'portable').glob('*.zip'))
        with zipfile.ZipFile(z) as f:
            self.assertFalse(any('PRIVATE.parquet' in n for n in f.namelist()))
            s=json.loads(f.read(next(n for n in f.namelist() if n.endswith('/SUMMARY.json'))))
        comp=next(r for r in s['support'] if r['sample']=='competitive_after_ply10')
        self.assertEqual((comp['opportunities'],comp['repeat_cells'],comp['opportunities_in_repeat_cells']),(48,24,48))
        losing=next(r for r in s['support'] if r['sample']=='losing_after_ply10')
        self.assertEqual((losing['opportunities'],losing['repeat_cells'],losing['opportunities_in_repeat_cells']),(72,24,48))
        self.assertEqual(s['authenticated_cached_months'],24)
        self.assertFalse(s['prior_audit_rebuilt'])
        self.assertEqual(s['API_requests'],0)


if __name__=='__main__':unittest.main(verbosity=2)
