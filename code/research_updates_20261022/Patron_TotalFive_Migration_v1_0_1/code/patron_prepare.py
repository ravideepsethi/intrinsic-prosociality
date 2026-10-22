"""Rebuild account linkage and original acquisition probabilities on the new roster."""
from patron_common import *
import badge_audit as audit
import patron_binding
import migration_util as mu
import re

def attach(c,source,score,accounts,dest,variants):
    c.execute('CREATE OR REPLACE VIEW src AS SELECT * FROM '+parq(source))
    c.execute('CREATE OR REPLACE VIEW sc AS SELECT * FROM '+parq(score))
    c.execute('CREATE OR REPLACE VIEW acc AS SELECT * FROM '+parq(accounts))
    require(set(RAW)<=set(pq.ParquetFile(source).schema_arrow.names),'Receipt model frame lacks required raw fields')
    for view in ('src','sc','acc'):
        ident='recipient_id' if view=='acc' else 'row_id'
        require(c.execute('SELECT count(*)-count(DISTINCT '+ident+') FROM '+view).fetchone()[0]==0,'Duplicate model/account keys')
    z=[x+'_'+v for v in variants for x in ('n','counterparts','expected','adjusted')]
    fields=['identity_resolved','in_original_chooser_universe','originally_selected','profile_returned','patron','sampling_fraction','query_ms','original_ever_kind','coverage_status']
    query='SELECT '+','.join('src.'+qi(x) for x in RAW)+','+','.join('sc.'+qi(x) for x in z)+','+','.join('acc.'+qi(x) for x in fields)+',coalesce(acc.sampling_fraction>0,FALSE) positive_support FROM src JOIN sc USING(row_id) LEFT JOIN acc USING(recipient_id)'
    copy(c,query+' ORDER BY src.row_id',dest)
    c.execute('CREATE OR REPLACE VIEW result AS SELECT * FROM '+parq(dest))
    require(c.execute('SELECT count(*) FROM result').fetchone()[0]==pq.ParquetFile(source).metadata.num_rows,'Projection lost model rows')
    require(c.execute('SELECT count(*) FROM result WHERE NOT coalesce(identity_resolved,FALSE) OR (profile_returned AND (patron IS NULL OR NOT positive_support OR query_ms IS NULL OR query_ms<=archive_start_ms)) OR (NOT profile_returned AND patron IS NOT NULL)').fetchone()[0]==0,'Invalid identity, observation, support, or timing')

def describe(c,path,name):
    c.execute('CREATE OR REPLACE VIEW d AS SELECT * FROM '+parq(path))
    out=[]
    for group,pred in [('all','TRUE'),('prior_chooser','fair_90>0')]:
        r=records(c,'SELECT count(*) exposures,count(DISTINCT recipient_id) recipients,sum(profile_returned::BIGINT) observed_exposures,count(DISTINCT recipient_id) FILTER(WHERE profile_returned) observed_recipients,count(DISTINCT recipient_id) FILTER(WHERE patron) unique_patrons,sum(coalesce(patron,FALSE)::BIGINT) patron_exposure_rows,count(*) FILTER(WHERE NOT positive_support) zero_support_exposures,count(DISTINCT recipient_id) FILTER(WHERE NOT positive_support) zero_support_recipients,count(*) FILTER(WHERE originally_selected AND NOT profile_returned) nonreturn_exposures FROM d WHERE '+pred)[0]
        r.update(sample=name,subsample=group);out.append(r)
    status=[dict(sample=name,**r) for r in records(c,'SELECT coverage_status,count(*) exposures,count(DISTINCT recipient_id) recipients FROM d GROUP BY coverage_status ORDER BY coverage_status')]
    weights=[]
    for unit,sql in [('exposure','SELECT sampling_fraction FROM d'),('recipient','SELECT DISTINCT recipient_id,sampling_fraction FROM d')]:
        # Apply returned restriction before taking distinct recipients.
        sql=sql+' WHERE profile_returned AND sampling_fraction>0'
        w=records(c,'SELECT count(*) observed_units,sum(w) sum_weights,max(w) max_weight,sum(w)*sum(w)/nullif(sum(w*w),0) kish_effective_units FROM (SELECT 1.0/sampling_fraction w FROM ('+sql+'))')[0]
        weights.append(dict(sample=name,unit=unit,**w))
    timing=records(c,'SELECT min((query_ms-archive_start_ms)/86400000.0) min_days,median((query_ms-archive_start_ms)/86400000.0) median_days,max((query_ms-archive_start_ms)/86400000.0) max_days FROM d WHERE profile_returned')[0]
    dims={'month':'CAST(month_code AS VARCHAR)','speed':"CAST("+audit.speed_sql()+" AS VARCHAR)",'rating':"CASE WHEN recipient_rating<1200 THEN '<1200' WHEN recipient_rating<1600 THEN '1200-1599' WHEN recipient_rating<2000 THEN '1600-1999' ELSE '2000+' END",'prior_chooser':'CAST(fair_90>0 AS VARCHAR)'}
    breakdown=[]
    for label,expr in dims.items():
        breakdown += [dict(sample=name,dimension=label,**r) for r in records(c,'SELECT '+expr+' group_value,count(*) exposures,count(DISTINCT recipient_id) recipients,sum(profile_returned::BIGINT) observed_rows,count(*) FILTER(WHERE NOT positive_support) zero_support_rows,count(DISTINCT recipient_id) FILTER(WHERE patron) unique_patrons FROM d GROUP BY 1 ORDER BY 1')]
    return out,status,weights,dict(sample=name,**timing),breakdown

def prepare(a):
    authority=load(PACKAGE/'evidence/patron_authority.json')
    coverage=a.project/'derived/replication/patron_iv_coverage_v100_PRIVATE'/authority['coverage_config'][:12]
    bound=patron_binding.bind(a.project,coverage,authority);paths=bound['paths']
    save(a.run/'report/patron_input_hashes.json',[{k:r[k] for k in ('role','sha256','bytes')} for r in authority['source_records']])
    inp={k:paths[k] for k in ('chooser','acquisition','snapshot','cell_diagnostics','plan_summary')}
    inp['dictionary']=[paths[k] for k in sorted(paths) if re.fullmatch('dictionary_[0-9]{4}',k)]
    inp['dictionary_column']=load(paths['dictionary_check'])['selected_explicit_ID_column']
    counts=load(PACKAGE/'evidence/badge_authority.json')['counts']
    rp=load(a.run/'PRIVATE/RECEIPT_PATHS.json')
    sources={'primary':(rp['primary'],rp.get('primary_timing_scores',rp['primary_scores'])), 'old':(paths['S0'],paths['S0_scores'])}
    if a.mode=='extended':sources['first_reference']=(rp['first_reference'],rp['first_reference_scores'])
    name='prepared_'+a.mode
    def build(tmp):
        c=connect(tmp,min(a.workers,2),a.memory_gb-2)
        try:
            acc=tmp/'accounts';acc.mkdir()
            profile=audit.build_accounts(c,inp,None,acc,counts,frame_paths=[p[0] for p in sources.values()])
            require(profile['identity_unresolved']==0,'New recipient identities must resolve before fitting')
            accounts=acc/'recipient_profiles_PRIVATE.parquet'
            c.execute('CREATE VIEW rebuilt AS SELECT * FROM '+parq(accounts))
            c.execute('CREATE VIEW previous AS SELECT * FROM '+parq(bound['accounts']))
            compare=['username_norm','original_match_cell','original_ever_kind','in_original_chooser_universe','originally_selected','profile_returned','patron','sampling_fraction','query_ms','coverage_status']
            bad=' OR '.join('a.'+qi(k)+' IS DISTINCT FROM b.'+qi(k) for k in compare)
            require(c.execute('SELECT count(*) FROM rebuilt a JOIN previous b USING(recipient_id) WHERE '+bad).fetchone()[0]==0,'New roster changes original account design or badge value')
            new_ids=c.execute('SELECT count(*) FROM rebuilt ANTI JOIN previous USING(recipient_id)').fetchone()[0]
            allstats=[];statuses=[];weights=[];timings=[];breakdowns=[]
            for label,(src,sc) in sources.items():
                variants=['A','B'] if label=='old' or (label=='primary' and a.mode=='extended') else ['A']
                dest=tmp/(label+'.parquet');attach(c,src,sc,accounts,dest,variants)
                st,ss,ww,tt,bb=describe(c,dest,label);allstats+=st;statuses+=ss;weights+=ww;timings.append(tt);breakdowns+=bb
            for n,v in [('sample_construction',allstats),('coverage_status',statuses),('weight_diagnostics',weights),('snapshot_lags',timings),('coverage_breakdowns',breakdowns)]:table(tmp/n,v)
            prior={r['sample']:r for r in allstats if r['subsample']=='prior_chooser'}
            save(tmp/'eligibility_gate.json',{k:dict(positive_support_everywhere=r['zero_support_exposures']==0,allowed=r['zero_support_exposures']==0 and r['observed_exposures']>=2000) for k,r in prior.items()})
            c.execute('CREATE VIEW old AS SELECT * FROM '+parq(sources['old'][0]))
            c.execute('CREATE VIEW new AS SELECT * FROM '+parq(sources['primary'][0]))
            c.execute("CREATE VIEW row_overlap AS SELECT coalesce(n.row_id,o.row_id) row_id,coalesce(n.recipient_id,o.recipient_id) recipient_id,CASE WHEN n.row_id IS NULL THEN 'removed' WHEN o.row_id IS NULL THEN 'added' ELSE 'retained' END disposition FROM old o FULL JOIN new n USING(row_id)")
            table(tmp/'row_overlap',records(c,'SELECT disposition,count(*) exposures,count(DISTINCT recipient_id) recipients FROM row_overlap GROUP BY 1 ORDER BY 1'))
            table(tmp/'recipient_overlap',records(c,"SELECT CASE WHEN n.recipient_id IS NULL THEN 'removed' WHEN o.recipient_id IS NULL THEN 'added' ELSE 'retained' END disposition,count(*) recipients FROM (SELECT DISTINCT recipient_id FROM old) o FULL JOIN (SELECT DISTINCT recipient_id FROM new) n USING(recipient_id) GROUP BY 1 ORDER BY 1"))
            table(tmp/'coverage_by_row_overlap',records(c,'SELECT disposition,coverage_status,count(*) exposures,count(DISTINCT recipient_id) recipients FROM row_overlap JOIN rebuilt USING(recipient_id) GROUP BY 1,2 ORDER BY 1,2'))
            # The selection ledger identifies why an old row disappears.
            c.execute('CREATE VIEW sel AS SELECT * FROM '+parq(rp['selection']))
            reasons=records(c,"SELECT disposition,CASE WHEN disposition='retained' THEN 'retained' WHEN disposition='added' THEN 'admitted_under_total5_and_recomputed_spacing' WHEN NOT coalesce(supported,FALSE) THEN 'total5_or_finite_score_support' WHEN NOT spaced90 THEN 'displaced_by_recomputed_spacing' WHEN NOT observation_complete THEN 'observation_window' ELSE 'UNEXPLAINED' END reason,count(*) exposures FROM row_overlap LEFT JOIN sel USING(row_id) GROUP BY 1,2 ORDER BY 1,2")
            require(all(r['reason']!='UNEXPLAINED' for r in reasons),'Unexplained receipt row migration')
            table(tmp/'row_change_reasons',reasons)
            save(tmp/'weight_validation.json',dict(original_hash_selection_reproduced=True,original_account_probabilities_recomputed=True,new_accounts_absent_from_old_profile_map=new_ids,overlap_values_identical=True,calibration_weights_used=False,only_fit_normalization='divide original inverse fractions by their mean within the current estimation rows',positive_support_target='new exposure roster intersected with the original positive-probability acquisition universe',unresolved_profiles_coded_as_zero=False,nonresponse_adjusted=False,identification_requires='Original hash selection exchangeability within acquisition strata; nonresponse/zero support are separately reported. No claim to the full new receipt population.'))
            return dict(new_identity_rows=new_ids,all_identities_resolved=True)
        finally:c.close()
    folder=stage(a.run/'PRIVATE',name,a.conf,build)
    for p in folder.glob('*.json'):
        if p.name!='_DONE.json':shutil.copy2(p,a.run/'report'/p.name)
    for p in folder.glob('*.csv'):shutil.copy2(p,a.run/'report'/p.name)
    shutil.copy2(folder/'accounts/original_sampling_cells.csv',a.run/'report/original_sampling_cells.csv')
    save(a.run/'PRIVATE/BADGE_BOUND.json',bound)
    return folder

if __name__=='__main__':
    a=mu.parser().parse_args()
    with mu.pulse('Reconstruct Patron coverage and acquisition probabilities'):prepare(a)
