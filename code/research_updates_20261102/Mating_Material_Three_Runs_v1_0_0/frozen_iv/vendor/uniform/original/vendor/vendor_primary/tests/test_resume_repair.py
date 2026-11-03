"""Exercise the actual failing SQL path and the original production cache key."""
import ast
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_primary import fixture
from primary_common import *
import primary_inputs as pi
import primary_report as pr
import run_primary as runner


class ResumeRepair(unittest.TestCase):
    def test_default_run_key_is_the_uploaded_v100_run(self):
        a=SimpleNamespace(project=Path('/Volumes/XT_Pro/lichess_kindness'),
            r12_root=Path('/Volumes/XT_Pro/lichess_kindness/derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3'),
            r9_root=None,comparison_root=None)
        cfg=runner.configuration(a)
        self.assertEqual(key(cfg),'cf6b3d8b4d65b13868403b5ef7b45a2d236457158db9310bebd26038e16cde5b')
        self.assertEqual(cfg['version'],'1.0.0')
        self.assertEqual(VERSION,'1.0.3')
        self.assertEqual(sha(PACKAGE/'evidence/v100_PACKAGE_MANIFEST.sha256'),CACHE_LINEAGE_MANIFEST_SHA256)

    def run_wider(self,root,corrupt=False):
        source,scores,d,_=fixture(root,40)
        d['spaced90'][::4]=True;d['spaced30'][::2]=True;d['first_recipient'][0]=True
        pq.write_table(pa.table(d),source)
        primary=root/'primary.parquet';tab=pa.table(d).filter(pa.array(d['spaced90']))
        if corrupt:
            y=tab.column('y').to_numpy().copy();y[0]=not y[0]
            tab=tab.set_column(tab.schema.get_field_index('y'),'y',pa.array(y))
        pq.write_table(tab,primary)
        (root/'PRIVATE/wider').mkdir(parents=True);(root/'report').mkdir()
        b=dict(primary=str(primary),all_scores=[str(scores)],bound={})
        a=SimpleNamespace(memory_gb=11)
        with patch.object(pi,'build_selection',return_value=source), \
             patch.object(pi,'rebuild_wider_features',return_value=(source,source)), \
             patch.object(pi.cutoffs,'add_volume',return_value=source), \
             patch.object(pi,'environment',return_value=source), \
             patch.object(pi,'EXPECTED_N',10):
            out=pi.wider(a,root,'unchanged-cache-key',b)
            before={str(p):(sha(p),p.stat().st_mtime_ns) for p in (source,primary,scores,Path(out[1]))}
            out_again=pi.wider(a,root,'unchanged-cache-key',b)
            self.assertEqual(out,out_again)
            for p,(digest,mtime) in before.items():
                self.assertEqual(sha(p),digest)
                self.assertEqual(Path(p).stat().st_mtime_ns,mtime)
        return out

    def test_actual_wider_final_queries_complete_and_resume_without_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source,scores=self.run_wider(root)
            got=load(root/'report/wider_sample_counts.json')
            self.assertEqual(got['all_exposures'],40)
            self.assertEqual(got['primary90'],10)
            self.assertEqual(got['spacing30'],20)
            self.assertEqual(got['first_observed'],1)
            self.assertTrue(got['primary_features_reproduced'])
            self.assertEqual(load(root/'PRIVATE/WIDER.json'),dict(source=str(source),scores=str(scores)))
            self.assertEqual(pq.read_table(scores).column('row_id').to_pylist(),list(range(40)))

    def test_primary_feature_bridge_still_rejects_changed_outcome(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,'identity/history/outcome mismatch'):
                self.run_wider(Path(td),corrupt=True)

    def test_top_level_sql_relation_names_parse(self):
        import duckdb
        con=duckdb.connect()
        checked=0
        try:
            for path in PACKAGE.glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node,ast.Constant) and isinstance(node.value,str):
                        for name in re.findall(r'CREATE\s+(?:TEMP\s+)?(?:VIEW|TABLE)\s+(\w+)\s+AS',node.value,re.I):
                            con.extract_statements('CREATE VIEW '+name+' AS SELECT 1')
                            checked+=1
            self.assertGreater(checked,20)
        finally:con.close()

    def test_report_removes_AR_fields_but_preserves_wald_and_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fit=root/'PRIVATE/fits/primary_r9__X0';fit.mkdir(parents=True)
            (root/'report').mkdir()
            data=dict(estimates=[dict(estimator='2SLS',iv_coefficient_pp=.363,
                iv_ci_low_pp=.174,iv_ci_high_pp=.552,AR95_intervals_pp=[[.173,.553]],AR_method='unused')])
            save(fit/'result.json',data);save(fit/'_DONE.json',{})
            save(root/'PRIVATE/PRIMARY_PLAN.json',[dict(output=str(fit),name='primary_r9__X0',engine='r9',conf='fixture')])
            digest=sha(fit/'result.json')
            with patch.object(pr.frozen.r9_inputs,'stage_file'):
                self.assertEqual(pr.model_tables(root),(1,1))
            import csv
            with (root/'report/primary_iv.csv').open() as handle:
                row=next(csv.DictReader(handle))
            self.assertFalse(any(k.startswith('AR') for k in row))
            self.assertEqual(float(row['iv_ci_low_pp']),.174)
            self.assertEqual(float(row['iv_ci_high_pp']),.552)
            self.assertEqual(sha(fit/'result.json'),digest)


if __name__=='__main__':unittest.main()
