"""Retained systems using the original R9b algebra and current bounded FWL."""
from common_retained import *

def fit_system(a,run,conf,label,src,scores,kind='compliers',act=None):
    require(kind in ('compliers','act'),'Only the two authorized system families may run')
    stat=frozen_systems();job=kernel.job_for(run,conf,label,src,scores,legacy=True)
    def build(tmp):
        extra={};D=col(src,'received').astype(float);description={}
        if kind=='compliers':
            speed=np.searchsorted([180,480,1500],col(src,'tc_base_s')+40*col(src,'tc_inc_s'),side='right')
            raw=dict(recipient_rating=col(src,'recipient_rating'),pre_games_30d=col(src,'pre_games_30d'),fair_90=col(src,'fair_90'),
              kind_ever_90=col(src,'kind_90')>0,no_fair_90=col(src,'fair_90')==0,disconnect_90=col(src,'disconnect_90'),receipt_90=col(src,'receipt_90'))
            raw.update({s+'_share':speed==k for k,s in enumerate(('bullet','blitz','rapid','classical'))})
            for k,v in raw.items():extra['product_'+k]=D*v;description[k]=dict(all_exposures=float(np.mean(v)),draw_recipients=float(np.mean(v[D==1])))
            del raw,speed
        elif kind=='act':
            require(np.array_equal(col(act,'row_id'),col(src,'row_id')),'Act features misaligned')
            board=col(act,'board_cp');require(np.all(board>=-100),'Noncompetitive act frame')
            band=np.searchsorted([0,100,300],board,side='right');g=col(act,'giver_cost');bval=col(act,'recipient_benefit')
            people=col(src,'recipient_id')
            for j in range(4):
                require(int(D[band==j].sum())>=20,'Act band has fewer than twenty receipts')
                for arm in (0,1):require(len(np.unique(people[(band==j)&(D==arm)]))>=30,'Act band has fewer than thirty recipients in one arm')
            description=dict(band_counts=[int((band==j).sum()) for j in range(4)],giver_cost_mean=float(g.mean()),recipient_benefit_mean=float(bval.mean()))
            mods=[(band==j).astype(float) for j in range(4)]+[(g-g.mean())/5,(bval-bval.mean())/5]
            z=col(scores,'adjusted_A')
            for j,v in enumerate(mods):extra['z_act_'+str(j)]=z*v;extra['d_act_'+str(j)]=D*v
            # Revised RA note: add only band indicators and centered stakes
            # to the headline controls. No extra board/clock/RD/ply controls.
            ctrl={'giver_cost_5':mods[4],'recipient_benefit_5':mods[5]}
            ctrl.update({'band_'+str(j):band==j for j in (1,2,3)})
        v,groups,actors,targets,meta,events=extended_buffer(job,tmp,extra)
        if kind=='act':
            # Move original standalone score and received/reached targets out of
            # the system (never add the standalone score as a nuisance control).
            w=kernel.disk.disk_matrix(tmp/'act_design.dat',len(v),v.shape[1]+len(ctrl))
            for j in range(v.shape[1]):w[:,j]=v[:,j]
            for j,(key,value) in enumerate(ctrl.items()):
                value=np.asarray(value,float);require(np.isfinite(value).all(),'Nonfinite act nuisance '+key)
                w[:,v.shape[1]+j]=(value-value.mean())/max(float(value.std()),1e-12)
            meta['controls']+=list(ctrl);del v;v=w
        res,rank,diag=kernel.project(v,groups,len(targets),tmp);del v,groups,extra;gc.collect()
        fields={k:res[:,j] for j,k in enumerate(targets)};meat=meat_factory(actors,tmp)
        meta.update(fit_meta(actors),sample=label,continuous_control_rank=rank,**description)
        rr=[];fs=[];system=[];compliers=[];contrasts=[]
        if kind=='act':
            Z=np.column_stack([fields['z_act_'+str(j)] for j in range(6)]);DD=np.column_stack([fields['d_act_'+str(j)] for j in range(6)])
            fs=stat.first_stage_system(DD,Z,meat)
            for outcome in ('y',):
                beta,V,info=stat.multi_iv(fields[outcome],DD,Z,meat);system.append(dict(meta,outcome=outcome,coefficients=beta.tolist(),covariance_matrix=V.tolist(),**info))
                terms=['band_'+str(j) for j in range(4)]+['giver_cost_per_5','recipient_benefit_per_5']
                weights={k:np.eye(6)[j] for j,k in enumerate(terms)};contrast=np.zeros(6);contrast[:2]=-np.array(description['band_counts'][:2])/sum(description['band_counts'][:2]);contrast[3]=1;weights['well_ahead_minus_near_equal']=contrast
                for k,w in weights.items():rr.append(dict(meta,outcome=outcome,term=k,**kernel.inference90(float(w@beta),float(w@V@w),100)))
        else:
            Z=fields['z'][:,None]
            dd=fields['received'];fs=stat.first_stage_system(dd,Z,meat)
            beta,V,info=stat.multi_iv(fields['y'],dd,Z,meat);system=[dict(meta,**info)]
            rr.append(dict(meta,term='iv_y',**kernel.inference90(beta[0],V[0,0],100)))
            if kind=='compliers':
                z=Z[:,0];den=float(z@dd);wt=z*D;neg=float(-wt[wt<0].sum()/wt.sum())
                for k,desc in description.items():
                    value=fields['product_'+k];beta=float(z@value)/den;infl=z*(value-beta*dd)/den;var=meat(infl)[0,0]
                    compliers.append(dict(meta,trait=k,**desc,negative_weight_absolute_mass_over_signed_total=neg,**kernel.inference90(beta,var)))
        for row in fs:row.update(fit_meta(actors),sample=label)
        save(tmp/'result.json',dict(estimates=rr,first_stages=fs,system=system,compliers=compliers,contrasts=contrasts))
        save(tmp/'numerical_diagnostics.json',diag)
        del res,fields,actors;clear_design(tmp);(tmp/'act_design.dat').unlink(missing_ok=True)
        return dict(rows=rows(src),kind=kind)
    out,_=stage(run/'PRIVATE/systems'/label,conf,build,[src,scores]+([act] if act else []));return out

def run_compliers(a,run,conf,auth):
    out=fit_system(a,run,conf,'spaced_compliers',Path(auth['paths']['spaced']),Path(auth['paths']['spaced_scores']),'compliers')
    result=read(out/'result.json');baseline=read(a.parent/'PRIVATE/models/legacy_spaced/result.json')
    got=result['estimates'][0];ref=next(r for r in baseline['estimates'] if r['term']=='iv_y')
    for k in ('coefficient','standard_error'):require(np.isclose(got[k],ref[k],rtol=2e-7,atol=2e-7),'Complier baseline does not reproduce: '+k)
    write_csv(run/'report/table_D6_complier_characteristics.csv',result['compliers'])
