import sys, unittest, tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from phase100_common import *
import phase100_models as models
import bounded_linear as linear
import bounded_entry, bounded_secondary
import bounded_assembly
import test_models_and_reuse as fixtures


class BoundedCalculationTests(unittest.TestCase):
    def test_primary_balance_and_joint_tests_match_after_removing_duplicate_columns(self):
        d=fixtures.ModelTests().data()
        with models.checked_solver():old=stats.estimate(d,SPECS['entry'])
        with models.checked_solver(owned=True):new=models.bounded_primary.estimate(d,SPECS['entry'])
        self.compare(old['estimates'],new['estimates'])
        def compare(x,y):
            if isinstance(x,dict):
                self.assertEqual(set(x),set(y))
                for k in x:compare(x[k],y[k])
            elif isinstance(x,list):
                self.assertEqual(len(x),len(y))
                for a,b in zip(x,y):compare(a,b)
            elif isinstance(x,(float,np.floating)):
                np.testing.assert_allclose(x,y,rtol=2e-7,atol=2e-9,equal_nan=True)
            else:self.assertEqual(x,y)
        for key in ('balance','joint_balance'):compare(old[key],new[key])

    def compare(self,a,b):
        self.assertEqual(len(a),len(b))
        for x,y in zip(a,b):
            for k in ('outcome','instrument','control_level','n','events','supported'):
                self.assertEqual(x.get(k),y.get(k),k)
            for k in ('coefficient_pp','standard_error_pp','coefficient','standard_error'):
                if k in x and x[k] is not None:
                    np.testing.assert_allclose(x[k],y[k],atol=2e-10,rtol=2e-8,err_msg=k)

    def test_all_entry_levels_and_contrasts_equal_checked_parent(self):
        d=fixtures.ModelTests().data()
        with models.checked_solver():
            old=models.entry_models.estimate(d,'test','competitive_supported',.13)
        with models.checked_solver(owned=True) as audits:
            new=bounded_entry.estimate(d,'test','competitive_supported',.13)
        self.compare(old['estimates'],new['estimates'])
        self.compare(old['contrasts'],new['contrasts'])
        self.assertEqual(audits[0]['status'],'CONVERGED')

    def test_both_secondary_families_equal_checked_parent(self):
        d=fixtures.ModelTests().data()
        for family in ('X0','XC'):
            with models.checked_solver():old=models.secondary.estimate(d,family,'test','all_supported')
            with models.checked_solver(owned=True):new=bounded_secondary.estimate(d,family,'test','all_supported')
            self.compare(old,new)

    def test_blocked_projection_crosses_block_boundary_and_rank_deficiency(self):
        rng=np.random.default_rng(43);n=linear.BLOCK+51
        x=rng.normal(size=(n,3));x[:,2]=x[:,0]+2*x[:,1]
        a=np.column_stack([x,rng.normal(size=(n,2))]);groups=[rng.integers(0,401,n),rng.integers(0,80,n)]
        with models.checked_solver():old,oi=num.partial_out(a,groups,3)
        owned=linear.stack_columns(list(a.T))
        with models.checked_solver(owned=True):new,ni=linear.partial_out_owned(owned,groups,3)
        self.assertEqual(oi['continuous_control_rank'],2);self.assertEqual(oi,ni)
        np.testing.assert_allclose(old,new,rtol=1e-10,atol=2e-11)

    def test_owned_solver_uses_same_buffer_and_rejects_shared_views(self):
        raw=linear.stack_columns([np.arange(30.),np.arange(30.)**2])
        with models.checked_solver(owned=True):
            out,it=num.absorb(raw,[np.arange(30)%4])
            self.assertTrue(np.shares_memory(raw,out))
            with self.assertRaises(ValueError):num.absorb(raw[:, :1],[np.arange(30)%4])

    def test_larger_phase_fits_inside_default_budget(self):
        # Eligibility-scaled planning counts, not a claim about realized 75% N.
        self.assertLess(models.memory_estimate(11535000,'primary'),11-1.5)
        self.assertLess(models.memory_estimate(7500000,'competitive_entry'),11-1.5)

    def test_indexed_full_stream_spacing_matches_frozen_ties_and_overlap(self):
        rng=np.random.default_rng(30);n=800
        starts=rng.integers(0,30,n)*DAY
        events=dict(recipient_id=rng.integers(1,80,n),archive_start_ms=starts,
            anchor_ms=starts+rng.integers(0,5,n)*DAY)
        query=dict(recipient_id=rng.integers(1,90,n),archive_start_ms=rng.integers(0,160,n)*DAY)
        for e in (events,{k:v[:0] for k,v in events.items()}):
            want=design.prospective_risk(e,query,90);index=bounded_assembly.RiskIndex(e)
            for sl in (slice(None),slice(17,98)):
                got=index.query({k:v[sl] for k,v in query.items()})
                for k in want:np.testing.assert_array_equal(want[k][sl],got[k])

if __name__=='__main__':unittest.main()
