"""Synthetic production-path checks. No empirical result is simulated as certified."""
import tempfile, unittest, zipfile
from test_r9 import synthetic, sc, fits, inp, report, ms
from r9_common import *
import run_r9

class PipelineTests(unittest.TestCase):
    def test_single_scan_authors_score_combination_and_resume(self):
        rng=np.random.default_rng(18)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);person=np.arange(1,500,dtype=np.int64)
            person=person[r.num.user_hash(person)%np.uint64(16)==0][:12]
            hj=np.repeat(person,80);hi=rng.integers(1000,1020,len(hj));hi[:2]=90001
            h=dict(j=hj,i=hi,t=ms('2023-11-01')+rng.integers(0,700*DAY,len(hj)),y=(rng.random(len(hj))<.15).astype(int),arm=np.ones(len(hj),bool),fair=rng.random(len(hj))<.4,cell=rng.integers(0,500,len(hj),dtype=np.int16))
            h['arm'][10]=False
            donor=root/'donor.parquet';r.io.table(donor,pa.table(h))
            q=dict(row_id=np.arange(36,dtype=np.uint64),frame=np.repeat(np.arange(3,dtype=np.int8),12),opponent_id=np.tile(person,3),recipient_id=rng.integers(1000,1022,36),
                archive_start_ms=np.full(36,ms('2024-07-10')),anchor_ms=np.full(36,ms('2024-07-11')),month_code=np.full(36,8,np.int16),
                n_7d=np.full(36,5),counterparts_7d=np.full(36,4),expected_7d=np.full(36,.1),adjusted_7d=np.full(36,.02))
            query=root/'queries.parquet';r.io.table(query,pa.table(q))
            ref=np.full((2,24,4,4,500),.1);ref[:,0]=np.nan;np.save(root/'ref.npy',ref)
            job=dict(parts=[dict(path=str(donor),sha256=u.sha(donor),rows=len(hj))],queries=str(query),reference=str(root/'ref.npy'),shard=0,authors=[90001,90002],output=str(root/'scan'),conf='toy')
            first=sc.scan_job(job);second=sc.scan_job(job);self.assertEqual(first['eligible_donors'],len(hj)-3)
            self.assertEqual(first['eligible_donors'],second['eligible_donors'])
            clean=r.arrays(r.io.read(root/'scan/events_PRIVATE.parquet'))
            self.assertFalse(np.isin(clean['i'],[90001,90002]).any())
            new=dict(events=str(root/'scan/events_PRIVATE.parquet'),queries=str(query),reference=str(root/'ref.npy'),output=str(root/'new'),conf='toy')
            sc.new_score_job(new)
            paths={}
            q['fair_90']=np.zeros(len(q['row_id']),np.int64)
            for frame,key in enumerate(('S0','F50','F')):
                paths[key]=root/(key+'.parquet');r.io.table(paths[key],pa.table({k:v[q['frame']==frame] for k,v in q.items() if k!='frame'}))
            old,_=sc.combine([str(root/'scan/baseline_scores_PRIVATE.parquet')],paths,root/'combined_old','toy',1)
            sc.combine([str(root/'scan/baseline_scores_PRIVATE.parquet')],paths,root/'certified_old','toy',1,archived={k:old[k] for k in ('S0','F50')})
            got,_=sc.combine([str(root/'new/scores_PRIVATE.parquet')],paths,root/'combined_new','toy',1,new=True)
            diag=report.diagnostics(paths,got,old,root/'diagnostics','toy',1)
            self.assertEqual(u.load(diag)[0]['before_fewer_than_five'],0)
            learning=inp.learning_flags(paths['S0'],[str(root/'scan/first_competitive_PRIVATE.parquet')],root/'learn','toy',1)
            self.assertEqual(pq.ParquetFile(learning).metadata.num_rows,12)

    def test_all_requested_model_families_and_export(self):
        d,a=synthetic(5200)
        # Ensure both learning strata have support; keep archived flag logically nested in full chronology.
        full=np.arange(5200)%4!=0
        for key in ('fair_90','kind_90'):d[key][~full]=0
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);desktop=root/'desktop';desktop.mkdir()
            source=root/'input.parquet';score=root/'scores.parquet'
            r.io.table(source,pa.table(d));r.io.table(score,pa.table(a))
            r.io.table(root/'old.parquet',pa.table(dict(row_id=d['row_id'],adjusted_all_time=a['adjusted_A']*.97)))
            r.io.table(root/'material.parquet',pa.table(dict(row_id=d['row_id'],material_valid=np.ones(5200,bool),material_neutral=np.arange(5200)%8!=0)))
            r.io.table(root/'flags.parquet',pa.table(dict(row_id=d['row_id'],experienced_full=full,experienced_90=d['fair_90']>0)))
            conf='synthetic_pipeline';jobs=[]
            def add(label,level,sample='S0_full',**kw):
                j=fits.make_job(source,score,root/'fits',conf,label+'__'+level,sample,level,primary_sd=.07,**kw)
                jobs.append(j);fits.fit_job(j)
            for level in LEVELS:
                add('A_full',level,balance=True,figure=level==LEVELS[0],implied_bias=True)
                add('A_neutral',level,sample='S0_neutral',material=str(root/'material.parquet'),balance=True)
                add('B_full',level,variant='B')
                for v in 'ABC':add('C_common_'+v,level,sample='S0_common',variant=v,cohort='common')
                add('D_ordinary',level,sample='O75',kind='ordinary',balance=True)
                add('E_entry',level,sample='F75',kind='entry',balance=True,influence=False)
                add('bridge_month',level,history='old')
                add('bridge_oldscore',level,score_recipe='old',old_scores=str(root/'old.parquet'))
                for definition in ('full','90'):
                    for experienced in (False,True):add('learning_'+definition+'_'+str(int(experienced)),level,learning=str(root/'flags.parquet'),learning_definition=definition,experienced=experienced)
            self.assertEqual(len(jobs),28);r.io.js(root/'MODEL_PLAN_PRIVATE.json',jobs)
            cert=root/'baseline_certification';cert.mkdir();r.io.js(cert/'certificate.json',dict(status='SYNTHETIC_FIXTURE_NOT_PRODUCTION_CERTIFICATE'))
            for level in LEVELS:
                pairs=[('after_minus_before','C_common_C','C_common_B',['y','reached','iv_y']),('S0_minus_ordinary','A_full','D_ordinary',['y','reached'])]
                for definition in ('full','90'):pairs.append(('learning_'+definition,'learning_'+definition+'_1','learning_'+definition+'_0',['y','reached','iv_y']))
                for label,left,right,fields in pairs:
                    fits.contrast_job(dict(left=str(root/'fits'/(left+'__'+level)),right=str(root/'fits'/(right+'__'+level)),output=str(root/'contrasts'/(label+'__'+level)),
                        label=label,level=level,fields=fields,conf=conf,primary_sd=.07,sql_memory=1))
            report.export(root,desktop,conf,100,'SYNTHETIC_VALIDATION_ONLY',dict(learning_split='both'))
            self.assertEqual(len(u.load(root/'report/contrasts.json')),22)
            self.assertEqual(len(u.load(root/'report/H_figure5.json')),20)
            self.assertEqual(len(u.load(root/'report/G_implied_bias.json')),4)
            for level in LEVELS:
                hashes=[u.load(root/'fits'/('C_common_'+v+'__'+level)/'result.json')['estimates'][0]['row_set_sha256'] for v in 'ABC']
                self.assertEqual(len(set(hashes)),1)
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                for name in z.namelist():self.assertNotIn('PRIVATE',name)

    def test_frame_bridge_handles_rebound_row_ids_and_absent_entry_outcomes(self):
        d,a=synthetic(3000)
        d['game_id']=np.array(['g'+str(k) for k in range(3000)])
        d['anchor_ms']=d['archive_start_ms']+1000
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);paths={}
            for key,mask,offset in [('S0',np.arange(3000)<2600,0),('F50',np.arange(3000)<2000,20000),('O50',np.arange(3000)<1000,20000),('F',np.ones(3000,bool),0),('O',np.arange(3000)<1500,0)]:
                values={k:v[mask] for k,v in d.items()}
                values['row_id']=values['row_id']+np.uint64(offset)
                if key=='F':
                    for k in ['y','reached']+r.ENV+['environment_supported']:values.pop(k,None)
                paths[key]=p/(key+'.parquet');r.io.table(paths[key],pa.table(values))
            info=inp.frame_checks(paths,[90001,90002],p/'check','toy',1)
            self.assertTrue(info['checks'][-1]['all_shared_model_fields_reproduced'])

    def test_environment_adapter_reuses_old_keys_and_computes_missing(self):
        import env_rates
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);env=p/'old_environment';ec='toy_environment'
            start=ms('2024-03-10')
            w=np.array([501,501,502,502,503,503]);b=np.array([1,3,1,5,5,2]);times=start+np.arange(6)*DAY
            chron=p/'chron.parquet';gids=['e'+str(k) for k in range(6)]
            r.io.table(chron,pa.table(dict(game_id=gids,utc_ms=times,white_id=w,black_id=b)))
            def events(tmp):
                r.io.table(tmp/'events.parquet',pa.table(dict(game_id=gids,start_ms=times,end_ms=times+1000,i=b,j=w)))
                return dict(minimum=int(times.min()),maximum=int(times.max()),rows=6)
            r.stable_stage(env/'rate_panels/00',ec,events,[chron])
            q=dict(row_id=np.arange(4,dtype=np.uint64),recipient_id=np.array([1,2,1,2]),opponent_id=np.array([501,502,503,501]),month_code=np.full(4,6))
            paths={}
            for key,count in [('F',4),('F50',1),('O',2)]:
                folder=p/key;folder.mkdir();paths[key]=folder/'model.parquet';r.io.table(paths[key],pa.table({k:v[:count] for k,v in q.items()}))
            lo=int(r.env_common.STARTS[6])-97*DAY;hi=int(r.env_common.STARTS[6])-7*DAY
            (p/'old').mkdir();old=p/'old/rates.parquet'
            oldvalues=dict(person=[501],partner=[1],month_code=[6],complete=[True],lo=[lo],hi=[hi],games=[1],own=[0],chooser=[1],environment_supported=[True],opponent_observed_disconnect_rate=[0.],opponent_observed_chooser_rate=[1.],log_opponent_games90=[math.log(2)])
            r.io.table(old,pa.table(oldvalues))
            r.io.js(paths['F50'].parent/'dependencies_PRIVATE.json',[dict(path=str(old),sha256=u.sha(old))])
            source=dict(chron=[dict(path=str(chron),signature=r.io.sig(chron),rows=6,file_index=0)])
            binding=dict(environment=dict(root=str(env),conf=ec,config=dict(binding=dict(source=source))),source=source,author_ids=[90001,90002])
            attached,info=inp.environment(paths,binding,p,p/'newenv','toy',11,2)
            self.assertEqual(info['new_pair_month_requests'],3)
            out=r.arrays(r.io.read(attached['F']))
            self.assertEqual(out['games'].tolist(),[1,2,2,2])
            self.assertEqual(out['chooser'].tolist(),[1,2,2,2])
            self.assertTrue(out['environment_supported'].all())
            self.assertTrue((out['opponent_observed_chooser_rate']==1).all())

if __name__=='__main__':unittest.main()
