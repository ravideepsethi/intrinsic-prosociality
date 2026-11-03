"""Consolidated original specifications; heavy models run sequentially."""
from bootstrap import *
import model_kernel as m


def sample(a,run,conf,source,scores,label,where='TRUE',score='A',legacy=False):
    def build(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',source);view(db,'s',scores)
            columns=c.columns(source);drop=[];fields=[]
            if legacy:
                for x in ('fair','kind','disconnect','receipt','claim'):
                    drop.append(x+'_90');fields.append('q.legacy_'+x+'_90 AS '+x+'_90')
            if 'pre_games_30d' not in columns:require(not legacy,'Spaced model lacks factual 30-day volume')
            select=c.except_fields('q',source,drop)+(','+','.join(fields) if fields else '')
            copy(db,'SELECT '+select+' FROM q JOIN s USING(row_id) WHERE '+where+' ORDER BY q.row_id',tmp/'source.parquet')
            fields=['row_id']+[k+'_'+score+' AS '+k+'_A' for k in ('n','counterparts','expected','adjusted')]
            copy(db,'SELECT '+','.join('s.'+k for k in fields)+' FROM s JOIN q USING(row_id) WHERE '+where+' ORDER BY s.row_id',tmp/'scores.parquet')
            return dict(rows=rows(tmp/'source.parquet'),score=score,legacy=legacy)
        finally:db.close()
    out,_=stage(run/'PRIVATE/model_inputs'/label,conf,build,[source,scores]);return out/'source.parquet',out/'scores.parquet'

def fit_one(a,run,conf,source,scores,label,where='TRUE',score='A',legacy=False,control_level='X0_ENV_indicator',**extra):
    src,sc=sample(a,run,conf,source,scores,label,where,score,legacy)
    if rows(src)<2000:
        save(run/'report'/('UNSUPPORTED_'+label+'.json'),dict(status='UNSUPPORTED_LT_2000_ROWS',rows=rows(src)))
        return None
    job=m.job_for(run,conf,label,src,sc,legacy=legacy,**extra)
    job['level']=control_level
    with heartbeat('Model '+label):m.fit(job)
    m.export_models(run);return job

def main(a,run,conf,source,scores):
    primary=fit_one(a,run,conf,source,scores,'uniform_unspaced','q.uniform_keep')
    fit_one(a,run,conf,source,scores,'uniform_unspaced_balance','q.uniform_keep',balance=True)
    # Same nuisance controls as the balance regression, with receipt and Y as
    # additional targets, gives the no-history IV without controlling its traits.
    plan=[primary]
    for label,where,legacy,options in [
        ('legacy_spaced','q.legacy_primary',True,{}),
        ('uniform_same_rows','q.legacy_primary',False,{}),
        ('uniform_spaced','q.uniform_keep AND q.spaced90',False,{}),
        ('uniform_unspaced_old_calendar','q.uniform_keep AND q.legacy_windows',False,{}),
        ('spaced30','q.spaced30 AND q.legacy_windows',True,{}),
        ('first_exposure','q.first_recipient AND q.uniform_keep AND q.legacy_windows',True,{}),
        ('spaced_nohistory','q.legacy_primary',True,{'balance':True}),
        ('first_nohistory','q.first_recipient AND q.uniform_keep AND q.legacy_windows',True,{'balance':True})]:
        plan.append(fit_one(a,run,conf,source,scores,label,where,legacy=legacy,**options))
    # Repeated-recipient membership is defined on the spaced frame itself.
    repeated='q.legacy_primary AND q.recipient_id IN (SELECT recipient_id FROM q WHERE legacy_primary GROUP BY recipient_id HAVING count(*)>=2)'
    fit_one(a,run,conf,source,scores,'repeated_pooled',repeated,legacy=True)
    fit_one(a,run,conf,source,scores,'repeated_recipient_FE',repeated,legacy=True,recipient_fe=True)
    # Context-specific, buffered balance tests are separate from the primary
    # 90-day balance. No controlled trait is presented as an independent test.
    pairs=[('uniform_same_rows','legacy_spaced','history_change_same_rows'),('uniform_spaced','uniform_same_rows','calendar_spaced'),
           ('uniform_unspaced_old_calendar','uniform_same_rows','spacing_same_calendar'),
           ('uniform_unspaced_old_calendar','legacy_spaced','spacing_vs_original_history_same_calendar'),
           ('uniform_unspaced','uniform_spaced','spacing_full_calendar'),
           ('uniform_unspaced','uniform_unspaced_old_calendar','calendar_unspaced')]
    results=[]
    for left,right,label in pairs:
        results+=m.contrast(run,conf,m.job_for(run,conf,left,'',''),m.job_for(run,conf,right,'',''),label,['first_stage','rf_y','iv_y'])
    c.csv_out(run/'report/CONTRASTS.csv',results)

def sensitivities(a,run,conf,source,scores):
    fit_one(a,run,conf,source,scores,'spaced_without_environment','q.legacy_primary',legacy=True,control_level='X0')
    for minimum in (3,10,20):
        where=f'q.spaced90_n{minimum} AND q.legacy_windows AND s.n_A>={minimum} AND isfinite(s.adjusted_A)'
        fit_one(a,run,conf,source,scores,'minimum_'+str(minimum),where,legacy=True,minimum=minimum)
    for hour in ('start','anchor'):fit_one(a,run,conf,source,scores,'same_hour_'+hour,'q.legacy_primary',legacy=True,clock_hour=hour)
    # Alternative instruments use their own counts, distinct-counterpart counts
    # and expected rates as controls, and common rows for paired comparisons.
    contrasts=[]
    for score in ('B','C','competitive','noncompetitive'):
        where=f'q.legacy_primary AND s.n_{score}>=5 AND isfinite(s.adjusted_{score}) AND isfinite(s.expected_{score})'
        j=fit_one(a,run,conf,source,scores,score+'_own',where,score=score,legacy=True)
        base=fit_one(a,run,conf,source,scores,score+'_pooled_same_rows',where,legacy=True)
        if j and base:contrasts+=m.contrast(run,conf,j,base,score+'_minus_pooled',['iv_y'])
    where='q.legacy_primary AND s.n_competitive>=3 AND isfinite(s.adjusted_competitive) AND isfinite(s.expected_competitive)'
    own=fit_one(a,run,conf,source,scores,'competitive_minimum3_own',where,score='competitive',legacy=True,minimum=3)
    pooled=fit_one(a,run,conf,source,scores,'competitive_minimum3_pooled_same_rows',where,legacy=True)
    if own and pooled:contrasts+=m.contrast(run,conf,own,pooled,'competitive_minimum3_minus_pooled',['iv_y'])
    where='q.legacy_primary AND s.n_B>=5 AND s.n_C>=5 AND isfinite(s.adjusted_B) AND isfinite(s.adjusted_C)'
    before=fit_one(a,run,conf,source,scores,'before_both_supported',where,score='B',legacy=True)
    after=fit_one(a,run,conf,source,scores,'after_both_supported',where,score='C',legacy=True)
    if before and after:contrasts+=m.contrast(run,conf,after,before,'after_minus_before',['iv_y'])
    for field in ('prior_choice_any_panel','legacy_fair_90>0'):
        tag='ever_prior' if field=='prior_choice_any_panel' else 'recent_prior'
        yes=fit_one(a,run,conf,source,scores,tag+'_yes','q.legacy_primary AND q.'+field,legacy=True)
        no=fit_one(a,run,conf,source,scores,tag+'_no','q.legacy_primary AND NOT (q.'+field+')',legacy=True)
        if yes and no:contrasts+=m.contrast(run,conf,yes,no,tag+'_difference',['iv_y'])
    c.csv_out(run/'report/SENSITIVITY_CONTRASTS.csv',contrasts)

def subgroups(a,run,conf,source,scores):
    groups=[('speed_'+s,"q.speed="+c.quote(s)) for s in ('bullet','blitz','rapid','classical')]
    groups += [('rating_under1200','q.recipient_rating<1200'),('rating_1200_1600','q.recipient_rating>=1200 AND q.recipient_rating<1600'),('rating_1600_2000','q.recipient_rating>=1600 AND q.recipient_rating<2000'),('rating_2000plus','q.recipient_rating>=2000')]
    groups += [('prior_none','q.legacy_fair_90=0'),('prior_choices_no_grant','q.legacy_fair_90>0 AND q.legacy_kind_90=0'),('prior_grant','q.legacy_kind_90>0')]
    groups += [('month_'+mo,'q.month_code='+str(k)) for k,mo in enumerate(MONTHS)]
    for tag,where in groups:
        src,sc=sample(a,run,conf,source,scores,'subgroup_'+tag,'q.legacy_primary AND ('+where+')',legacy=True)
        if rows(src)<2000:continue
        job=m.job_for(run,conf,'subgroup_'+tag,src,sc,legacy=True);job.update(outcomes=['received'],iv=False)
        with heartbeat(tag):m.fit(job)
        m.export_models(run)

def supplements(a,run,conf,source,scores):
    import supp_core as s
    src,sc=sample(a,run,conf,source,scores,'supplement_primary','q.uniform_keep')
    def design(tmp):
        s.prepare_design(src,sc,tmp,validate_real=False)
        # Parent scientific transforms verified, new frame asserted separately.
        require(rows(src)==rows(sc),'Material supplement rows do not align')
        return dict(rows=rows(src),material_parent=MATERIAL)
    d,_=stage(run/'PRIVATE/supplement_design',conf,design,[src,sc])
    outputs=[];fits={}
    for weighted in (False,True):
        def fit(tmp):s.fit(d,tmp,weighted);return dict(weighted=weighted)
        out,_=stage(run/'PRIVATE'/('supplement_weighted' if weighted else 'supplement_unweighted'),conf,fit,[d/'design.json',d/'base.dat',d/'weights.npy']+[d/(k+'.npy') for k in ('row_id','recipient_id','opponent_id','date','group0','group1','group2')])
        terms=read(out/'terms.json');prefix='w_' if weighted else 'u_';cols=[prefix+t['term'] for t in terms]
        V=s.covariance(out/'influence.parquet',cols,run/'PRIVATE'/('supp_cov_w' if weighted else 'supp_cov_u'))
        meta=read(d/'design.json')['meta'];rr=s.result_rows(terms,V,meta,'material_primary',weighted)
        if not weighted:
            gate=s.baseline_gate(rr,read(run/'PRIVATE/models/uniform_unspaced/result.json'));save(run/'report/SUPPLEMENT_REPLAY.json',gate)
        outputs+=rr;c.csv_out(run/'report/SUPPLEMENTS.csv',outputs)
        fits[weighted]=(out,{r['term']:r for r in rr})
    def differences(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'u',fits[False][0]/'influence.parquet');view(db,'w',fits[True][0]/'influence.parquet')
            c.assert_coverage(db,'u','w')
            copy(db,'SELECT u.row_id,u.recipient_id,u.opponent_id,u.date,u.u_iv_y,u.u_ols_y,w.w_iv_y FROM u JOIN w USING(row_id) ORDER BY u.row_id',tmp/'joint.parquet')
        finally:db.close()
        V=m.covariance(tmp/'joint.parquet',['u_iv_y','u_ols_y','w_iv_y'],run/'PRIVATE/supplement_joint_covariance',4.)
        values=np.array([fits[False][1]['iv_y']['coefficient'],fits[False][1]['ols_y']['coefficient'],fits[True][1]['iv_y']['coefficient']])/100
        result=[]
        for label,gradient in [('OLS_minus_IV',[-1,1,0]),('recipient_weighted_minus_exposure_weighted_IV',[-1,0,1])]:
            g=np.asarray(gradient)
            result.append(dict(contrast=label,units='percentage points per receipt',**m.inference90(float(g@values),float(g@V@g),100)))
        save(tmp/'result.json',result);(tmp/'joint.parquet').unlink()
        return dict(contrasts=len(result))
    joint,_=stage(run/'PRIVATE/supplement_contrasts',conf,differences,[fits[k][0]/'influence.parquet' for k in (False,True)])
    c.csv_out(run/'report/SUPPLEMENT_CONTRASTS.csv',read(joint/'result.json'))
    counts=read(d/'counts.json')
    save(run/'report/EXPOSURE_COUNTS.json',counts['summary'])
    for name in ('histogram','quantiles','thresholds'):c.csv_out(run/'report'/('EXPOSURE_'+name.upper()+'.csv'),counts[name])
    m.overlap_audit(a,run,conf,dict(source=str(src),scores=str(sc)))
