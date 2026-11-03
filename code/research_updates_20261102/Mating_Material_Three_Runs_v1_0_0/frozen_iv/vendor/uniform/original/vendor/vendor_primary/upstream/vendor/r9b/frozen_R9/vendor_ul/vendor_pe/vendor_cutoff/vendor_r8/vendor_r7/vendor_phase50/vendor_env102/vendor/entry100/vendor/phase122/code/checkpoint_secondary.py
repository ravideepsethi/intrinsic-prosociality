"""Declared secondary competitive score check. Frozen primary fits are untouched."""
from phase_features import *
import performance_cache as cache
import performance_histories as fast

COMP_REFERENCE_SD=.09545502195393069
# This is the reported S1/XC unit from the Oct 3 competitive-only run. It is
# retained for readable comparisons; it is not claimed to be a newly fitted
# author-clean receipt first stage or a transportable bias correction.
COHORTS=('new_phase25','increment_10_25','new_phase10','old_author_clean','pooled')

def prepare_queries_secondary(split,root,conf,memory):
    def build(tmp):
        cols=['row_id']+cache.BEHAVIOR_KEYS+SCORE_COLS
        q=io.read(split/'ordinary_pooled.parquet',cols);ids=io.arr(q,'opponent_id')
        shard=num.user_hash(ids)%np.uint64(16)
        for s in range(16):io.table(tmp/f'{s:02}.parquet',q.filter(pa.array(shard==s)))
        return dict(rows=len(q))
    return stable_stage(root,conf,build,[split/'ordinary_pooled.parquet'])

def score_job(job):
    threads_one()
    def produce(query,tmp):
        q=arrays(io.read(query));nq=len(q['row_id']);out={'row_id':q['row_id']}
        vals={k:np.zeros(nq,np.int64) if k.startswith(('n_','counterparts_')) else np.full(nq,np.nan) for k in SCORE_COLS}
        if nq:
            fast.score_index_job(job['index_job']);idx=fast.ScoreIndex(job['index'])
            if np.any((idx.h['cell']<0)|(idx.h['cell']>=500)):raise RuntimeError('Unrecognized board-state cell')
            entire=idx.h;mask=entire['cell']//100>=2
            competitive={k:v[mask] for k,v in entire.items()};other={k:v[~mask] for k,v in entire.items()}
            model=np.load(Path(job['reference'])/'clean.npy',mmap_mode='r',allow_pickle=False)
            for m in np.unique(q['month_code']):
                at=np.flatnonzero(q['month_code']==m);args=(q['opponent_id'][at],q['recipient_id'][at],int(m),model[0,int(m)],job['authors'])
                idx.h=entire;pooled=idx.score(*args)
                idx.h=competitive;comp=idx.score(*args)
                idx.h=other;non=idx.score(*args)
                for k in SCORE_COLS:
                    if not np.allclose(pooled[k],q[k][at],atol=2e-11,rtol=1e-10,equal_nan=True):raise RuntimeError('Secondary pooled score does not reproduce original: '+k)
                    vals[k][at]=comp[k]
                if not np.array_equal(pooled['n_7d'],comp['n_7d']+non['n_7d']):raise RuntimeError('History partition count mismatch')
                reconstructed=np.nan_to_num(comp['adjusted_7d'])*comp['n_7d']+np.nan_to_num(non['adjusted_7d'])*non['n_7d']
                if not np.allclose(pooled['adjusted_7d']*pooled['n_7d'],reconstructed,atol=1e-8,rtol=1e-10):raise RuntimeError('Residual history partition mismatch')
        for k,v in vals.items():out['comp_'+k]=v
        path=tmp/'scores.parquet';io.table(path,pa.table(out));return path
    return cache.feature_stage(job,'scores.parquet',cache.BEHAVIOR_KEYS,produce)

def assemble(split,scorepaths,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1);support=[]
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scorepaths))
            if c.execute('SELECT count(*)-count(DISTINCT row_id) FROM s').fetchone()[0]:raise RuntimeError('Duplicate competitive score row')
            for cohort in COHORTS:
                src=split/('ordinary_'+cohort+'.parquet');c.execute('CREATE OR REPLACE VIEW d AS SELECT * FROM '+io.parq([src]))
                total=c.execute('SELECT count(*) FROM d').fetchone()[0]
                if c.execute('SELECT count(*) FROM d JOIN s USING(row_id)').fetchone()[0]!=total:raise RuntimeError('Missing competitive score')
                eligible='comp_n_7d>=5 AND isfinite(comp_adjusted_7d) AND isfinite(comp_expected_7d)'
                count=io.copy(c,'SELECT d.*,s.* EXCLUDE(row_id) FROM d JOIN s USING(row_id) WHERE '+eligible+' ORDER BY row_id',tmp/(cohort+'.parquet'))
                support.append(dict(cohort=cohort,original_ordinary_n=total,competitive_supported_n=count,excluded=total-count))
            threshold_value=c.execute('SELECT quantile_cont(comp_adjusted_7d,0.95) FROM '+io.parq([tmp/'new_phase25.parquet'])).fetchone()[0]
            io.js(tmp/'support.json',support)
            io.js(tmp/'scale.json',dict(comp_reference_SD=COMP_REFERENCE_SD,pooled_reference_SD=stats.REFERENCE_SD,
                competitive_SD_source='Oct 3 author-included S1 XC unit, fixed scaling only',scores_author_clean=True,
                upper_5pct_raw_competitive_cutoff=threshold_value,cutoff_fitted_on='new_phase25 ordinary rows with >=5 competitive history decisions',
                trimming_rule='retain raw comp score <= cutoff; retain ties; apply same cutoff to all cohorts; refit all controls',
                confirmatory=False,tail_sensitivity_changes_instrument_support=True,no_receipt_effect_estimated=True))
            return dict(support=support,tail_cutoff=threshold_value)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,scorepaths+[split/('ordinary_'+s+'.parquet') for s in COHORTS])

def estimate(d,family,cohort,tail):
    n=len(d['row_id']);base=dict(n=n,cohort=cohort,control_family=family,tail_policy=tail,secondary=True,
        scores_author_clean=True,clustering='shared_account_OR_date_CR0',historical_scores_treated_as_fixed=True,
        row_set_sha256=design.row_digest(d['row_id']),abstract_gate_cleared=False)
    if n<2000:return [dict(base,supported=False,reason='FEWER_THAN_2000_ROWS')]
    xs,names,_,_,groups,missing=stats.controls(d,True)
    if any(missing.values()):raise RuntimeError('Missing controls in competitive comparison')
    if family=='XC':
        for name,v in [('competitive_expected_rate',d['comp_expected_7d']),('log_competitive_decisions',np.log1p(d['comp_n_7d'])),('log_competitive_counterparts',np.log1p(d['comp_counterparts_7d']))]:
            if not np.isfinite(v).all():raise RuntimeError('Missing competitive control')
            xs.append((v-v.mean())/max(float(v.std()),1e-12));names.append(name)
    raw=np.column_stack(xs+[d['adjusted_7d'],d['comp_adjusted_7d'],d['y'],d['reached']])
    res,info=num.partial_out(raw,groups,len(names));del raw,xs
    codes=stats.cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]);meat=lambda v:stats.stats.shared_meat(v,codes,True)
    rows=[]
    for j,(tag,sd) in enumerate([('pooled',stats.REFERENCE_SD),('competitive',COMP_REFERENCE_SD)]):
        z=res[:,j];native=float(np.sqrt(np.mean(z*z)))
        for k,outcome in enumerate(['y','reached']):
            events=int(np.asarray(d[outcome],bool).sum())
            if native<1e-10:fit=dict(supported=False,reason='NO_RESIDUAL_SCORE_VARIATION')
            elif min(events,n-events)<10:fit=dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            else:fit=stats.stats.ols(res[:,2+k],z,meat)
            rows.append(dict(base,instrument=tag,outcome=outcome,events=events,reference_score_SD=sd,native_residual_score_SD=native,
                controls=names,**info,**stats.stats.effect_row(fit,100*sd)))
    return rows

def model_job(job):
    threads_one()
    def build(tmp):
        d=arrays(io.read(job['input']))
        if job['tail']=='exclude_above_95pct' and job['cutoff'] is not None:
            use=d['comp_adjusted_7d']<=job['cutoff'];d={k:v[use] for k,v in d.items()}
        rows=estimate(d,job['family'],job['cohort'],job['tail'])
        io.js(tmp/'result.json',dict(estimates=rows));return dict(rows=len(d['row_id']))
    return stable_stage(job['output'],job['conf'],build,[job['input']])[1]

def run(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime):
    with runtime.stage('Secondary competitive score queries; outcomes reused unchanged'):
        queries,_=prepare_queries_secondary(split,root/'secondary_queries',conf,memory)
    definition=cache.definition('competitive_history_author_clean_v1',dict(pooled_definition=pooled_definition,cp_cutoff=-100,minimum_decisions=5),[Path(__file__)])
    jobs=[]
    for s in range(16):
        j=dict(queries=str(queries/f'{s:02}.parquet'),index=index_jobs[s]['output'],index_job=index_jobs[s],reference=str(reference),
            authors=ids,memory=max(.5,(memory-2)/workers),conf=conf,output=str(root/'secondary_scores'/f'{s:02}'))
        jobs.append(cache.attach(j,shared,'competitive_scores',definition,s))
    runtime.mapped(score_job,jobs,workers,'Competitive historical scores from existing sufficient-statistic indexes')
    with runtime.stage('Competitive support and fixed tail sensitivity'):
        prepared,info=assemble(split,[str(Path(j['output'])/'scores.parquet') for j in jobs],root/'secondary_prepared',conf,memory)
    for cohort in COHORTS:
        for family in ('X0','XC'):
            for tail in ('all_supported','exclude_above_95pct'):
                j=dict(input=str(prepared/(cohort+'.parquet')),cohort=cohort,family=family,tail=tail,cutoff=info['tail_cutoff'],
                    conf=conf,output=str(root/'secondary_models'/(cohort+'_'+family+'_'+tail)))
                runtime.mapped(model_job,[j],1,'Secondary '+cohort+' '+family+' '+tail)
