"""Exercise the actual other-year SQL and certify checkpoint compatibility."""
import ast
import hashlib
import inspect
import json
import unittest
from pathlib import Path

import duckdb
import pandas as pd
import opportunities
import run_local


class SqlRepairTests(unittest.TestCase):
    def test_other_year_labels_execute_with_duckdb(self):
        records = []
        for chooser, month, grants in [
            (1, 0, [0, 0, 0, 0]), (1, 12, [1, 1, 1, 1]),
            (2, 11, [0, 0, 1, 1]), (2, 23, [0, 0, 0, 0]),
            (3, 0, [1, 1, 1]), (3, 12, [0, 0]), (4, 12, [1]),
        ]:
            records.extend(dict(chooser=chooser, month_code=month, y=y, board=0)
                           for y in grants)
        # Lost-position grants must not enter competitive history rates.
        records.append(dict(chooser=1, month_code=0, y=1, board=-300))
        fixture = pd.DataFrame(records)
        with duckdb.connect() as c:
            c.register('fixture', fixture)
            c.execute('CREATE VIEW p AS SELECT * FROM fixture')
            calls = sorted((n for n in ast.walk(ast.parse(inspect.getsource(opportunities.prepare)))
                            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr == 'execute' and n.args
                            and isinstance(n.args[0], ast.Constant)
                            and isinstance(n.args[0].value, str)), key=lambda n: n.lineno)
            statements = [n.args[0].value for n in calls if n.args[0].value.startswith((
                'CREATE TEMP TABLE history ', 'CREATE TEMP TABLE medians ', 'CREATE VIEW labelled '))]
            self.assertEqual(len(statements), 3)
            for sql in statements:
                c.execute(sql)
            self.assertEqual(c.execute('SELECT * FROM medians ORDER BY "year"').fetchall(),
                             [(0, 0.25, 2), (1, 0.5, 2)])
            labels = c.execute('SELECT DISTINCT chooser,month_code,intensity FROM labelled ORDER BY 1,2').fetchall()
            self.assertEqual(labels, [(1, 0, 1), (1, 12, 0), (2, 11, 0), (2, 23, 1),
                                      (3, 0, 2), (3, 12, 2), (4, 12, 2)])
            self.assertEqual(c.execute('SELECT count(*) FROM labelled').fetchone()[0], len(records))

    def test_same_input_configuration_keeps_existing_run_key(self):
        args = run_local.parser().parse_args([])
        cfg = run_local.configuration(args, 'actual-repair-package-hash')
        self.assertEqual(cfg['package_manifest_sha256'], run_local.CACHE_LINEAGE_MANIFEST_SHA256)
        self.assertEqual(run_local.key(cfg)[:12], '4df83f1178f3')
        args.shards = 512
        self.assertNotEqual(run_local.key(run_local.configuration(args, 'actual-repair-package-hash'))[:12],
                            '4df83f1178f3')


if __name__ == '__main__':
    unittest.main()
