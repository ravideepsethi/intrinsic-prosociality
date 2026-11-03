"""Exit composition, class-specific entry outcomes, post-assignment checks."""
from r7_common import *
from r7_math import *
from r7_models import estimate

EXTRA=['moves_available','net_material_change_4ply','window_plies','opening_tag','move_missing_reason','fair_competitive']

def classify(d):
    n=len(d['row_id']);ply=np.asarray(d['ply_count'],float);delta=np.asarray(d['net_material_change_4ply'],float)
    have=np.array([v is True or v==1 for v in d['moves_available']],bool)&np.isfinite(delta)
    pb=np.full(n,'unavailable',dtype=object)
    good=np.isfinite(ply)&(ply>=0)
    pb[good]=np.asarray(['<=10','11-30','31-60','>60'],object)[np.searchsorted([10,30,60],ply[good],side='left')]
    mb=np.full(n,'unavailable',dtype=object)
    mb[have]=np.select([delta[have]<=-3,delta[have]<0,delta[have]==0],['<=-3','-2_to_-1','0'],default='>=+1')
    clock=np.asarray(d['disconnected_clock_last_obs_s'],float);initial=np.asarray(d['tc_base_s'],float)
    cg=np.isfinite(clock)&(clock>=0)&np.isfinite(initial)&(initial>0);cb=np.full(n,'unavailable',dtype=object)
    cb[cg]=np.where(clock[cg]/initial[cg]<.1,'<10pct','>=10pct')
    cp=np.asarray(d['engine_eval_cp_disconnected'],float);merit=np.full(n,'unavailable',dtype=object)
    ok=~np.isnan(cp)
    merit[ok]=np.select([cp[ok]<=-300,cp[ok]<-100,cp[ok]<=100,cp[ok]<300],['0','1','2','3'],default='4')
    swing=have&good&(delta<=-3)&(ply<=30)
    quiet=have&good&(delta==0)&(ply>30)&(cb=='>=10pct')
    typ=np.full(n,'other_observed',dtype=object);typ[~have]='unavailable';typ[swing]='swing';typ[quiet]='quiet'
    # Share category strings instead of allocating one joint string per row.
    dimensions=[pb,mb,merit,cb];labels=[];code=np.zeros(n,np.int64);stride=1
    for values in dimensions:
        label,ix=np.unique(values,return_inverse=True);labels.append(label)
        code+=stride*ix;stride*=len(label)
    unique,inverse=np.unique(code,return_inverse=True);names=[]
    for value in unique:
        parts=[]
        for label in labels:parts.append(label[value%len(label)]);value//=len(label)
        names.append('|'.join(parts))
    joint=np.asarray(names,object)[inverse]
    return dict(ply_band=pb,material_band=mb,merit_code=merit,clock_band=cb,exit_type=typ,
                joint_class=joint,swing=swing,quiet=quiet,moves_available=have)

def raw_traits(d):
    out={}
    for days in (90,30):
        f=np.asarray(d[f'fair_{days}'],float);k=np.asarray(d[f'kind_{days}'],float)
        out[f'kind_rate_{days}']=np.divide(k,f,out=np.zeros(len(f)),where=f>0)
        out[f'kind_ever_{days}']=(k>0).astype(float)
    out['log_disconnect_90']=np.log1p(d['disconnect_90'])
    out['prior_competitive_choice']=(np.asarray(d['fair_90'])>0).astype(float)
    return out

def classes_and_prior(d,sample):
    cls=classify(d);n=len(d['row_id']);rows=[];prior=[];meta=metadata(d,sample,'descriptive','pooled',units='count and share')
    values=raw_traits(d) if sample=='S0' else {}
    if sample=='S0':base_mask=np.ones(n,bool)
    else:base_mask=np.asarray(d['recipient_disconnect_main'],bool)
    total=int(base_mask.sum())
    dimensions=['ply_band','material_band','merit_code','clock_band','exit_type','joint_class']
    for dimension in dimensions:
        for value in sorted(np.unique(cls[dimension][base_mask])):
            m=base_mask&(cls[dimension]==value);count=int(m.sum())
            rows.append(dict(meta,dimension=dimension,class_value=value,class_n=count,denominator_n=total,share=count/total if total else None))
            if sample=='S0':
                for name,v in values.items():
                    scale=1 if name=='log_disconnect_90' else 100
                    prior.append(dict(meta,dimension=dimension,class_value=value,trait=name,class_n=count,
                        units='log count' if scale==1 else 'percentage points',mean=float(v[m].mean()*scale)))
    if sample=='S0':
        take=cls['swing']|cls['quiet']
        if cls['swing'].sum()>=10 and cls['quiet'].sum()>=10:
            dd=subset(d,take);x,names,_,groups=feature_design(dd,'NH');meat=covariance(dd)
            swing=cls['swing'][take].astype(float)
            for adjusted in (False,True):
                xx=x if adjusted else np.empty((len(swing),0));gg=groups if adjusted else [np.zeros(len(swing),np.int64)]
                keys=list(values);mat=np.column_stack([swing]+[values[k][take] for k in keys]);res=project(xx,mat,gg)[0]
                for j,name in enumerate(keys):
                    scale=1 if name=='log_disconnect_90' else 100;fit,_=scalar(res[:,j+1],res[:,0],meat,scale)
                    prior.append(dict(metadata(dd,sample,'NH' if adjusted else 'intercept_only','pooled'),
                        dimension='swing_minus_quiet',trait=name,units='log count' if scale==1 else 'percentage points',
                        full_S0_mean=float(values[name].mean()*scale),
                        difference_as_share_of_S0_mean=fit.get('coefficient',float('nan'))/values[name].mean() if values[name].mean() else None,**fit))
        else:prior.append(dict(meta,dimension='swing_minus_quiet',supported=False,reason='FEWER_THAN_TEN_SWING_OR_QUIET_ROWS'))
    return cls,rows,prior

def entry_models(d,cls):
    n=len(d['row_id']);disc=np.asarray(d['recipient_disconnect_main'],bool);entry=np.asarray(d['analysis_entry_90'],bool)
    if np.any(entry&~disc):raise RuntimeError('analysis_entry_90 is not a subset of recipient_disconnect_main')
    xs,names,unused_traits,groups=feature_design(d,'X0');del unused_traits
    zraw=d['adjusted_7d'];meat=covariance(d)
    z=project(xs,zraw[:,None],groups)[0][:,0];native=float(np.sqrt(np.mean(z*z)))
    meta=metadata(d,'F50','X0','pooled',native_residual_score_SD=native)
    specs=[('entry_partition','nonentry_recipient_disconnect')]
    for dimension in ('ply_band','material_band','merit_code','clock_band','exit_type','joint_class'):
        for value in sorted(np.unique(cls[dimension][disc])):
            specs.append((dimension,str(value)))
    for value in sorted(np.unique(cls['ply_band'][entry])):
        specs.append(('competitive_entry_by_ply',str(value)))
    rows=[]
    def class_mask(dimension,value):
        if dimension=='entry_partition':return disc&~entry
        if dimension=='competitive_entry_by_ply':return entry&(cls['ply_band']==value)
        return disc&(cls[dimension]==value)
    # Allocate just eight current outcomes, not one n-row mask for every class.
    for start in range(0,len(specs),8):
        batch=[(dimension,value,class_mask(dimension,value)) for dimension,value in specs[start:start+8]]
        Y=np.column_stack([b[2] for b in batch]).astype(float)
        ys=project(xs,Y,groups)[0]
        for k,(dimension,value,m) in enumerate(batch):
            events=int(m.sum());fit,_=scalar(ys[:,k],z,meat,100*SD['pooled'])
            if min(events,n-events)<10:fit.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            mean=events/n
            rows.append(dict(meta,dimension=dimension,class_value=value,events=events,outcome_mean_pp=100*mean,
                relative_percent_of_class_base=fit.get('coefficient_pp',float('nan'))/mean if mean else None,**fit))
        io.log(f'C3: {min(start+8,len(specs))}/{len(specs)} class outcomes finished')
        del ys,Y,batch,m,_
    return rows

def job(job):
    threads_one();no_network()
    def build(tmp):
        sample=job['sample'];d=load_fit_columns(job['input'],['moves_available','net_material_change_4ply','ply_count','engine_eval_cp_disconnected','disconnected_clock_last_obs_s']);cls,counts,prior=classes_and_prior(d,sample)
        out={k:[] for k in TABLES};out['C_classes']=counts;out['C_prior_by_class']=prior
        if sample=='F50':out['C_entry_by_class']=entry_models(d,cls)
        else:
            ply=np.asarray(d['ply_count'],float);swing_share=float(cls['swing'].mean())
            for label,mask in [('exclude_swing',~cls['swing']),
                               ('ply_gt30',ply>30),('ply_gt30_clock_ge10pct',(ply>30)&(cls['clock_band']=='>=10pct'))]:
                if label=='exclude_swing' and swing_share<.01:
                    out['C_restricted_iv'].append(dict(metadata(d,'S0','X0','pooled'),restriction=label,supported=False,
                        reason='SWING_EXITS_UNDER_ONE_PERCENT_OF_FULL_S0',swing_share=swing_share));continue
                # Keep unavailable material histories separate. An influence check
                # restricted to known histories gets its own matched baseline.
                bases=[('known_move_baseline',cls['moves_available']),('known_moves_excluding_swing',cls['moves_available']&mask),('restricted_unknowns_retained',mask)] if label=='exclude_swing' else [('restricted',mask)]
                for variant,take in bases:
                    fit,_=estimate(subset(d,take),'iv','S0_'+label+'_'+variant,part_a=False)
                    for r in fit['B_estimates']+fit['B_joint_balance']:
                        out['C_restricted_iv'].append(dict(r,restriction=label,variant=variant,
                            post_assignment_influence_check=True,missing_move_rows=int((~cls['moves_available']).sum())))
        io.js(tmp/'result.json',out)
        relevant=np.ones(len(d['row_id']),bool) if sample=='S0' else d['recipient_disconnect_main'].astype(bool)
        io.js(tmp/'coverage.json',dict(sample=sample,relevant_rows=int(relevant.sum()),moves_available=int((cls['moves_available']&relevant).sum()),
             missing_move_rows=int((~cls['moves_available']&relevant).sum()),swing_rows=int((cls['swing']&relevant).sum()),
             swing_share=float(cls['swing'][relevant].mean()) if relevant.any() else None,
             clock_missing_rows=int(((cls['clock_band']=='unavailable')&relevant).sum()),
             complete_recorded_move_coverage=bool(cls['moves_available'][relevant].all())))
        return dict(rows=len(d['row_id']))
    return stable_stage(Path(job['output']),job['conf'],build,[job['input']])[1]
