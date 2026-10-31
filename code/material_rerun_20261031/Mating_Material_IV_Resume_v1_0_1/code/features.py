"""Rebuild decision histories; reuse only identified factual volume and denominators."""
from bootstrap import *
import fast_features as ff
FROZEN_VOLUME90=ff.volume
FROZEN_ENVIRONMENT=c.primary.environment

def history_job(job):
    def build(tmp):
        q={k:pq.read_table(job['queries'],columns=[k])[k].to_numpy() for k in ('row_id','game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms')}
        db=connect(tmp,3.);result=dict(row_id=q['row_id']);n=len(q['row_id'])
        try:
            view(db,'q',job['queries'])
            if n:
                lower=int(q['archive_start_ms'].min())-97*DAY;upper=int(q['archive_start_ms'].max())
                h=db.execute('SELECT e.person,e.t,'+','.join('e.clean_'+x for x in ('fair','kind','disconnect','receipt','claim'))+' FROM '+c.parq(job['histories'])+f' e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.person=q.recipient_id WHERE e.t>={lower} AND e.t<{upper} ORDER BY person,t').fetchnumpy()
                keys=ff.moments(h['person'],h['t'])
                for prefix,days,gap in [('',90,0),('legacy_',90,7),('recent_',30,7)]:
                    lo=np.searchsorted(keys,ff.moments(q['recipient_id'],q['archive_start_ms']-(days+gap)*DAY),'left')
                    hi=np.searchsorted(keys,ff.moments(q['recipient_id'],q['archive_start_ms']-gap*DAY),'left')
                    for name in ('fair','kind','disconnect','receipt','claim'):
                        cum=np.r_[0,np.cumsum(h['clean_'+name],dtype=np.int64)]
                        result[prefix+name+'_90']=cum[hi]-cum[lo]
                del h;gc.collect()
                prior=db.execute('SELECT e.person,min(e.t) AS t FROM '+c.parq(job['histories'])+' e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.person=q.recipient_id WHERE e.clean_fair>0 GROUP BY e.person ORDER BY e.person').fetchnumpy()
                ix=np.searchsorted(prior['person'],q['recipient_id']);ok=ix<len(prior['person']);ok[ok]&=prior['person'][ix[ok]]==q['recipient_id'][ok]
                previous=np.zeros(n,bool);previous[ok]=prior['t'][ix[ok]]<q['archive_start_ms'][ok];result['prior_choice_any_panel']=previous
                h=db.execute('SELECT e.* FROM '+c.parq(job['futures'])+f" e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.j=q.recipient_id WHERE e.t>{int(q['anchor_ms'].min())} AND e.t<={int(q['anchor_ms'].max())+90*DAY} ORDER BY j,t,ord,gid").fetchnumpy()
            else:
                for prefix in ('','legacy_','recent_'):
                    for name in ('fair','kind','disconnect','receipt','claim'):result[prefix+name+'_90']=np.empty(0,np.int64)
                result['prior_choice_any_panel']=np.empty(0,bool)
                h={k:np.empty(0,'U8' if k=='gid' else bool if k=='y' else np.int64) for k in ('gid','j','i','t','start','ord','y')}
            result.update(c.fast.sorted_later_outcomes(h,q));result['history_window_complete']=q['archive_start_ms']-90*DAY>=int(c.phase_inputs.core.STARTS[0])
            pq.write_table(pa.table(result),tmp/'outcomes.parquet',compression='zstd');return dict(rows=n)
        finally:db.close()
    return stage(job['output'],job['conf'],build,[job['queries']]+job['histories']+job['futures'])[1]

def behavior(a,run,conf,bound,source):
    def prep(tmp):
        db=connect(tmp)
        try:
            for s in range(16):copy(db,'SELECT * FROM '+c.parq([source])+f' WHERE recipient_id%16={s} ORDER BY row_id',tmp/f'outcome_{s:02}.parquet')
            return dict(rows=rows(source))
        finally:db.close()
    q,_=stage(run/'PRIVATE/behavior_queries90',conf,prep,[source]);jobs=c.inputs.outcome_jobs(bound,q,run/'PRIVATE/behavior90',conf)
    c.mapped(history_job,jobs,min(a.workers,2),'Fresh recipient histories and later choices')
    parts=[Path(j['output'])/'outcomes.parquet' for j in jobs]
    def join(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',source);view(db,'h',parts);c.assert_coverage(db,'q','h')
            remove=list(set(c.columns(parts[0]))-{'row_id'})
            copy(db,'SELECT '+c.except_fields('q',source,remove)+',h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',tmp/'features.parquet')
            view(db,'f',tmp/'features.parquet');c.ensure(db,'SELECT count(*) FROM f WHERE NOT history_window_complete OR (y AND NOT reached)','Invalid history or zero-coded outcome')
            c.ensure(db,f'SELECT count(*) FROM f WHERE reached AND (outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY} OR outcome_start<=anchor_ms OR outcome_opponent=opponent_id OR outcome_gid=game_id)','Future choice temporal/pair restriction failed')
            return dict(rows=rows(source))
        finally:db.close()
    out,_=stage(run/'PRIVATE/behavior_combined90',conf,join,[source]+parts);return out/'features.parquet'

def volume(a,run,conf,bound,source,known,days=90):
    root=run/'PRIVATE'/f'factual_volume_{days}';column=f'pre_games_{days}d'
    known=[str(p) for p in known if column in c.columns(p)]
    def prep(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',source)
            # Original row numbers can change. Match the factual event identity.
            if known:
                db.execute('CREATE VIEW union_known AS '+' UNION ALL '.join('SELECT game_id,recipient_id,archive_start_ms,'+column+' FROM '+c.parq([p]) for p in known))
                c.ensure(db,'SELECT count(*) FROM (SELECT game_id,recipient_id,archive_start_ms FROM union_known GROUP BY ALL HAVING min('+column+')<>max('+column+') OR count('+column+')<>count(*))','Factual volume caches disagree')
                db.execute('CREATE VIEW k AS SELECT game_id,recipient_id,archive_start_ms,min('+column+')::BIGINT '+column+' FROM union_known GROUP BY ALL')
                copy(db,'SELECT q.row_id,k.'+column+' FROM q JOIN k USING(game_id,recipient_id,archive_start_ms) ORDER BY q.row_id',tmp/'known.parquet')
                copy(db,'SELECT q.* FROM q ANTI JOIN k USING(game_id,recipient_id,archive_start_ms) ORDER BY q.row_id',tmp/'missing.parquet')
            else:
                copy(db,'SELECT row_id,0::BIGINT '+column+' FROM q WHERE FALSE',tmp/'known.parquet')
                copy(db,'SELECT * FROM q ORDER BY row_id',tmp/'missing.parquet')
            return dict(total=rows(source),reused=rows(tmp/'known.parquet'),missing=rows(tmp/'missing.parquet'),days=days)
        finally:db.close()
    pp,info=stage(root/'plan',conf,prep,[source]+known);paths=[pp/'known.parquet']
    log(f'Factual {days}-day volume: {info["reused"]:,} cached, {info["missing"]:,} need a scan.')
    if info['missing']:
        if days==90:fresh=FROZEN_VOLUME90(a,root/'scan',conf,bound,pp/'missing.parquet')
        else:
            r=root/'scan';r.mkdir(parents=True,exist_ok=True)
            fresh=c.cutoffs.add_volume(a,dict(bound,original=str(pp/'known.parquet')),pp/'missing.parquet',r,conf)
        paths.append(fresh)
    def join(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',source)
            db.execute('CREATE VIEW v AS '+' UNION ALL '.join('SELECT row_id,'+column+' FROM '+c.parq([p]) for p in paths))
            c.assert_coverage(db,'q','v');copy(db,'SELECT '+c.except_fields('q',source,[column])+',v.'+column+' FROM q JOIN v USING(row_id) ORDER BY row_id',tmp/'source.parquet')
            return {k:info[k] for k in ("total","reused","missing","days")}
        finally:db.close()
    out,_=stage(root/'combined',conf,join,[source]+paths);save(run/'report'/f'VOLUME_{days}.json',info);return out/'source.parquet'

def removed_main(a,run,conf,auth,b):
    new=[r['path'] for r in auth['material']['records']]
    old=b['bound']['binding']['source']['panels'];old=[r['path'] if isinstance(r,dict) else r for r in old]
    def build(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'o',old);view(db,'n',new);ids=','.join(map(str,b['bound']['binding']['author_ids']))
            copy(db,'''SELECT o.game_id,o.utc_ms::BIGINT start_ms,o.api_last_move_at_ms::BIGINT end_ms,
              o.chooser_user_id::BIGINT j,o.disconnected_user_id::BIGINT i
              FROM o ANTI JOIN n USING(game_id) WHERE o.chooser_user_id NOT IN ('''+ids+') AND o.disconnected_user_id NOT IN ('+ids+')',tmp/'events.parquet')
            require(rows(tmp/'events.parquet')==20570,'Unexpected number of removed main environment events');return dict(removed=20570)
        finally:db.close()
    out,_=stage(run/'PRIVATE/removed_main',conf,build,old+new);return out/'events.parquet'

def environment(a,run,conf,b,source,removed):
    # Old ENV dates and all-game denominators remain factual. Its decision
    # numerators are corrected by subtracting the removed material events.
    original=FROZEN_ENVIRONMENT(a,run/'old_env_facts',conf,b,source)
    rates=run/'old_env_facts/PRIVATE/wider/environment/combined/rates.parquet'
    def correct(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'r',rates);view(db,'d',removed)
            db.execute('''CREATE VIEW e AS SELECT i person,j counterpart,start_ms,end_ms,1::BIGINT own,0::BIGINT chooser FROM d
              UNION ALL SELECT j,i,start_ms,end_ms,0,1 FROM d''')
            copy(db,'''WITH v AS (
              SELECT r.person,r.partner,r.month_code,coalesce(sum(e.own),0)::BIGINT drop_own,
                coalesce(sum(e.chooser),0)::BIGINT drop_chooser FROM r LEFT JOIN e
                ON r.complete AND r.person=e.person AND r.partner<>e.counterpart AND e.start_ms>=r.lo AND e.start_ms<r.hi AND e.end_ms<r.hi GROUP BY r.person,r.partner,r.month_code
              ), fixed AS (
                SELECT r.* EXCLUDE(own,chooser,opponent_observed_disconnect_rate,opponent_observed_chooser_rate),
                  r.own-v.drop_own AS own,r.chooser-v.drop_chooser AS chooser
                FROM r JOIN v USING(person,partner,month_code)
              ) SELECT *,CASE WHEN environment_supported THEN own::DOUBLE/games ELSE NULL END opponent_observed_disconnect_rate,
                CASE WHEN environment_supported THEN chooser::DOUBLE/games ELSE NULL END opponent_observed_chooser_rate FROM fixed''',tmp/'rates.parquet')
            view(db,'f',tmp/'rates.parquet');c.ensure(db,'SELECT count(*) FROM f WHERE games<0 OR own<0 OR chooser<0 OR own+chooser>games','Invalid corrected environment counts')
            return dict(keys=rows(rates),factual_game_denominators_preserved=True,removed_decisions=rows(removed))
        finally:db.close()
    out,info=stage(run/'PRIVATE/material_environment',conf,correct,[rates,removed])
    attached,_=c.frozen.r.env_rates.attach(source,out/'rates.parquet',run/'PRIVATE/material_environment_attached',conf,a.memory_gb-2)
    save(run/'report/ENVIRONMENT_CORRECTION.json',info);return attached/'model.parquet'
