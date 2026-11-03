from position_common import *

def paired_contrasts(points,V,names,prefix='iv_'):
    rows=[];at={name:k for k,name in enumerate(names)}
    def report(label,beta,g,units):
        rows.append(dict(contrast=label,units=units,**inference(beta,g@V@g)))
    C,L=points[prefix+'grant_comp'],points[prefix+'grant_lost']
    pc,pl=points['base_comp'],points['base_lost']
    g=np.zeros(len(names));g[at[prefix+'grant_lost']]=100;g[at[prefix+'grant_comp']]=-100
    report('lost_minus_comp_absolute',100*(L-C),g,'percentage points')
    if prefix=='iv_':
        for label,terms,scale,units in [
            ('arrival_lost_minus_comp',{'iv_reach_lost':1,'iv_reach_comp':-1},100,'percentage points'),
            ('arrival_either',{'iv_first_either_type_comp':1,'iv_first_either_type_lost':1},100,'percentage points'),
            ('first_either_grant_lost_minus_comp',{'iv_first_either_grant_lost':1,'iv_first_either_grant_comp':-1},100,'percentage points'),
            ('restricted_wait_lost_minus_comp',{'iv_wait_lost_days':1,'iv_wait_comp_days':-1},1,'days')]:
            if all(t in at for t in terms):
                g=np.zeros(len(names))
                for t,w in terms.items():g[at[t]]=w*scale
                report(label,sum(points[t]*w*scale for t,w in terms.items()),g,units)
    if pc<=0 or pl<=0:
        rows.append(dict(contrast='proportional_comparisons',supported=False,reason='ZERO_UNTREATED_BASELINE'))
        return rows
    for label,beta,base in [('comp',C,pc),('lost',L,pl)]:
        g=np.zeros(len(names));g[at[prefix+'grant_'+label]]=1/base;g[at['base_'+label]]=-beta/base**2
        report(label+'_effect_as_share_of_own_base',beta/base,g,'fraction of own untreated baseline')
    g=np.zeros(len(names));g[at[prefix+'grant_lost']]=1/pl;g[at[prefix+'grant_comp']]=-1/pc
    g[at['base_lost']]=-L/pl**2;g[at['base_comp']]=C/pc**2
    report('lost_minus_comp_proportional',L/pl-C/pc,g,'difference in fractions of own untreated baseline')
    # A pp-scale equal-proportion contrast; its SE includes covariance and baseline uncertainty.
    g=np.zeros(len(names));g[at[prefix+'grant_lost']]=100;g[at[prefix+'grant_comp']]=-100*pl/pc
    g[at['base_lost']]=-100*C/pc;g[at['base_comp']]=100*C*pl/pc**2
    report('lost_minus_equal_proportion_benchmark',100*(L-C*pl/pc),g,'percentage points')
    return rows

def fit_projection(a,run,conf,source,scores,label):
    def build(tmp):
        # Force disk storage. Only independent FE columns run concurrently.
        allocate=model.allocate_design
        model.allocate_design=lambda path,n,p:model.disk.disk_matrix(path,n,p)
        try:
            base,groups,actors,targets,meta,_=model.build_buffer(dict(input=str(source),scores=str(scores),
                name=label,level='X0_ENV_indicator',outcomes=['received'],iv=True),tmp)
        finally:model.allocate_design=allocate
        require(targets==['z','received'],'Unexpected base target layout')
        n=len(actors['row_id']);width=2+len(OUTCOMES)
        values=model.disk.disk_matrix(tmp/'expanded.dat',n,width+base.shape[1]-2)
        values[:,:2]=base[:,:2]
        for k,name in enumerate(OUTCOMES):
            x=col(source,name).astype(float);require(np.isfinite(x).all(),'Nonfinite outcome: '+name)
            require(np.all((x>=0)&(x<=90 if name.startswith('wait_') else x<=1)),'Invalid outcome bounds: '+name)
            values[:,2+k]=x;del x
        values[:,width:]=base[:,2:];values.flush();del base;gc.collect();(tmp/'design.dat').unlink()
        for name,value in actors.items():np.save(tmp/(name+'.npy'),value,allow_pickle=False)
        res,rank,diag=model.project(values,groups,width,tmp)
        res.flush();del values,res,groups,actors;gc.collect();(tmp/'expanded.dat').unlink()
        save(tmp/'meta.json',dict(meta=meta,n=n,width=width,targets=['z','received']+OUTCOMES,rank=rank,diagnostics=diag))
        return dict(rows=n)
    return stage(run/'PRIVATE/projection'/label,conf,build,[source,scores])

def estimator_points(res,raw_d,raw_y):
    z,d=res[:,0],res[:,1];zz=float(z@z);zd=float(z@d);dd=float(d@d)
    require(zz>1e-14 and dd>1e-14 and abs(zd)>1e-14,'No identifying variation')
    points={'first_stage':zd/zz}
    for k,name in enumerate(OUTCOMES):points['iv_'+name]=float(z@res[:,k+2])/zd
    for name in ['grant_comp','grant_lost']:
        y=res[:,2+OUTCOMES.index(name)]
        points['rf_'+name]=float(z@y)/zz;points['ols_'+name]=float(d@y)/dd
    n0=int((raw_d==0).sum());require(n0>0,'No untreated exposure rows')
    for label in ['comp','lost']:points['base_'+label]=float(raw_y[label][raw_d==0].mean())
    return points,dict(zz=zz,zd=zd,dd=dd,n0=n0)

def influence_block(res,raw_d,raw_y,points,den):
    z,d=res[:,0],res[:,1];out={'first_stage':z*(d-points['first_stage']*z)/den['zz']}
    for k,name in enumerate(OUTCOMES):out['iv_'+name]=z*(res[:,k+2]-points['iv_'+name]*d)/den['zd']
    for name in ['grant_comp','grant_lost']:
        y=res[:,2+OUTCOMES.index(name)]
        out['rf_'+name]=z*(y-points['rf_'+name]*z)/den['zz']
        out['ols_'+name]=d*(y-points['ols_'+name]*d)/den['dd']
    for label in ['comp','lost']:out['base_'+label]=(1-raw_d)*(raw_y[label]-points['base_'+label])/den['n0']
    return out

def fit(a,run,conf,source,scores,label,primary=False):
    projected=fit_projection(a,run,conf,source,scores,label)
    def influences(tmp):
        info=load(projected/'meta.json');n,width=info['n'],info['width']
        res=np.memmap(projected/'residual.dat',dtype='float64',mode='r',shape=(n,width),order='F')
        actors={k:np.load(projected/(k+'.npy'),mmap_mode='r') for k in ['row_id','recipient_id','opponent_id','date']}
        raw_d=col(source,'received').astype(float);raw_y={l:col(source,'grant_'+l).astype(float) for l in ['comp','lost']}
        points,den=estimator_points(res,raw_d,raw_y);writer=None
        try:
            for lo in range(0,n,65536):
                hi=min(n,lo+65536);part=influence_block(res[lo:hi],raw_d[lo:hi],{k:v[lo:hi] for k,v in raw_y.items()},points,den)
                t=pa.table({**{k:v[lo:hi] for k,v in actors.items()},**part})
                if writer is None:writer=pq.ParquetWriter(tmp/'influence_PRIVATE.parquet',t.schema,compression='zstd')
                writer.write_table(t)
        finally:
            if writer:writer.close()
        save(tmp/'points.json',dict(points=points,denominators=den,meta=info['meta'],native_score_sd=float(np.sqrt(den['zz']/n))))
    infl=stage(run/'PRIVATE/influences'/label,conf,influences,[projected/'POSITION_DONE.json',source])
    pointsinfo=load(infl/'points.json');points=pointsinfo['points'];names=list(points)
    def infer(tmp):
        V=covariance(infl/'influence_PRIVATE.parquet',names,run/'PRIVATE/covariance'/label)
        rows=[]
        for k,name in enumerate(names):
            scale=100*cert.SCALE if name=='first_stage' or name.startswith('rf_') else 1 if 'wait_' in name else 100
            row=dict(exposure_type=label,term=name,n=pointsinfo['meta']['n'],units='days' if 'wait_' in name else 'pp per reference SD' if name=='first_stage' or name.startswith('rf_') else 'percentage points',**inference(points[name],V[k,k],scale))
            if name=='first_stage':
                F=points[name]**2/V[k,k] if V[k,k]>0 else None
                row.update(wald_F=F,positive_first_stage=points[name]>0,weak_first_stage_flag=F is None or F<10)
            rows.append(row)
        contrasts=paired_contrasts(points,V,names)
        save(tmp/'result.json',dict(estimates=rows,contrasts=contrasts,points=points,names=names,covariance=V.tolist(),meta=pointsinfo['meta']))
        if primary:
            cert.check_meta(dict(pointsinfo['meta'],sample='uniform_unspaced'),cert.baseline_row(a.baseline))
            actual={r['term']:r for r in rows}
            for name,value,se in [('first_stage',cert.SLOPE,cert.SLOPE_SE),('iv_grant_comp',.3246734093460897,.05641077060922318)]:
                require(actual[name]['supported'] and np.isclose(actual[name]['coefficient'],value,rtol=2e-7,atol=2e-7) and np.isclose(actual[name]['standard_error'],se,rtol=2e-7,atol=2e-7),'MODEL5_REPRODUCTION_FAILED: '+name)
            require(np.isclose(pointsinfo['native_score_sd'],cert.NATIVE_SD,rtol=2e-7,atol=2e-7),'Native score SD replay failed')
            save(tmp/'reproduction.json',dict(passed=True,n=cert.N,row_hash=cert.ROW_HASH,first_stage=actual['first_stage'],receipt=actual['iv_grant_comp']))
    out=stage(run/'PRIVATE/fits'/label,conf,infer,[infl/'POSITION_DONE.json'])
    result=load(out/'result.json')
    table(run/'report'/f'{label}_estimates.csv',result['estimates']);table(run/'report'/f'{label}_contrasts.csv',result['contrasts'])
    save(run/'report'/f'{label}_joint_covariance.json',dict(names=result['names'],covariance=result['covariance'],units='unscaled probability coefficients; waiting time in days'))
    if primary:shutil.copyfile(out/'reproduction.json',run/'report/model5_reproduction.json')
    return out,infl

def cem_scores(d,y,cells):
    """ATT in overlapping CEM strata, with estimated-control-mean influence."""
    _,g=np.unique(cells,return_inverse=True);ng=int(g.max())+1
    n1=np.bincount(g,weights=d,minlength=ng);n0=np.bincount(g,weights=1-d,minlength=ng)
    keep=(n1[g]>0)&(n0[g]>0);N1=float(d[keep].sum())
    require(N1>0,'No CEM overlap')
    total0=np.bincount(g,weights=(1-d)*y,minlength=ng)
    mu0=np.divide(total0,n0,out=np.zeros(ng),where=n0>0)
    ratio=np.divide(n1,n0,out=np.zeros(ng),where=n0>0)
    beta=float(np.sum(d[keep]*(y[keep]-mu0[g[keep]]))/N1)
    influence=np.where(keep,(d*(y-mu0[g]-beta)+(1-d)*ratio[g]*(mu0[g]-y))/N1,0.)
    return beta,influence,dict(overlap_rows=int(keep.sum()),treated_total=int(d.sum()),treated_overlap=int(N1),
        overlap_cells=int(((n1>0)&(n0>0)).sum()),control_weight_max=float(ratio[(n1>0)&(n0>0)].max()))

def matched(a,run,conf,source,label):
    def prep(tmp):
        con=sql(tmp,3.)
        try:
            view(con,'q',source)
            fields=['month_code','tc_base_s','tc_inc_s','floor((recipient_rating+opponent_rating)/400)',
                    'floor((opponent_rating-recipient_rating)/100)',
                    'CASE WHEN eval_cp<=-1000 THEN 0 WHEN eval_cp<=-300 THEN 1 WHEN eval_cp< -100 THEN 2 WHEN eval_cp<=100 THEN 3 WHEN eval_cp<=300 THEN 4 WHEN eval_cp<=1000 THEN 5 ELSE 6 END',
                    'sign(draw_payoff)']
            c.ensure(con,'SELECT count(*) FROM q WHERE eval_cp IS NULL OR NOT isfinite(eval_cp) OR draw_payoff IS NULL OR NOT isfinite(draw_payoff)','Missing matching state')
            copy(con,'SELECT row_id,recipient_id,opponent_id,archive_start_ms//86400000 AS date,received,dense_rank() OVER(ORDER BY '+','.join(fields)+')::BIGINT AS cell,'+','.join(OUTCOMES[:8])+' FROM q ORDER BY row_id',tmp/'matching.parquet')
        finally:con.close()
    prepared=stage(run/'PRIVATE/match_inputs'/label,conf,prep,[source])
    def fit_match(tmp):
        path=prepared/'matching.parquet';d=col(path,'received').astype(float);cells=col(path,'cell');points={};out={}
        for name in ['grant_lost','grant_comp','reach_lost','reach_comp','first_either_grant_comp','first_either_grant_lost']:
            points['matched_'+name],out['matched_'+name],meta=cem_scores(d,col(path,name).astype(float),cells)
        actors={k:col(path,k) for k in ['row_id','recipient_id','opponent_id','date']}
        pq.write_table(pa.table({**actors,**out}),tmp/'influence_PRIVATE.parquet',compression='zstd')
        names=list(points);del out,actors,d,cells;gc.collect()
        V=covariance(tmp/'influence_PRIVATE.parquet',names,run/'PRIVATE/match_covariance'/label)
        rows=[dict(exposure_type=label,term=name,estimand='CEM ATT association',**meta,**inference(points[name],V[k,k],100)) for k,name in enumerate(names)]
        g=np.zeros(len(names));g[names.index('matched_grant_lost')]=1;g[names.index('matched_grant_comp')]=-1
        rows.append(dict(exposure_type=label,term='matched_lost_minus_comp',estimand='CEM ATT association',**meta,**inference(points['matched_grant_lost']-points['matched_grant_comp'],g@V@g,100)))
        save(tmp/'result.json',rows)
    out=stage(run/'PRIVATE/matched'/label,conf,fit_match,[prepared/'POSITION_DONE.json'])
    table(run/'report'/f'{label}_matched.csv',load(out/'result.json'));return out

def full_comparison(run,conf,main,lost):
    # Cross-exposure covariance retains shared accounts/dates. Row IDs are cohort-local.
    def build(tmp):
        con=sql(tmp);queries=[];points=[];names=['CC','CL','LC','LL']
        try:
            for k,(fitdir,infl) in enumerate([main,lost]):
                r=load(fitdir/'result.json');p=r['points'];points += [p['iv_grant_comp'],p['iv_grant_lost']]
                fields=['recipient_id','opponent_id','date']
                for j,name in enumerate(names):fields.append((('iv_grant_comp' if j%2==0 else 'iv_grant_lost') if j//2==k else '0.0')+' AS '+name)
                queries.append('SELECT '+','.join(fields)+' FROM '+c.parq([infl/'influence_PRIVATE.parquet']))
            copy(con,' UNION ALL '.join(queries),tmp/'stack.parquet')
        finally:con.close()
        V=covariance(tmp/'stack.parquet',names,run/'PRIVATE/cross_covariance')
        rows=[dict(exposure_type='competitive' if k<2 else 'lost',outcome='competitive' if k%2==0 else 'lost',**inference(p,V[k,k],100)) for k,p in enumerate(points)]
        contrasts=[]
        for label,g in [('lost_receipt_minus_comp_receipt_on_comp',[-1,0,1,0]),('lost_receipt_minus_comp_receipt_on_lost',[0,-1,0,1]),('difference_in_outcome_differences',[1,-1,-1,1])]:
            g=np.asarray(g);contrasts.append(dict(contrast=label,**inference(g@points,g@V@g,100)))
        save(tmp/'result.json',dict(cells=rows,contrasts=contrasts,names=names,covariance=V.tolist()))
        (tmp/'stack.parquet').unlink()
    out=stage(run/'PRIVATE/full_comparison',conf,build,[x/'POSITION_DONE.json' for pair in [main,lost] for x in pair])
    r=load(out/'result.json');table(run/'report/two_by_two.csv',r['cells']);table(run/'report/two_by_two_contrasts.csv',r['contrasts']);save(run/'report/two_by_two_covariance.json',r)
