import unittest,sys,tempfile,math
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'closeout'))
import duckdb
import test_closeout as fixtures
import mechanism as current
import reference_mechanism_v101 as previous
import bounded_io as bio
from overlap_audit import matched_moments,RTOL,ATOL
from closeout_common import signature,read

class RoundoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=duckdb.connect();self.db.execute('SET threads=1');self.db.execute("SET memory_limit='256MB'")
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def data(self,n0=100,n1=13,edit='weight',where='TRUE'):
        self.db.execute(f'''CREATE OR REPLACE VIEW original AS
          SELECT i,(i>={n0})::INT arm,(i%17=0 AND i%3<>0)::INT y,(i%3<>0)::INT reached,
          CASE WHEN i>={n0} THEN {n0}::DOUBLE/{n0+n1} ELSE {n1}::DOUBLE/{n0+n1} END weight
          FROM range({n0+n1}) t(i)''')
        self.db.execute('''CREATE OR REPLACE VIEW cells AS SELECT 'one' cell,
          count(*) FILTER(WHERE arm=0) n0,count(*) FILTER(WHERE arm=1) n1,
          avg(y) FILTER(WHERE arm=0) y0,avg(y) FILTER(WHERE arm=1) y1,
          avg(reached) FILTER(WHERE arm=0) r0,avg(reached) FILTER(WHERE arm=1) r1 FROM original''')
        self.db.execute('CREATE OR REPLACE VIEW d AS SELECT arm,y,reached,'+edit+' weight FROM original WHERE '+where)
    def test_production_size_false_stop_and_compensated_reconciliation(self):
        # Same arm sizes as the returned 11,432,259-row frame; one synthetic
        # cell. Reproduces the numeric failure without production observations.
        self.data(n0=10448509,n1=983750)
        naive=[r[1] for r in self.db.execute('SELECT arm,sum(weight) FROM d GROUP BY arm ORDER BY arm').fetchall()]
        self.assertFalse(math.isclose(naive[0],naive[1],rel_tol=RTOL,abs_tol=ATOL))
        groups,audit=matched_moments(self.db,self.root/'audit.json')
        self.assertEqual(audit['status'],'PASSED');self.assertFalse(audit['weights_rescaled'])
        self.assertEqual(groups[0][1],10448509);self.assertEqual(groups[1][1],983750)
        self.assertEqual(groups[0][5],groups[1][5]);self.assertEqual(read(self.root/'audit.json'),audit)
        self.assertLess(audit['compensated_relative_arm_gap'],1e-14)
    def test_real_weight_error_and_balanced_rescaling_still_stop(self):
        for edit in ('CASE WHEN i=0 THEN weight+.01 ELSE weight END','weight*.99'):
            with self.subTest(edit=edit):
                self.data(edit=edit)
                with self.assertRaisesRegex(RuntimeError,'cell formula'):matched_moments(self.db,self.root/'audit.json')
                self.assertEqual(read(self.root/'audit.json')['status'],'FAILED')
    def test_missing_rows_invalid_weights_and_changed_outcomes_stop(self):
        for edit,where in [('weight','i<>0'),('CASE WHEN i=0 THEN NULL ELSE weight END','TRUE'),("CASE WHEN i=0 THEN 'NaN'::DOUBLE ELSE weight END",'TRUE')]:
            with self.subTest(edit=edit,where=where):
                self.data(edit=edit,where=where)
                with self.assertRaisesRegex(RuntimeError,'Overlap reconciliation failed'):matched_moments(self.db)
        self.data();self.db.execute('CREATE OR REPLACE VIEW d AS SELECT arm,1-y y,1 reached,weight FROM original')
        with self.assertRaisesRegex(RuntimeError,'weighted_grants'):matched_moments(self.db)
    def test_v101_failed_fit_reuses_every_matching_partition(self):
        fixture=fixtures.CloseoutTests();fixture.setUp()
        try:
            with patch.object(bio,'PARTITIONS',7):
                run=fixture.root/'run';auth=fixture.ordinary();source=previous.prepare(fixture.a,run,'resume102',auth)
                # Stop the original version at the exact failed guard.
                with patch.object(previous.np,'isclose',return_value=False):
                    with self.assertRaisesRegex(RuntimeError,'not balanced across arms'):
                        previous.fit(fixture.a,run,'resume102',source,'overlap')
                paths=sorted((run/'PRIVATE/ordinary_matching_v101/overlap').rglob('*'))
                stamps={p:signature(p) for p in paths if p.is_file()}
                source_stamp=signature(source)
                result=current.fit(fixture.a,run,'resume102',source,'overlap')
                self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['weight_audit']['status'],'PASSED')
                self.assertEqual(source_stamp,signature(source))
                for path,stamp in stamps.items():self.assertEqual(signature(path),stamp,str(path))
                self.assertEqual(read(run/'report/ORDINARY_WEIGHT_AUDIT_overlap.json'),result['weight_audit'])
        finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
