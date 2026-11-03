"""Verified-input G3 adapters and estimators. Missing inputs remain explicit, never invented."""
from __future__ import annotations
import pickle
from scipy.special import expit,logit
from g_common import *
from g_design import *
from g_outcome import *
from g_fe import solve,within_forms,block_draw
from g_statistics import interval,monte_carlo_endpoints,equivalence

def import_optional(a,run,kind):
    if not a.optional_manifest:return None,'No authenticated optional-input manifest was supplied'
    manifest=load(a.optional_manifest);entry=manifest.get(kind)
    if not entry:return None,'No '+kind+' entry in optional-input manifest'
    path=Path(entry['path']).expanduser();require(path.is_file() and sha(path)==entry['sha256'],'Optional input checksum failed','OPTIONAL_INPUT_INTEGRITY_FAILURE')
    require(entry.get('whole_account_histories') is True and entry.get('source_reviewed') is True,'Optional histories or source provenance not certified','OPTIONAL_INPUT_UNREVIEWED')
    d=pd.read_parquet(path)
    needed={'game_id','chooser','chooser_name','opponent_name','y','vf','mate','dr','mean_r','clock_f','clock_g','base','inc','stm','ply','speed','month_code','premium','rd_c','rd_d','board','event_ms','archive_ordinal','group','engine_sha256','api_status'}
    require(needed<=set(d),'Optional schema missing: '+','.join(sorted(needed-set(d))),'OPTIONAL_SCHEMA_MISMATCH')
    require(d.game_id.is_unique and set(d.api_status)=={'timeout'} and (d.stm==0).all(),'Optional opportunity identity/status/orientation failed')
    expected=load(run/'report/ENGINE.json')['binary_sha256'];require(set(d.engine_sha256)=={expected},'Optional positions use another engine')
    d=d.loc[~d.chooser_name.str.lower().isin(AUTHORS)&~d.opponent_name.str.lower().isin(AUTHORS)&(d.ply>10)].copy()
    d=d.sort_values(['chooser','event_ms','archive_ordinal','game_id']).reset_index(drop=True);d['train']=True
    return d,None

def fe_logit(d,X,weights=None,maxiter=150):
    ids=d.chooser.to_numpy();start=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1];count=np.diff(np.r_[start,len(d)]);index=np.repeat(np.arange(len(start)),count)
    y=d.y.to_numpy(float);w0=np.ones(len(y)) if weights is None else np.asarray(weights,float);tot=np.add.reduceat(w0,start);events=np.add.reduceat(y*w0,start)
    active=(tot>0)&(events>0)&(events<tot);use=active[index]
    require(active.sum()>1,'No identifying mixed-outcome chooser histories in G3a','G3A_NO_IDENTIFYING_ACCOUNTS')
    if not use.all():return fe_logit(d.loc[use].reset_index(drop=True),X[use],w0[use],maxiter)
    alpha=logit(np.clip(events/tot,1e-8,1-1e-8));b=np.zeros(X.shape[1]);previous=np.inf
    for iteration in range(maxiter):
        eta=alpha[index]+X@b;p=expit(eta);w=w0*np.maximum(p*(1-p),1e-12);r=w0*(y-p)
        sw=np.add.reduceat(w,start);sx=np.add.reduceat(X*w[:,None],start,axis=0);sr=np.add.reduceat(r,start)
        H=X.T@(X*w[:,None])-sx.T@(sx/sw[:,None]);score=X.T@r-sx.T@(sr/sw)
        delta=np.linalg.pinv(H,rcond=1e-10)@score;da=(sr-sx@delta)/sw
        objective=float(np.sum(w0*(np.logaddexp(0,eta)-y*eta)));step=1.
        while step>1/2048:
            trial=alpha[index]+step*da[index]+X@(b+step*delta);value=float(np.sum(w0*(np.logaddexp(0,trial)-y*trial)))
            if value<=objective+1e-10:break
            step/=2
        b+=step*delta;alpha+=step*da
        if np.max(np.abs(score))/w0.sum()<1e-7 and np.max(np.abs(sr))/w0.sum()<1e-7:return b,dict(accounts=len(start),rows=len(d),iterations=iteration+1)
    raise GateError('G3A_LOGIT_NONCONVERGENCE','Chooser FE logit did not converge')

def arena_fit(d,model,arena_model=None,weights=None):
    probability=predict_chunks(model,d)
    if arena_model is not None:
        ix=d.arena.to_numpy(bool);probability[ix]=predict_chunks(arena_model,d.loc[ix])
    z=logit(np.clip(probability[:,0],PROB_CLIP,1-PROB_CLIP));base,names=baseline(d)
    X=np.column_stack([z,z*d.arena.to_numpy(),d.arena,base]);b,meta=fe_logit(d,X,weights)
    pool=b[0];arena=b[0]+b[1]
    return dict(pool_slope=pool,arena_slope=arena,difference=arena-pool,ratio=arena/pool if pool<0 else np.nan),meta

def path_fit(d,model,knots,weights=None):
    p=predict_chunks(model,d);base,names,_=g2_design(d,'MR',p[:,0],p[:,0]+.5*p[:,1],knots['knots'],knots['score_knots'])
    X=np.column_stack([base,d.opponent_own_move_gain_cp.to_numpy()/100,d.chooser_own_move_loss_cp.to_numpy()/100])
    _,z,_,blocks,_=within_forms(d,X);w=np.ones(len(d)) if weights is None else weights;fit=solve(z.T@(z*w[:,None]))
    cf=counterfactual(d,'eval100');q=predict_chunks(model,cf);base_cf=g2_design(cf,'MR',q[:,0],q[:,0]+.5*q[:,1],knots['knots'],knots['score_knots'])[0]
    effect=100*float(np.average((base_cf-base)@fit['beta'][:-2],weights=w));margin=.25*abs(effect)
    return dict(opponent_gain_pp_per100cp=100*fit['beta'][-2],chooser_loss_pp_per100cp=100*fit['beta'][-1],margin_pp=margin,
        opponent_lower=100*fit['beta'][-2]+margin,opponent_upper=100*fit['beta'][-2]-margin,
        chooser_lower=100*fit['beta'][-1]+margin,chooser_upper=100*fit['beta'][-1]-margin)

def run_g3(a,run,positions,g1,knots,merge):
    from g_reports import default_meta
    results={};point_positions=pd.read_parquet(positions);manifest=load(a.optional_manifest) if a.optional_manifest else {}
    for kind,file in [('arena_opportunities','tabG3a_stakes_by_omega'),('replay_opportunities','tabG3b_path_given_omega')]:
        d,reason=import_optional(a,run,kind)
        if d is None:
            table(run/'report',file,[dict(status='NOT_RUN_MISSING_VERIFIED_INPUT',reason=reason)],default_meta(run));results[kind]='missing input';continue
        arena=kind.startswith('arena');arena_model=None;arena_data=None
        if arena:
            require({'arena','berserk'}<=set(d),'Missing arena/berserk fields')
            d=d.loc[(d.board>=-100)&~d.berserk].copy();eligible=d.groupby('chooser').arena.nunique();d=d.loc[d.chooser.isin(eligible.index[eligible==2])].reset_index(drop=True)
            entry=manifest.get('arena_completed')
            if not entry:
                table(run/'report',file,[dict(status='NOT_RUN_MISSING_VERIFIED_INPUT',reason='Arena completed-game calibration sample missing')],default_meta(run,len(d)));results[kind]='missing arena calibration';continue
            source=Path(entry['path']);require(sha(source)==entry['sha256'],'Arena completed checksum failure');arena_data=pd.read_parquet(source)
            require({'ending_basis','api_status','engine_sha256','white','black','test','weight','outcome','ply_bin'}<=set(arena_data),'Arena completed schema incomplete')
            require(set(arena_data.api_status)<=ORDINARY_STATUS and set(arena_data.engine_sha256)=={load(run/'report/ENGINE.json')['binary_sha256']},'Arena calibration ending/engine provenance failed')
            arena_data=arena_data.loc[~arena_data.white.isin(AUTHORS)&~arena_data.black.isin(AUTHORS)].copy()
            cal,passed=calibration(g1,arena_data,arena_data.test.to_numpy(),merge,'arena validation')
            if not passed:
                arena_model=fit_outcome(arena_data,run/'g3/arena_fit',g1.kind);cal,passed=calibration(arena_model,arena_data,arena_data.test.to_numpy(),merge,'arena refit')
            table(run/'report','tabG3a_calibration',cal,default_meta(run,len(arena_data),'Arena completed games'))
            if not passed:
                table(run/'report',file,[dict(status='NOT_RUN_CALIBRATION_FAILED')],default_meta(run,len(d)));results[kind]='calibration failed';continue
            point,info=arena_fit(d,g1,arena_model)
        else:
            require({'opponent_own_move_gain_cp','chooser_own_move_loss_cp'}<=set(d),'Missing path fields')
            require(manifest[kind].get('path_units')=='centipawns' and manifest[kind].get('own_move_only') is True,'Unverified path units or move attribution')
            d=d.loc[d.mate==0].reset_index(drop=True);point=path_fit(d,g1,knots);info={}
        stats=[];families=[];work=run/'g3'/kind;work.mkdir(exist_ok=True,parents=True);precision=[]
        for family in range(a.max_g1_draws):
            saved=work/f'family_{family:04d}.json'
            if saved.exists():draws=load(saved);draws=[{k:float(v) for k,v in r.items()} for r in draws]
            else:
                model_file=run/'bootstrap/models'/f'g1_{family:04d}.pkl'
                if model_file.exists():
                    with model_file.open('rb') as f:model=pickle.load(f)
                else:model=fit_outcome(point_positions,run/'g1/fit'/g1.kind,g1.kind,multiplicity=bootstrap_games(point_positions,SEED+100000+family),warm=g1)
                am=None
                if arena_model is not None:am=fit_outcome(arena_data,run/'g3/arena_fit',g1.kind,multiplicity=bootstrap_games(arena_data,SEED+300000+family),warm=arena_model)
                blocks=np.array([(int(g)+1)*400+hash64(int(u),'account-blocks')%400 for u,g in zip(d.chooser,d.group)],int);draws=[]
                for inner in range(10):
                    weights=block_draw(SEED+100*family+inner)[blocks]
                    value=arena_fit(d,model,am,weights)[0] if arena else path_fit(d,model,knots,weights);draws.append(value)
                save(saved,draws)
            stats+=draws;families.extend([family]*len(draws))
            if (family+1)%50==0:
                names=['ratio','pool_slope'] if arena else ['opponent_lower','opponent_upper','chooser_lower','chooser_upper'];precision=[]
                for n in names:
                    vals=[v[n] for v in stats];ci=interval(vals);se=monte_carlo_endpoints(vals,families);thresholds=[.8,1.25] if n=='ratio' else [0]
                    ok=all(np.isfinite(v) and np.isfinite(s) and min(abs(v-t) for t in thresholds)>2*s for v,s in zip(ci,se));precision.append(dict(statistic=n,ci=ci,mcse=se,resolved=ok))
                if all(r['resolved'] for r in precision):break
        out=[]
        for name,value in point.items():
            vals=[r[name] for r in stats];lo,hi=interval(vals);out.append(dict(statistic=name,estimate=value,ci_low=lo,ci_high=hi,combined_replicates=len(stats)))
        save(run/'report'/('G3A_PRECISION.json' if arena else 'G3B_PRECISION.json'),precision)
        if arena:
            ratio=next(r for r in out if r['statistic']=='ratio');pool=next(r for r in out if r['statistic']=='pool_slope')
            invalid=np.mean([not np.isfinite(r['ratio']) for r in stats]);ratio['reading']=equivalence((ratio['ci_low'],ratio['ci_high']),(.8,1.25),all(r['resolved'] for r in precision)) if invalid<=.025 and pool['ci_high']<0 else 'unresolved denominator; report slopes and difference'
        else:
            bounds={r['statistic']:(r['ci_low'],r['ci_high']) for r in out};equiv=all(bounds[side+'_lower'][0]>0 and bounds[side+'_upper'][1]<0 for side in ['opponent','chooser'])
            out.append(dict(statistic='path_equivalence',reading='Both path effects inside the prespecified margin' if equiv and all(r['resolved'] for r in precision) else 'Inconclusive or outside margin'))
        table(run/'report',file,out,dict(default_meta(run,len(d)),**info));results[kind]='estimated'
    return results

ORDINARY_STATUS={'mate','resign','stalemate','draw','outoftime','variantend'}
