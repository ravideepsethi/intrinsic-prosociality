"""Partitioned ENV execution against frozen SQL, including restart and faults."""
import sys,tempfile,unittest,shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from bootstrap import *
import environment_partitions as ep
import rebuild_frames
import r7_inputs


class EnvironmentPartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.a=SimpleNamespace(workers=2,memory_gb=3.);self.conf='partition_test'
    def tearDown(self):self.temp.cleanup()
    def file(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(data if isinstance(data,pa.Table) else pa.table(data),p,row_group_size=3)
        return p
    def sorted(self,p,keys=ep.KEYS):
        db=connect(self.root/'oracle',.4)
        try:return db.execute('SELECT * FROM '+c.parq([p])+' ORDER BY '+','.join(keys)).fetch_arrow_table().to_pydict()
        finally:db.close()
    def rates(self,name,persons,partners=None,months=None):
        n=len(persons);partners=[100+i for i in range(n)] if partners is None else partners
        months=[5]*n if months is None else months
        lo=[int(c.frozen.r.env_rates.STARTS[m])-97*DAY for m in months]
        hi=[int(c.frozen.r.env_rates.STARTS[m])-7*DAY for m in months]
        return self.file(name,dict(person=pa.array(persons,pa.int64()),partner=pa.array(partners,pa.int64()),
          month_code=pa.array(months,pa.int64()),lo=pa.array(lo,pa.int64()),hi=pa.array(hi,pa.int64()),
          complete=pa.array([True]*n,pa.bool_()),games=pa.array([10]*n,pa.int64()),
          own=pa.array([2]*n,pa.int64()),chooser=pa.array([3]*n,pa.int64()),
          environment_supported=pa.array([True]*n,pa.bool_()),
          log_opponent_games90=pa.array([np.log(11)]*n,pa.float64()),
          opponent_observed_disconnect_rate=pa.array([.2]*n,pa.float64()),
          opponent_observed_chooser_rate=pa.array([.3]*n,pa.float64())))

    def test_pool_exact_original_SQL_priority_tolerance_and_nulls(self):
        r=self.rates('r.parquet',[1,129,-1,None],[2,3,4,5])
        t=pq.read_table(r).to_pydict();t['own']=[2,None,2,2]
        r=self.file('r.parquet',t)
        t['opponent_observed_disconnect_rate'][0]+=.000000000001
        s=self.file('s.parquet',t)
        extra=self.rates('extra.parquet',[17],[8]);b={'primary':dict(known_rates=[str(r),str(s),str(extra)])}
        before=[sha(p) for p in [r,s,extra]]
        old=rebuild_frames.pool_rates(self.a,self.root/'old',self.conf,b)
        new=ep.pool_rates(self.a,self.root/'new',self.conf,b,nparts=8)
        self.assertEqual(self.sorted(new),self.sorted(old))
        self.assertEqual(before,[sha(p) for p in [r,s,extra]])
        self.assertEqual(rows(new),5)
        stamp=new.stat().st_mtime_ns
        with patch.object(ep,'partition',side_effect=AssertionError('repartitioned completed pool')):
            self.assertEqual(ep.pool_rates(self.a,self.root/'new',self.conf,b,nparts=8),new)
        self.assertEqual(stamp,new.stat().st_mtime_ns)

    def test_conflicts_float_integer_boolean_and_partial_null_block(self):
        r=self.rates('r.parquet',[1],[2])
        for field,value in [('own',4),('complete',False),('own',None),('opponent_observed_disconnect_rate',.200000000003)]:
            with self.subTest(field=field,value=value):
                t=pq.read_table(r).to_pydict();t[field][0]=value
                s=self.file('s.parquet',pa.Table.from_pydict(t,schema=pq.read_table(r).schema))
                for fn,label in [(rebuild_frames.pool_rates,'old'),(ep.pool_rates,'new')]:
                    run=self.root/(label+field+str(value))
                    args={} if label=='old' else dict(nparts=4)
                    with self.assertRaisesRegex(RuntimeError,'caches disagree'):
                        fn(self.a,run,self.conf,{'primary':dict(known_rates=[str(r),str(s)])},**args)
                    self.assertFalse((run/'PRIVATE/rate_pool/_DONE.json').exists())

    def test_pool_restart_preserves_checked_partitions_and_detects_corruption(self):
        r=self.rates('r.parquet',list(range(32)));b={'primary':dict(known_rates=[str(r)])};run=self.root/'new'
        with patch.object(ep,'concatenate',side_effect=RuntimeError('interrupted finish')):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):ep.pool_rates(self.a,run,self.conf,b,nparts=4)
        outputs=list((run/'PRIVATE/rate_pool_v106_checked').rglob('rates.parquet'))
        self.assertEqual(len(outputs),4);stamps={p:p.stat().st_mtime_ns for p in outputs}
        with patch.object(ep,'connect',side_effect=AssertionError('completed partition rerun')):
            out=ep.pool_rates(self.a,run,self.conf,b,nparts=4)
        self.assertEqual(stamps,{p:p.stat().st_mtime_ns for p in outputs})
        with out.open('ab') as f:f.write(b'corruption')
        with self.assertRaises(RuntimeError):ep.pool_rates(self.a,run,self.conf,b,nparts=4)

    def test_requests_all_missing_and_windows_match_original(self):
        old=self.rates('old.parquet',[1,2,8],[10,20,80],[5,6,8])
        query=self.file('q.parquet',dict(opponent_id=[1,1,1,2,3,3,7],recipient_id=[10,10,10,20,30,31,70],month_code=[5,5,6,6,7,7,0]))
        original,oi=r7_inputs.missing_requests([query],old,self.root/'oldreq',self.conf,.4)
        new,ni=ep.missing_requests([query],old,self.root/'newreq',self.conf,.4,nparts=4)
        for name,keys in [('requests',ep.KEYS),('people',['person']),('pairs',['person','partner']),('windows',['month_code'])]:
            for folder in ['all','missing']:
                self.assertEqual(self.sorted(self.root/'oldreq'/folder/(name+'.parquet'),keys),
                                 self.sorted(self.root/'newreq'/folder/(name+'.parquet'),keys))
        for key in ['missing_requests','all_requests','windows']:self.assertEqual(oi[key],ni[key])
        self.assertEqual(ni['missing_requests'],4)

    def test_duplicate_known_keys_fail_and_changed_source_refuses_resume(self):
        old=self.rates('old.parquet',[1,1],[2,2]);q=self.file('q.parquet',dict(opponent_id=[1],recipient_id=[2],month_code=[5]))
        with self.assertRaisesRegex(RuntimeError,'Duplicate archived ENV keys'):
            ep.missing_requests([q],old,self.root/'req',self.conf,.4,nparts=4)
        out,_=ep.partition([q],self.root/'parts',self.conf,rename={'opponent_id':'person'},nparts=4)
        pq.write_table(pq.read_table(q),q)
        with self.assertRaisesRegex(RuntimeError,'Checkpoint input changed'):
            ep.partition([q],self.root/'parts',self.conf,rename={'opponent_id':'person'},nparts=4)

    def test_attachment_all_values_and_missing_duplicate_key_rejection(self):
        q=self.file('q.parquet',dict(row_id=[1,3,5,8],opponent_id=[1,2,1,4],recipient_id=[10,20,11,40],month_code=[5,5,6,5],payload=['a',None,'c','d']))
        r=self.rates('r.parquet',[1,2,1,4],[10,20,11,40],[5,5,6,5])
        out,info=ep.attach(q,r,self.root/'attach',self.conf,.4,nparts=4)
        db=connect(self.root/'oracle',.4)
        try:
            view(db,'q',q);view(db,'r',r)
            want=db.execute('SELECT q.*,r.* EXCLUDE(person,partner,month_code) FROM q JOIN r ON q.opponent_id=r.person AND q.recipient_id=r.partner AND q.month_code=r.month_code ORDER BY row_id').fetch_arrow_table()
        finally:db.close()
        self.assertEqual(pq.read_table(out/'model.parquet').to_pydict(),want.to_pydict());self.assertEqual(info['rows'],4)
        table=pq.read_table(r)
        for label,bad in [('missing',table.slice(1)),('duplicate',pa.concat_tables([table,table.slice(0,1)]))]:
            p=self.file(label+'.parquet',bad)
            with self.assertRaisesRegex(RuntimeError,'Environment join changed rows'):
                ep.attach(q,p,self.root/label,self.conf,.4,nparts=4)
            self.assertFalse((self.root/label/'_DONE.json').exists())

    def test_partition_and_attachment_keep_empty_typed_outputs(self):
        q=self.file('empty.parquet',dict(row_id=pa.array([],pa.int64()),opponent_id=pa.array([],pa.int64()),recipient_id=pa.array([],pa.int64()),month_code=pa.array([],pa.int64())))
        r=self.rates('emptyrates.parquet',[])
        out,info=ep.attach(q,r,self.root/'emptyattach',self.conf,.4,nparts=4)
        self.assertEqual(info['rows'],0)
        self.assertIn('environment_supported',pq.read_table(out/'model.parquet').column_names)

    def test_factual_environment_no_missing_matches_frozen_producer(self):
        r=self.rates('r.parquet',[1,2],[10,20],[5,6]);b=dict(known_rates=[str(r)])
        q=self.file('q.parquet',dict(row_id=[0,1],opponent_id=[1,2],recipient_id=[10,20],month_code=[5,6]))
        original=c.primary.environment(self.a,self.root/'old',self.conf,b,q)
        actual=ep.missing_requests
        with patch.object(ep,'missing_requests',side_effect=lambda *args:actual(*args,nparts=4)):
            new=ep.environment_rates(self.a,self.root/'new',self.conf,b,q)
        old=self.root/'old/PRIVATE/wider/environment/combined/rates.parquet'
        self.assertEqual(self.sorted(old),self.sorted(new))
        self.assertFalse((self.root/'new/PRIVATE/wider/environment/attached').exists())

    def test_factual_missing_requests_use_original_scanner_and_author_rules(self):
        r=self.rates('r.parquet',[1],[10],[5]);extra=self.rates('extra.parquet',[2],[20],[6])
        q=self.file('q.parquet',dict(row_id=[0,1],opponent_id=[1,2],recipient_id=[10,20],month_code=[5,6]))
        (self.root/'env/rate_panels').mkdir(parents=True)
        binding=dict(environment=dict(root=str(self.root/'env'),conf='env'),source=dict(chron=['chronology']),author_ids=[55,66])
        b=dict(known_rates=[str(r)],bound=dict(binding=binding));seen=[]
        def jobs(chron,windows,panels,req,parts,conf,memory):
            self.assertEqual(chron,['chronology']);self.assertEqual(rows(req/'requests.parquet'),1)
            return [dict(output=str(parts/'0'))],dict(jobs=1)
        def mapped(fn,jobs,workers,memory,label,*args):
            self.assertIs(fn,c.primary.inputs.env_attempt);seen.extend(jobs)
            self.assertEqual(workers,2);self.assertTrue(all(j['authors']==[55,66] for j in jobs))
            return [dict(ok=True)]
        fresh=self.root/'fresh';fresh.mkdir();shutil.copy2(extra,fresh/'rates.parquet')
        actual=ep.missing_requests
        with patch.object(ep,'missing_requests',side_effect=lambda *args:actual(*args,nparts=4)),\
             patch.object(c.frozen.r.env_rates,'chronology_jobs',side_effect=jobs),\
             patch.object(c.primary.frozen.runtime,'mapped',side_effect=mapped),\
             patch.object(c.frozen.r.env_rates,'combine',return_value=(fresh,{})) as combine:
            out=ep.environment_rates(self.a,self.root/'new',self.conf,b,q)
        self.assertEqual(rows(out),2);self.assertEqual(len(seen),1);combine.assert_called_once()


if __name__=='__main__':unittest.main()
