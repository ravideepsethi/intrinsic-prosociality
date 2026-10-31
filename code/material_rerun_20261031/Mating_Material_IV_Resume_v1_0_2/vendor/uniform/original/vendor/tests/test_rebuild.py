import unittest,tempfile,sys,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import rebuild_models as rm,rebuild_candidates as rc,rebuild_metadata as md,rebuild_frames as rf

def fixture(root,n=2600):
    rng=np.random.default_rng(921)
    d=dict(row_id=np.arange(n),game_id=np.array([f'g{k:07d}' for k in range(n)]),
      recipient_id=rng.integers(1,301,n),opponent_id=rng.integers(301,601,n),
      archive_start_ms=1710000000000+rng.integers(0,30*DAY,n),month_code=rng.integers(3,5,n),
      tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n),recipient_rating=rng.normal(1700,150,n),opponent_rating=rng.normal(1700,150,n),
      pre_games_30d=rng.integers(0,200,n),environment_supported=rng.random(n)>.1)
    z=rng.uniform(-.1,.2,n);d['received']=rng.random(n)<(.2+z)
    d['reached']=rng.random(n)<.65;d['y']=d['reached']&(rng.random(n)<(.2+.15*z))
    d['active_timeout']=rng.random(n)<(.4+.1*z)
    d['recipient_disconnect_main']=d['active_timeout']&(rng.random(n)<.5)
    d['analysis_entry_90']=d['recipient_disconnect_main']&(rng.random(n)<.4)
    for days in (30,90):
        fair=rng.integers(0,40,n);disconnect=rng.integers(0,20,n)
        d[f'fair_{days}']=fair;d[f'kind_{days}']=rng.binomial(fair,.1)
        d[f'disconnect_{days}']=disconnect;d[f'receipt_{days}']=rng.binomial(disconnect,.1);d[f'claim_{days}']=disconnect-d[f'receipt_{days}']
    for x in frozen.r.ENV:d[x]=rng.normal(size=n)
    scores=dict(row_id=np.arange(n),n_A=rng.integers(5,50,n),counterparts_A=rng.integers(1,5,n),expected_A=rng.uniform(.1,.3,n),adjusted_A=z)
    p=root/'model.parquet';s=root/'scores.parquet';pq.write_table(pa.table(d),p);pq.write_table(pa.table(scores),s)
    return p,s,d,scores

class Rebuild(unittest.TestCase):
    def test_sql_covariance_matches_direct_pairwise_OR(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rng=np.random.default_rng(14);n=61
            i=rng.integers(1,20,n);j=rng.integers(1,20,n);j=np.where(i==j,j+30,j);date=rng.integers(1,6,n);s=rng.normal(size=(n,3))
            p=root/'influence.parquet';pq.write_table(pa.table(dict(recipient_id=i,opponent_id=j,date=date,a=s[:,0],b=s[:,1],c=s[:,2])),p)
            got=rm.sql_covariance(p,['a','b','c'],root/'calc',.2)
            share=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(date[:,None]==date)
            expected=s.T@share.astype(float)@s
            np.testing.assert_allclose(got,expected,atol=1e-10)

    def test_models_reproduce_frozen_R9_coefficients_covariance_balance_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,_,_=fixture(root)
            for kind,level in [('ordinary','X0_ENV_indicator'),('entry','X0')]:
                job=fits.make_job(p,s,root/(kind+'_fit'),'unit',kind,kind,level);job['memory']=.3
                expected,_=fits.estimate(job)
                rm.fit_job(job);got=load(Path(job['output'])/'result.json');rm.replay_check(got,expected)
                stamp=(Path(job['output'])/'result.json').stat().st_mtime_ns
                rm.fit_job(job);self.assertEqual(stamp,(Path(job['output'])/'result.json').stat().st_mtime_ns)
                self.assertFalse((Path(job['output'])/'design.dat').exists())

    def test_joint_contrast_preserves_cross_sample_covariance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rng=np.random.default_rng(421);i=np.array([1,2,3,1,5,6]);j=np.array([2,3,4,7,6,5]);dates=np.array([1,1,2,2,3,4]);s=rng.normal(size=6)*.01
            for side,take,beta in [('left',slice(0,3),.12),('right',slice(3,6),.03)]:
                folder=root/side;folder.mkdir();pq.write_table(pa.table(dict(row_id=np.arange(3),recipient_id=i[take],opponent_id=j[take],date=dates[take],y=s[take])),folder/'influence_PRIVATE.parquet')
                save(folder/'result.json',dict(estimates=[dict(outcome='y',estimator='reduced_form',coefficient=beta,n=3)]))
            job=dict(left=str(root/'left'),right=str(root/'right'),outcomes=['y'],label='test',level='X0',conf='unit',output=str(root/'contrast'))
            rm.contrast_job(job);got=load(root/'contrast/result.json')[0];V=np.array(got['covariance_matrix'])
            codes=frozen.r.stats.cmp.covariance_codes(i,j,dates);influence=np.zeros((6,2));influence[:3,0]=s[:3];influence[3:,1]=s[3:]
            expected=frozen.shared_meat(influence,codes,True)
            np.testing.assert_allclose(V,expected,atol=1e-15);self.assertNotEqual(float(V[0,1]),0.)

    def test_full_frame_query_does_not_reapply_prior_support_or_change_hash_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'PRIVATE').mkdir();(root/'report').mkdir();start=int(phase_inputs.core.STARTS[5]);ids=np.arange(6)
            # Rows: low prior support kept; old pilot excluded; author excluded;
            # strict 90-day boundary excluded; +1ms passes; same-anchor tie passes.
            starts=np.array([start,start,start,start,start+1,start])
            d=dict(game_id=np.array([f'c{k:07}' for k in ids]),recipient_id=np.array([1,2,99,4,4,6]),opponent_id=np.full(6,200),
              utc_ms=starts,month=np.array([phase_inputs.core.MONTHS[5]]*6),recipient_color=np.array(['white']*6),speed_partition=np.array(['blitz']*6),
              previous_frame=np.array([False,True,False,False,False,False]),n7_author_clean=np.zeros(6,np.int64))
            ledger=root/'ledger.parquet';pq.write_table(pa.table(d),ledger)
            stream=root/'stream.parquet';pq.write_table(pa.table(dict(recipient_id=[4,6],anchor_ms=[start-90*DAY,start],archive_start_ms=[start-91*DAY,start-1])),stream)
            b=dict(local=dict(ledgers=[str(ledger)]),primary=dict(bound=dict(binding=dict(author_ids=[99,100]),reference=str(root/'ref.npy'),parts=[])))
            np.save(root/'ref.npy',np.zeros(1))
            def fake_score(job):
                q=pq.read_table(job['query']);n=len(q);Path(job['out']).parent.mkdir(parents=True,exist_ok=True)
                pq.write_table(pa.table(dict(row_id=q['row_id'],n_A=np.full(n,5),counterparts_A=np.full(n,5),expected_A=np.full(n,.2),adjusted_A=np.full(n,.1))),job['out'])
                return job['out']
            a=SimpleNamespace(memory_gb=10.5,workers=1)
            with patch.object(rc,'receipt_stream',return_value=stream),patch.object(cache_auth,'FRAME_ROWS',6),patch.object(rc,'mapped',side_effect=lambda fn,jobs,*args:[fake_score(j) for j in jobs]):
                rc.candidates(a,root,'unit',b)
            got=pq.read_table(root/'PRIVATE/supported/queries.parquet').to_pydict()
            self.assertEqual(got['game_id'],['c0000000','c0000004','c0000005'])
            self.assertTrue(all(v==0 for v in got['legacy_prior_count']))

    def test_metadata_checks_previous_hash_rows_and_detects_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=connection(root,.2)
            try:
                row={f.name:None for f in md.expansion.metadata_schema()};row.update(game_id='abcdefgh',source='pool',status='resign',winner='white',
                  api_start_ms=1710000000000,anchor_ms=1710000001000,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,
                  white_username='a',black_username='b',white_rating=1500.,black_rating=1600.,record_errors='')
                p=root/'meta.parquet';pq.write_table(pa.Table.from_pylist([row],schema=md.expansion.metadata_schema()),p)
                q=root/'query.parquet';pq.write_table(pa.table(dict(game_id=['abcdefgh'],row_id=[1],previous_frame=[True],utc_ms=[1710000000000],speed_partition=['blitz'])),q)
                sql=md.metadata_union(c,[p],q);c.execute('CREATE VIEW m AS '+sql);c.execute('CREATE VIEW f AS SELECT * FROM '+parq([q]))
                self.assertEqual(c.execute('SELECT '+md.ready_sql()+' FROM f LEFT JOIN m USING(game_id)').fetchone()[0],'CACHED_POOL_METADATA')
                c.execute('DROP VIEW m');c.execute('DROP VIEW metadata_sources');row['white_rating']=1400.
                p2=root/'meta2.parquet';pq.write_table(pa.Table.from_pylist([row],schema=md.expansion.metadata_schema()),p2)
                sql=md.metadata_union(c,[p,p2],q);c.execute('CREATE VIEW m AS '+sql)
                self.assertEqual(c.execute('SELECT '+md.ready_sql()+' FROM f LEFT JOIN m USING(game_id)').fetchone()[0],'CACHE_CONFLICT_OR_PRIOR_FLAG')
            finally:c.close()

    def test_entry_labels_use_rebuilt_stream_and_distinguish_window_cut(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'PRIVATE/receipt_stream').mkdir(parents=True);(root/'report').mkdir();start=int(phase_inputs.core.STARTS[5])
            q=root/'q.parquet';pq.write_table(pa.table(dict(row_id=[0,1,2],game_id=['abcdefgh','bcdefghi','cdefghij'],recipient_id=[1,2,3],opponent_id=[10,20,30],
              archive_start_ms=[start]*3,anchor_ms=[start+1000]*3,ordinary_narrow=[False,False,True],active_timeout=[True,True,False],status=['timeout','timeout','resign'])),q)
            main=root/'main';main.mkdir();pq.write_table(pa.table(dict(game_id=['abcdefgh','bcdefghi'],i=[1,2],j=[10,20],fair_competitive=[True,True],kind_draw=[True,False],timeout_chooser_win=[False,True])),main/'keys.parquet')
            pq.write_table(pa.table(dict(game_id=['abcdefgh','bcdefghi'],recipient_id=[1,2],rebuilt_spaced90=[True,True],rebuilt_observation_complete=[True,False])),root/'PRIVATE/receipt_stream/stream.parquet')
            b=dict(primary=dict(bound=dict(features=dict(futures=[str(main)],main_conf='unit'))));a=SimpleNamespace(memory_gb=10.5,workers=1)
            with patch.object(rf,'check_stage',side_effect=lambda p,c:p),patch.object(rf,'mapped',side_effect=lambda fn,jobs,*args:[fn(j) for j in jobs]):out=rf.labels(a,root,'unit',b,q)
            d=pq.read_table(out).to_pydict();self.assertEqual(d['selected_entry_90'],[True,True,False]);self.assertEqual(d['analysis_entry_90'],[True,False,False])

    def test_metadata_plan_and_completion_reuse_cached_rows_without_requests(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'PRIVATE/locally_eligible').mkdir(parents=True);(root/'report').mkdir();start=1710000000000
            q=root/'PRIVATE/locally_eligible/queries.parquet'
            pq.write_table(pa.table(dict(row_id=[1,2],game_id=['abcdefgh','bcdefghi'],recipient_id=[1,2],opponent_id=[10,20],
              utc_ms=[start,start],archive_start_ms=[start,start],month_code=[4,4],recipient_color=['white','black'],speed_partition=['blitz','blitz'],previous_frame=[False,False])),q)
            rows=[]
            for game,source in [('abcdefgh','pool'),('bcdefghi','friend')]:
                row={f.name:None for f in md.expansion.metadata_schema()};row.update(game_id=game,source=source,status='resign',winner='white',
                  api_start_ms=start,anchor_ms=start+1000,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,
                  white_username='a',black_username='b',white_rating=1500.,black_rating=1600.,record_errors='')
                rows.append(row)
            meta=root/'meta.parquet';pq.write_table(pa.Table.from_pylist(rows,schema=md.expansion.metadata_schema()),meta)
            quarantine=root/'quarantine.parquet';pq.write_table(pa.table(dict(game_id=['q0000001','q0000002','q0000003'])),quarantine)
            b=dict(metadata=[str(meta)],quarantine=[str(quarantine)],source={});a=SimpleNamespace(memory_gb=10.5,workers=1)
            with patch.object(md.cached_inputs,'identity_check') as identity,patch.object(md.metadata_http,'Client') as client:
                md.retrieve(a,root,'unit',b);client.assert_not_called();identity.assert_called_once()
            got=pq.read_table(root/'PRIVATE/metadata_complete/queries.parquet').to_pydict()
            self.assertEqual(got['game_id'],['abcdefgh']);self.assertEqual(got['recipient_rating'],[1500.])
            md.plan(a,root,'unit',b)

    def test_alltime_pair_exclusion_counts_after_only_decisions(self):
        h=dict(j=np.full(7,200,np.int64),i=np.array([1,1,2,3,4,5,6]),t=np.arange(7)+1700000000000,y=np.array([1,1,0,1,0,1,0]),cell=np.full(7,250,np.int64))
        q=dict(row_id=np.array([1]),opponent_id=np.array([200]),recipient_id=np.array([1]),month_code=np.array([0]))
        score,_=inputs.alltime(h,q,np.full((1,24,4,4,500),.2));self.assertEqual(score['n'].tolist(),[5]);self.assertAlmostEqual(score['adjusted'][0],.2)

    def test_actual_feature_and_frame_joins_preserve_windows_and_explain_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'PRIVATE').mkdir();(root/'report').mkdir();fr=root/'old_frames';fr.mkdir()
            start=int(phase_inputs.core.STARTS[5]);end=int(phase_inputs.core.PANEL_END)
            d=dict(row_id=[1,2,3],game_id=['a0000001','a0000002','a0000003'],recipient_id=[1,2,3],opponent_id=[10,20,30],
              archive_start_ms=[start,end-91*DAY,start],anchor_ms=[start+1000,end-89*DAY,start+1000],
              tc_base_s=[180]*3,pre_games_30d=[5]*3,eligible_main=[True]*3,first_observed_pair=[True]*3,at_risk_90=[True]*3,
              ordinary_narrow=[True,True,False],active_timeout=[False,False,True],status=['resign','resign','timeout'],legacy_prior_count=[6,0,0])
            def write(path,data):
                path.parent.mkdir(parents=True,exist_ok=True);pq.write_table(data if isinstance(data,pa.Table) else pa.table(data),path);return path
            query=write(root/'PRIVATE/metadata_complete/queries.parquet',d)
            hist=dict(row_id=pa.array([1],pa.int64()),history_window_complete=pa.array([True]),y=pa.array([False]),reached=pa.array([False]),
              outcome_gid=pa.array([None],pa.string()),outcome_t=pa.array([None],pa.int64()),outcome_start=pa.array([None],pa.int64()),outcome_opponent=pa.array([None],pa.int64()))
            hist.update({k:pa.array([0],pa.int64()) for k in COUNTS})
            h=pa.table(hist);oldrow={k:[v[0]] for k,v in d.items()};oldrow.update({k:v.to_pylist() for k,v in hist.items() if k!='row_id'})
            known=write(fr/'assembled/features.parquet',pa.table(oldrow,schema=pa.schema(list(pa.table({k:[v[0]] for k,v in d.items()}).schema)+[f for f in h.schema if f.name!='row_id'])))
            old=pa.concat_tables([pq.read_table(known),pq.read_table(known).set_column(0,'row_id',pa.array([4])).set_column(1,'game_id',pa.array(['a0000004'])).set_column(2,'recipient_id',pa.array([4]))])
            oldf=write(root/'oldF.parquet',old);oldo=write(root/'oldO.parquet',old)
            stream=write(root/'PRIVATE/receipt_stream/stream.parquet',pa.table(dict(game_id=pa.array([],pa.string()),recipient_id=pa.array([],pa.int64()),rebuilt_spaced90=pa.array([],pa.bool_()),rebuilt_observation_complete=pa.array([],pa.bool_()))))
            oldstream=write(root/'oldstream.parquet',pa.table(dict(recipient_id=pa.array([],pa.int64()),anchor_ms=pa.array([],pa.int64()))))
            keys=write(root/'main/keys.parquet',dict(game_id=['a0000003'],i=[3],j=[30],fair_competitive=[True],kind_draw=[True],timeout_chooser_win=[False]))
            write(root/'PRIVATE/supported/scores.parquet',dict(row_id=[1,2,3],n_A=[5]*3,counterparts_A=[3]*3,expected_A=[.2]*3,adjusted_A=[.1]*3))
            oldscores=write(root/'oldscores.parquet',dict(row_id=[1,4],n_A=[5]*2,counterparts_A=[3]*2,expected_A=[.2]*2,adjusted_A=[.1]*2))
            write(root/'PRIVATE/candidates/dispositions.parquet',dict(row_id=[1,2,3,4],game_id=['a0000001','a0000002','a0000003','a0000004'],
              previous_frame=[False]*4,author_clean=[True]*4,history_complete=[True]*4,start_calendar_complete=[True]*4,at_risk_90=[True,True,True,False]))
            write(root/'PRIVATE/supported/support_dispositions.parquet',dict(row_id=[1,2,3],total_five_supported=[True]*3))
            write(root/'PRIVATE/chronology/features.parquet',dict(row_id=[1,2,3],eligible_main=[True]*3,first_observed_pair=[True]*3))
            write(root/'PRIVATE/metadata_complete/dispositions.parquet',dict(row_id=[1,2,3],inherited_quarantine=[False]*3,disposition=['CACHED_POOL_METADATA']*3))
            write(fr/'prepared/queries.parquet',dict(row_id=[1,4],game_id=['a0000001','a0000004']))
            write(fr/'early/dispositions.parquet',dict(row_id=[1,4],reason=['KEEP']*2))
            write(fr/'support/dispositions.parquet',dict(row_id=[1,4],keep=[True]*2))
            b=dict(frame_root=str(fr),frame_conf='unit',old_paths=dict(F=str(oldf),O=str(oldo)),old_scores=dict(F=str(oldscores),O=str(oldscores)),source=dict(stream=str(oldstream)),
              primary=dict(bound=dict(features=dict(futures=[str(keys.parent)],main_conf='unit'))))
            a=SimpleNamespace(memory_gb=10.5,workers=1)
            def jobs(bound,prep,out,conf):return [dict(queries=str(prep/f'outcome_{i:02}.parquet'),output=str(out/str(i))) for i in range(16)]
            def mapped(fn,jobs,*args):
                for job in jobs:
                    if fn is fast.role_job:fn(job);continue
                    q=pq.read_table(job['queries']);n=len(q);cols={f.name:pa.array(([None] if f.name.startswith('outcome_') else [f.name=='history_window_complete'] if pa.types.is_boolean(f.type) else [0])*n,type=f.type) for f in h.schema}
                    cols['row_id']=q['row_id'];write(Path(job['output'])/'outcomes.parquet',pa.table(cols,schema=h.schema))
            with patch.object(rf,'check_stage',side_effect=lambda p,c:Path(p)),patch.object(rf.inputs,'outcome_jobs',side_effect=jobs),patch.object(rf,'mapped',side_effect=mapped),\
              patch.object(rf,'pool_rates',return_value=root/'unused_rates'),patch.object(rf.primary,'environment',side_effect=lambda a,r,c,b,s:s):
                out=rf.assemble(a,root,'unit',b)
            entry=pq.read_table(out/'F.parquet');ordinary=pq.read_table(out/'O.parquet')
            self.assertEqual(entry['row_id'].to_pylist(),[1,2,3]);self.assertNotIn('y',entry.schema.names)
            self.assertEqual(ordinary['row_id'].to_pylist(),[1]);self.assertEqual(ordinary['y'].to_pylist(),[False])
            reasons=load(root/'PRIVATE/overlap_audit/reasons.json')
            self.assertEqual(sum(x['rows'] for x in reasons if x['reason']=='old_prior_support_below_five'),2)
            self.assertEqual(sum(x['rows'] for x in reasons if x['reason']=='new_receipt_cooldown'),2)

if __name__=='__main__':unittest.main()
