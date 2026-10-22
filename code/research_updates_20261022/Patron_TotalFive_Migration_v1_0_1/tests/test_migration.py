import sys,unittest,tempfile,subprocess,json,zipfile
from unittest import mock
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import numpy as np,pyarrow as pa,pyarrow.parquet as pq,duckdb
import badge_audit as audit
import patron_models as models
import patron_prepare as prep
import migration_util as mu
from patron_common import *
from comparison_logic import total_count_query,metadata_query
from test_numeric import make_fixture,write
from badge_fixture import fixture

class MigrationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_new_roster_rebuilds_account_probabilities_and_missing_statuses(self):
        inp,counts=fixture(self.root/'input')
        new=self.root/'new.parquet';write(new,[dict(recipient_id=i,opponent_id=200+i) for i in (1,2,3,4,5,6,7)])
        c=audit.connect(self.root/'db',1,4)
        try:
            audit.build_accounts(c,inp,None,self.root/'accounts',counts,frame_paths=[new])
            d=c.execute('SELECT recipient_id,sampling_fraction,patron,coverage_status FROM '+audit.parq(self.root/'accounts/recipient_profiles_PRIVATE.parquet')+' ORDER BY 1').fetchall()
        finally:c.close()
        self.assertEqual([r[1] for r in d],[1,.75,.75,.75,.75,0,0])
        self.assertEqual([r[3] for r in d],['observed','observed','observed','selected_profile_nonreturn','eligible_not_selected','zero_sampling_fraction','outside_original_chooser_universe'])
        self.assertIsNone(d[3][2]);self.assertIsNone(d[4][2]);self.assertFalse(d[1][2])
    def prepare_fixture(self):
        bound,_=make_fixture(self.root/'input',n=6000)
        accounts=pq.read_table(bound['accounts']).to_pylist()
        for r in accounts:
            r.update(originally_selected=r['profile_returned'],coverage_status='observed' if r['profile_returned'] else 'eligible_not_selected' if r['sampling_fraction']>0 else 'outside_original_chooser_universe')
        write(bound['accounts'],accounts)
        c=connect(self.root,1,3);out=self.root/'model.parquet'
        try:prep.attach(c,bound['paths']['S0'],bound['paths']['S0_scores'],bound['accounts'],out,['A','B'])
        finally:c.close()
        return out
    def test_B_and_same_row_A_do_not_trim_main_A(self):
        out=self.prepare_fixture();d=pq.read_table(out).to_pylist()
        for k,r in enumerate(d):
            if k%3==0:r['n_B']=2;r['adjusted_B']=None;r['expected_B']=None
        write(out,d)
        job=dict(input=str(out),name='test',family='patron',sample='new',level='X0',variant='A',weighted=True)
        main=models.estimate(job,minimum_rows=1,minimum_events=1)['rows'][0]
        A=models.estimate(dict(job,before_support=True),minimum_rows=1,minimum_events=1)['rows'][0]
        B=models.estimate(dict(job,before_support=True,variant='B'),minimum_rows=1,minimum_events=1)['rows'][0]
        self.assertGreater(main['n'],A['n']);self.assertEqual(A['row_set_sha256'],B['row_set_sha256'])
        self.assertEqual(B['history_controls_donor_set'],'B')
    def test_missing_returned_badge_rejected(self):
        out=self.prepare_fixture();d=pq.read_table(out).to_pylist()
        next(r for r in d if r['profile_returned'])['patron']=None;write(out,d)
        with self.assertRaisesRegex(RuntimeError,'Missing/nonbinary'):
            models.estimate(dict(input=str(out),name='bad',family='patron',sample='new',level='X0',variant='A',weighted=True),minimum_rows=1)
    def test_coverage_counts_and_weight_kish_are_distinct_units(self):
        out=self.prepare_fixture();c=connect(self.root,1,3)
        try:stats,status,weights,timing,_=prep.describe(c,out,'new')
        finally:c.close()
        self.assertEqual(sum(x['exposures'] for x in status),6000)
        self.assertGreater(weights[0]['observed_units'],weights[1]['observed_units'])
        self.assertGreater(timing['min_days'],0)
        self.assertEqual(next(r for r in stats if r['subsample']=='prior_chooser')['zero_support_exposures'],0)
    def test_full_new_old_preparation_and_fit(self):
        bound,_=make_fixture(self.root/'models',n=6000);inp,expected=fixture(self.root/'badges')
        run=self.root/'run';(run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
        rr=[dict(r,opponent_id=r['opponent_id']+1000) for r in pq.read_table(bound['paths']['S0']).to_pylist() if r['recipient_id']<=7]
        ids={r['row_id'] for r in rr};zz=[r for r in pq.read_table(bound['paths']['S0_scores']).to_pylist() if r['row_id'] in ids]
        old=self.root/'old.parquet';sc=self.root/'sc.parquet';new=self.root/'new.parquet';ns=self.root/'ns.parquet'
        for path,data in [(old,rr),(sc,zz),(new,rr[:-5]),(ns,zz[:-5])]:write(path,data)
        selected=self.root/'selection.parquet';newids={r['row_id'] for r in rr[:-5]}
        write(selected,[dict(row_id=r['row_id'],supported=True,spaced90=r['row_id'] in newids,observation_complete=True) for r in rr])
        save(run/'PRIVATE/RECEIPT_PATHS.json',dict(primary=str(new),primary_scores=str(ns),selection=str(selected)))
        c=audit.connect(self.root/'db',1,4)
        try:audit.build_accounts(c,inp,None,self.root/'old_accounts',expected,frame_paths=[old])
        finally:c.close()
        paths={k:str(v) for k,v in inp.items() if k not in ('dictionary','dictionary_column')}
        check=self.root/'dict.json';save(check,dict(selected_explicit_ID_column='uid'))
        paths.update(S0=str(old),S0_scores=str(sc),dictionary_0000=str(inp['dictionary'][0]),dictionary_check=str(check))
        binding=dict(paths=paths,accounts=str(self.root/'old_accounts/recipient_profiles_PRIVATE.parquet'))
        original_load=prep.load
        def loader(path):return dict(counts=expected) if Path(path).name=='badge_authority.json' else original_load(path)
        args=SimpleNamespace(project=self.root,run=run,conf='test',mode='primary',workers=1,memory_gb=11)
        with mock.patch.object(prep.patron_binding,'bind',return_value=binding),mock.patch.object(prep,'load',side_effect=loader):folder=prep.prepare(args)
        overlap={r['disposition']:r['exposures'] for r in load(folder/'row_overlap.json')}
        self.assertEqual(overlap,dict(retained=len(rr)-5,removed=5))
        job=dict(input=str(folder/'primary.parquet'),name='full',family='patron',sample='new',level='X0',variant='A',weighted=True)
        fit=models.estimate(job,minimum_rows=1,minimum_events=1)
        self.assertEqual(len(fit['rows']),3)
    def test_all_time_count_is_decisions_pair_excluded_and_author_clean(self):
        c=duckdb.connect()
        try:
            c.execute('CREATE TABLE h(j BIGINT,i BIGINT,arm BOOLEAN)')
            c.executemany('INSERT INTO h VALUES(?,?,?)',[(10,1,True)]*8+[(10,2,True)]*5+[(10,3,False)]*50+[(10,101,True)]*9+[(101,4,True)]*30)
            c.execute('CREATE TABLE pairs AS SELECT j,i,count(*)::BIGINT n FROM h WHERE arm AND j NOT IN (101,102) AND i NOT IN (101,102) GROUP BY j,i')
            c.execute('CREATE TABLE people AS SELECT j,sum(n)::BIGINT n FROM pairs GROUP BY j')
            c.execute('CREATE TABLE frame(recipient_id BIGINT,opponent_id BIGINT)');c.executemany('INSERT INTO frame VALUES(?,?)',[(1,10),(2,10),(7,10),(9,20)])
            got=c.execute(total_count_query('frame')+' ORDER BY recipient_id').fetchall()
            self.assertEqual([r[-1] for r in got],[5,8,13,0])
        finally:c.close()
    def test_metadata_missing_conflict_and_explicit_nonpool_stay_distinct(self):
        c=duckdb.connect()
        try:
            c.execute('CREATE TABLE statuses(game_id VARCHAR,metadata_status VARCHAR,fingerprint VARCHAR)')
            c.executemany('INSERT INTO statuses VALUES(?,?,?)',[('a','NO_CACHE','x'),('b','CACHED_NONPOOL','x'),('c','CACHED_POOL_METADATA','x'),('c','CACHED_POOL_METADATA','y'),('d','CACHED_POOL_METADATA','x'),('d','NO_CACHE','y'),('e','CACHED_POOL_METADATA','x'),('e','CACHE_CONFLICT_OR_PRIOR_FLAG','x')])
            got=dict(c.execute(metadata_query()).fetchall())
            self.assertEqual(got,dict(a='MISSING_OR_UNRESOLVED_METADATA',b='CACHED_NONPOOL',c='CROSS_CACHE_CONFLICT',d='CACHED_POOL_METADATA',e='REVIEW_CACHE_FLAGS_OR_INVALID'))
        finally:c.close()
    def test_spacing_before_windows_and_strict_boundary(self):
        # Test in the actual producer's isolated module namespace.
        package=Path(__file__).resolve().parents[1]
        script="""import sys,numpy as np
sys.path.insert(0,sys.argv[1]);import receipt_worker as r
D=86400000
i=np.array([1,1,1,1,1,2]);s=np.array([0,90,91,181,182,5])*D;a=s.copy()
support=np.array([1,1,1,1,1,1],bool)
v=r.pi.spacing_flags(i,s,a,support)['spaced90']
assert v.tolist()==[True,False,True,False,True,True]
# Reject first row on calendar only AFTER its accepted window displaced row 2.
obs=np.array([0,1,1,1,1,1],bool)
assert (v&obs).tolist()==[False,False,True,False,True,True]
"""
        subprocess.run([sys.executable,'-c',script,str(package/'code')],check=True)
    def test_stage_corruption_and_private_export_rejection(self):
        f=stage(self.root,'s','conf',lambda p:(save(p/'r.json',dict(x=1)) or {}))
        (f/'r.json').write_text('{}')
        with self.assertRaises(RuntimeError):stage(self.root,'s','conf',lambda p:{})
        run=self.root/'run';(run/'report').mkdir(parents=True);desktop=self.root/'desktop';desktop.mkdir()
        (run/'report/identities_PRIVATE.parquet').write_bytes(b'private')
        with self.assertRaisesRegex(RuntimeError,'Private file'):mu.export(run,desktop,'abc',25,'TEST')
    def test_comparison_worker_full_synthetic_flow(self):
        subprocess.run([sys.executable,str(Path(__file__).with_name('support_comparison.py'))],check=True)
    def test_spawned_fit_checkpoint(self):
        import patron_fit
        out=self.prepare_fixture();run=self.root/'spawn';run.mkdir()
        a=SimpleNamespace(run=run,conf='test')
        j=patron_fit.make(a,out,'new','patron','X0',weighted=True)
        result=patron_fit.run_jobs(a,[j])
        self.assertEqual(len(result),3)
        verify_stage(Path(j['output']),a.conf)
        self.assertTrue((Path(j['output'])/'influence_PRIVATE.parquet').is_file())

if __name__=='__main__':unittest.main()
