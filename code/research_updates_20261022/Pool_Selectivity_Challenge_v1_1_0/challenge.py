#!/usr/bin/env python3
"""A fixed, exploratory challenge to the returned v100 selectivity pilot."""
from __future__ import annotations
import argparse, concurrent.futures, fcntl, json, os, shutil, sys, time, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import scipy
import pyarrow
from scipy.optimize import minimize
from model import (unpack, objective, components, predict, fit_encoder, encode,
                   arrays, save_arrays, load_arrays, choose_fit)
from util import (require, log, binding, ready, certify, sha256_file, atomic_json,
                  atomic_text, csv_write)

PACKAGE = Path(__file__).resolve().parent
RIDGE = 1e-6

def verify_manifest(root, filename):
    hashes = {}
    for line in (root/filename).read_text().splitlines():
        h, name = line.split('  ', 1)
        p = root/name
        require(p.is_file() and sha256_file(p) == h, 'Checksum mismatch: '+str(p))
        hashes[name] = h
    return hashes

def authenticate_parent(parent):
    expected = json.loads((PACKAGE/'PARENT_AUTHORITY.json').read_text())
    report = parent/'report'
    require(sha256_file(report/'REPORT_MANIFEST.sha256') == expected['report_manifest_sha256'],
            'This package requires the returned v100 run 5de7829248590795.')
    verify_manifest(report, 'REPORT_MANIFEST.sha256')
    done = json.loads((report/'_SUCCESS.json').read_text())
    require(done['identity'] == expected['identity'] and done['selected_fits_converged'],
            'Parent run identity or convergence mismatch')
    config = json.loads((parent/'PRIVATE/RUN_CONFIG.json').read_text())
    require(binding(config) == done['identity'], 'Parent configuration identity mismatch')
    require(config['ridge'] == RIDGE, 'Parent penalty mismatch')
    path = parent/'PRIVATE/pilot_counts.parquet'
    require(ready(path, done['identity']), 'Missing authenticated pilot cache: '+str(path))
    return dict(identity=done['identity'], cache_sha256=sha256_file(path),
                report_manifest_sha256=expected['report_manifest_sha256'],
                sample_fingerprint=config['sample_fingerprint'])

def expand_level(fit, K, split_class):
    """Embed a K=3 level model exactly by splitting one component's mass."""
    P = len(fit['parameters']) - (2*fit['K'])
    a, t, b, lp = unpack(np.array(fit['parameters']), P, fit['K'], False)
    extra = K-len(a)
    require(extra >= 0, 'Cannot contract a mixture')
    w = np.exp(lp).copy()
    piece = w[split_class]/(extra+1)
    w[split_class] = piece
    w = np.r_[w, np.repeat(piece, extra)]
    aa = np.r_[a, np.repeat(a[split_class], extra)]
    return np.r_[aa, t[0], b, np.log(w[1:]/w[0])]

def fit_task(task):
    data_path, outpath, basefit, K, start_id, seed, maxiter, identity = task
    outpath = Path(outpath)
    if ready(outpath, identity):
        log('RESUME '+outpath.name)
        return str(outpath)
    d = load_arrays(Path(data_path)); P = d['X'].shape[1]
    rng = np.random.default_rng(seed)
    v = expand_level(basefit, K, start_id % 3)
    nested_objective = objective(v, d, K, False, RIDGE)[0]
    # Break exact duplicate components; all starts originate from an exact nesting.
    v[:K] += rng.normal(0, [.18, .45, .8, .3][start_id % 4], K)
    v[K] += rng.normal(0, .12)
    v[-(K-1):] += rng.normal(0, .12, K-1)
    bounds = [(-16.,3.)]*K + [(-12.,12.)] + [(-8.,8.)]*P + [(-10.,10.)]*(K-1)
    v = np.array([np.clip(x,lo+1e-6,hi-1e-6) for x,(lo,hi) in zip(v,bounds)])
    began = time.monotonic(); it = [0]
    def callback(_):
        it[0] += 1
        if it[0] % 100 == 0:
            log(f'{outpath.stem}: iteration {it[0]}')
    log('FIT '+outpath.name)
    opt = minimize(objective, v, args=(d,K,False,RIDGE), jac=True,
                   method='L-BFGS-B', bounds=bounds, callback=callback,
                   options=dict(maxiter=maxiter,maxfun=maxiter*3,ftol=1e-11,
                                gtol=2e-6,maxls=40,maxcor=20))
    require(np.isfinite(opt.fun) and np.isfinite(opt.x).all(), 'Nonfinite fit')
    _,_,ll,_ = components(opt.x,d,K,False)
    a,t,b,lp = unpack(opt.x,P,K,False)
    boundary = [j for j,(lo,hi) in enumerate(bounds)
                if min(abs(opt.x[j]-lo),abs(opt.x[j]-hi)) < 1e-4]
    result = dict(K=K,heterogeneous=False,seed=seed,start_id=start_id,
                  parameters=opt.x.tolist(),alpha=a.tolist(),theta=t.tolist(),
                  weights=np.exp(lp).tolist(),success=bool(opt.success),message=str(opt.message),
                  iterations=int(opt.nit),objective=float(opt.fun),
                  nested_parent_objective=float(nested_objective),
                  train_log_likelihood=float(ll.sum()),boundary_parameters=boundary,
                  gradient_max_abs=float(abs(objective(opt.x,d,K,False,RIDGE)[1]).max()),
                  elapsed_seconds=time.monotonic()-began)
    atomic_json(outpath,result); certify(outpath,identity)
    log(f'FINISHED {outpath.name}: converged={opt.success}, objective={opt.fun:.9f}')
    return str(outpath)

def paired_score(base, new, df, ids, mask, N):
    n = df.n.to_numpy()[mask]; g = df.g.to_numpy()[mask]; ix = ids[mask]
    if n.sum() == 0: return None
    p = new[mask]; q = base[mask]
    grant_gain = g*(np.log(p)-np.log(q))
    nongrant_gain = (n-g)*(np.log1p(-p)-np.log1p(-q))
    diff = np.bincount(ix,weights=grant_gain+nongrant_gain,minlength=N)
    ns = np.bincount(ix,weights=n,minlength=N); active = ns>0; m=int(active.sum())
    gain = float(diff.sum()/ns.sum())
    se = float(np.sqrt(m/(m-1)*np.sum((diff[active]-gain*ns[active])**2))/ns.sum()) if m>1 else None
    eq = diff[active]/ns[active]
    return dict(accounts=m,opportunities=int(n.sum()),grants=int(g.sum()),
                gain=gain,conditional_cluster_SE=se,
                conditional_CI_low=gain-1.96*se if se is not None else None,
                conditional_CI_high=gain+1.96*se if se is not None else None,
                equal_account_gain=float(eq.mean()),
                equal_account_SE=float(eq.std(ddof=1)/np.sqrt(m)) if m>1 else None,
                grant_contribution=float(grant_gain.sum()/n.sum()),
                nongrant_contribution=float(nongrant_gain.sum()/n.sum()))

def score_all(fits, tr, te, train_df, test_df, accounts, report):
    predictions={}; joints={}; posterior={}
    for name, fit in fits.items():
        predictions[name],joints[name],posterior[name]=predict(fit,tr,te)
    n=test_df.n.to_numpy();g=test_df.g.to_numpy();F=test_df.competitive.to_numpy()
    ids=te['ids']; N=len(accounts)
    train_grants=np.bincount(tr['ids'],weights=tr['g'],minlength=N)
    fair_grants=np.bincount(tr['ids'],weights=tr['g']*tr['F'],minlength=N)
    worse_grants=np.bincount(tr['ids'],weights=tr['g']*(1-tr['F']),minlength=N)
    fair=np.bincount(tr['ids'],weights=tr['n']*tr['F'],minlength=N)
    worse=np.bincount(tr['ids'],weights=tr['n']*(1-tr['F']),minlength=N)
    stages=test_df.cell.to_numpy()%8
    subgroups={
      'all':np.ones(len(n),bool),
      'train_at_least_8_each_region':(np.minimum(fair,worse)>=8)[ids],
      'train_zero_grants_in_modeled_regions':(train_grants==0)[ids],
      'train_positive_grants_in_modeled_regions':(train_grants>0)[ids],
      'train_grants_competitive_only':((fair_grants>0)&(worse_grants==0))[ids],
      'train_grants_clearly_worse_only':((fair_grants==0)&(worse_grants>0))[ids],
      'train_grants_both_regions':((fair_grants>0)&(worse_grants>0))[ids],
      'plies_le_10':stages<=3,
      'plies_11_40':(stages>=4)&(stages<=5),
      'plies_gt_40':stages>=6}
    regions={'all':np.ones(len(n),bool),'competitive':F==1,'clearly_worse':F==0}
    scores=[]; comparisons=[]
    for subgroup,sg in subgroups.items():
        for region,rg in regions.items():
            mask=sg&rg;nn=n[mask].sum()
            if not nn: continue
            for name,p in predictions.items():
                pp=p[mask];gg=g[mask];ns=n[mask]
                scores.append(dict(subgroup=subgroup,region=region,model=name,
                    accounts=int(np.unique(ids[mask]).size),opportunities=int(nn),
                    actual_rate=float(gg.sum()/nn),predicted_rate=float((ns*pp).sum()/nn),
                    log_loss=float(-(gg*np.log(pp)+(ns-gg)*np.log1p(-pp)).sum()/nn),
                    brier=float((gg*(1-pp)**2+(ns-gg)*pp**2).sum()/nn)))
            for baseline in ['level_K3','level_K4','level_K5']:
                row=paired_score(predictions[baseline],predictions['selectivity_K3'],test_df,ids,mask,N)
                comparisons.append(dict(subgroup=subgroup,region=region,
                   comparison='selectivity_K3 vs '+baseline,**row))
    csv_write(report/'heldout_scores.csv',scores)
    csv_write(report/'paired_gains.csv',comparisons)
    active=np.bincount(ids,weights=n,minlength=N)>0;joint_rows=[]
    for baseline in ['level_K3','level_K4','level_K5']:
        dd=joints['selectivity_K3'][active]-joints[baseline][active]
        joint_rows.append(dict(comparison='selectivity_K3 vs '+baseline,accounts=int(active.sum()),
            gain_per_account=float(dd.mean()),conditional_SE=float(dd.std(ddof=1)/np.sqrt(len(dd)))))
    csv_write(report/'joint_history_gains.csv',joint_rows)
    # Probabilistic membership, not hard psychological labels.
    information=[]
    for name,q in posterior.items():
        for group,keep in [('all',np.ones(N,bool)),('train_at_least_8_each_region',np.minimum(fair,worse)>=8),
                          ('train_zero_grants_in_modeled_regions',train_grants==0),
                          ('train_positive_grants_in_modeled_regions',train_grants>0)]:
            qq=q[keep]
            if not len(qq):continue
            entropy=-np.sum(qq*np.log(np.maximum(qq,1e-300)),axis=1)/np.log(q.shape[1])
            information.append(dict(model=name,group=group,accounts=len(qq),
                mean_normalized_entropy=float(entropy.mean()),
                mean_max_posterior=float(qq.max(axis=1).mean()),
                fraction_max_posterior_above_90pct=float((qq.max(axis=1)>.9).mean()),
                caution='High certainty can reflect a dominant prior component; not measurement reliability.'))
    csv_write(report/'posterior_diagnostics.csv',information)
    return scores, comparisons

def package_report(report, transfer, run_id):
    atomic_text(report/'REPORT_MANIFEST.sha256',''.join(
        sha256_file(p)+'  '+p.name+'\n' for p in sorted(report.iterdir())
        if p.is_file() and p.name!='REPORT_MANIFEST.sha256'))
    transfer.mkdir(parents=True,exist_ok=True)
    output=transfer/f'POOL_SELECTIVITY_CHALLENGE_RESULTS_v110_{run_id}.zip'
    partial=Path(str(output)+'.partial')
    with zipfile.ZipFile(partial,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,'report/'+p.name)
    os.replace(partial,output)
    atomic_text(Path(str(output)+'.sha256'),sha256_file(output)+'  '+output.name+'\n')
    return output

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--starts',type=int,default=4)
    parser.add_argument('--maxiter',type=int,default=900)
    args=parser.parse_args()
    require(1<=args.workers<=10 and args.starts>=3 and args.maxiter>=100,'Invalid settings')
    hashes=verify_manifest(PACKAGE,'PACKAGE_MANIFEST.sha256')
    parent=args.project_root/'output/pool_selectivity_pilot_v100_5de7829248590795'
    log('Authenticating the completed pilot and its cached account histories')
    lineage=authenticate_parent(parent)
    config=dict(version='1.1.0',parent=lineage,code=hashes,starts=args.starts,maxiter=args.maxiter,
                seed=20260920,ridge=RIDGE,
                dependencies={m.__name__:m.__version__ for m in [np,pd,scipy,pyarrow]})
    identity=binding(config);run_id=identity[:16]
    root=args.project_root/'output'/('pool_selectivity_challenge_v110_'+run_id)
    root.mkdir(parents=True,exist_ok=True)
    lock=(root/'.run.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This configuration is already running')
    private=root/'PRIVATE';report=root/'report'
    private.mkdir(exist_ok=True);report.mkdir(exist_ok=True)
    if (report/'_SUCCESS.json').exists():
        verify_manifest(report,'REPORT_MANIFEST.sha256')
        log('Completed run verified; repackaging')
        log('REPORT: '+str(package_report(report,args.transfer_root,run_id)));return
    atomic_json(private/'RUN_CONFIG.json',config)
    df=pd.read_parquet(parent/'PRIVATE/pilot_counts.parquet')
    train_df=df[df.period==0].copy();test_df=df[df.period==1].copy();del df
    accounts=np.sort(train_df.chooser.unique());spec=fit_encoder(train_df)
    X,names,_=encode(train_df,spec);TX,_,unknown=encode(test_df,spec)
    design=json.loads((parent/'report/MODEL_DESIGN.json').read_text())
    require(names==design['features'],'Feature design changed')
    expected_counts=pd.read_csv(parent/'report/pilot_sample_counts.csv').set_index('period')
    for period,frame in [(0,train_df),(1,test_df)]:
        expected=expected_counts.loc[period]
        require(frame.chooser.nunique()==expected['accounts'] and int(frame.n.sum())==expected['opportunities']
                and int(frame.g.sum())==expected['grants'], 'Pilot sample counts changed')
    tr=arrays(train_df,X,accounts);te=arrays(test_df,TX,accounts)
    original=json.loads((parent/'report/PILOT_FITS.json').read_text())
    original_scores=pd.read_csv(parent/'report/heldout_scores.csv')
    reproduction=[]
    for name,fit in original.items():
        p,_,_=predict(fit,tr,te)
        for region,mask in [('all',np.ones(len(p),bool)),('competitive',te['F']==1),('clearly_worse',te['F']==0)]:
            n=te['n'][mask];g=te['g'][mask];pp=p[mask]
            loss=float(-(g*np.log(pp)+(n-g)*np.log1p(-pp)).sum()/n.sum())
            old=float(original_scores[(original_scores.model==name)&(original_scores.region==region)].log_loss_per_opportunity.iloc[0])
            require(abs(loss-old)<1e-9,'Frozen parent predictions failed reproduction')
            reproduction.append(dict(model=name,region=region,parent_log_loss=old,recomputed_log_loss=loss))
    csv_write(report/'parent_reproduction.csv',reproduction)
    log('Reproduced both original models in all three scoring regions')
    data_path=private/'training_arrays.npz'
    if not ready(data_path,identity):save_arrays(data_path,tr);certify(data_path,identity)
    fits={'level_K3':original['level_only'],'selectivity_K3':original['selectivity']}
    attempts=[];warnings=[]
    tasks=[]
    for K in [4,5]:
        for start in range(args.starts):
            tasks.append((str(data_path),str(private/f'level_K{K}_start{start}.json'),
                original['level_only'],K,start,20260920+1009*K+101*start,args.maxiter,identity))
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        paths=list(pool.map(fit_task,tasks))
    for K in [4,5]:
        chosen,values=choose_fit([p for p in paths if Path(p).name.startswith(f'level_K{K}_')])
        fits[f'level_K{K}']=chosen
        if not chosen['success']:warnings.append(f'K={K}: no converged attempt')
        if chosen['boundary_parameters']:warnings.append(f'K={K}: selected fit touches a bound')
        if min(chosen['weights'])<.001:warnings.append(f'K={K}: selected component weight below 0.001')
        if chosen['objective']>original['level_only']['objective']+1e-6:
            warnings.append(f'K={K}: failed to improve on nested K=3 parent')
        finite_best=min(v['objective'] for v in values)
        if chosen['objective']>finite_best+1e-5:
            warnings.append(f'K={K}: an unconverged start has a materially better objective')
        for v in values:
            attempts.append(dict(model=f'level_K{K}',seed=v['seed'],converged=v['success'],
                iterations=v['iterations'],objective=v['objective'],train_log_likelihood=v['train_log_likelihood'],
                min_weight=min(v['weights']),boundary_parameters=len(v['boundary_parameters']),
                gradient_max_abs=v['gradient_max_abs']))
    if fits['level_K5']['objective']>fits['level_K4']['objective']+1e-6:
        warnings.append('K=5 selected objective is worse than K=4; inspect local solutions')
    csv_write(report/'optimizer_attempts.csv',attempts)
    atomic_json(report/'FITS.json',fits)
    csv_write(report/'parameter_counts.csv',[dict(model=name,K=fit['K'],
        total_parameters=len(fit['parameters']),common_controls=len(names),
        heterogeneity_parameters=len(fit['parameters'])-len(names)) for name,fit in fits.items()])
    scores,comparisons=score_all(fits,tr,te,train_df,test_df,accounts,report)
    atomic_json(report/'LINEAGE.json',config)
    atomic_json(report/'MODEL_DESIGN.json',dict(features=names,unknown=unknown,
        comparison='K3 selectivity versus K4 level-only: same parameter count',
        sensitivity='K5 level-only; no additional selectivity-model tuning',
        first_year='November 2023–October 2024',second_year='November 2024–October 2025',
        second_year_status='Already inspected during v100 review; this is exploratory, not a fresh confirmation.',
        uncertainty='SEs condition on fitted models; no refitting, model-search, or class-selection uncertainty.'))
    headline=[r for r in comparisons if r['subgroup']=='all' and r['region']=='all']
    atomic_text(report/'SUMMARY.md',
        '# Selectivity challenge — exploratory\n\n'
        'This reuses the original 100,000 pilot accounts and original training/test split. '
        'It reproduces the two original frozen forecasts, then fits K=4 and K=5 level-only models. '
        'K=4 level-only and K=3 selectivity have equal parameter counts. All starts are selected by the training objective.\n\n'
        'Read paired_gains.csv by board region, optimizer_attempts.csv, and parameter_counts.csv. '
        'Positive gains favor K=3 selectivity. Grant and non-grant contributions sum to the overall gain within each row. '
        'Subgroup definitions overlap; they are diagnostics, not independent tests.\n\n'
        'The same second-year pilot was already inspected. These are exploratory specification checks. '
        'A confirmation should use a frozen specification on disjoint accounts. Neither a positive gain nor three '
        'latent components establishes two independent psychological traits or economic primitives. '
        'Exposure-correlated heterogeneity and transient attention remain open alternatives.\n\n'
        'The cached histories and their receipts were checked against the completed parent run. '
        'The original 24 source parquets were not rehashed or rescanned. No identifiers are exported.\n\n'
        'Warnings: '+('; '.join(warnings) if warnings else 'none from numerical gates')+'\n')
    atomic_json(report/'_SUCCESS.json',dict(status='CHALLENGE_COMPUTATION_COMPLETE',identity=identity,
        warnings=warnings,all_selected_fits_converged=all(f['success'] for f in fits.values()),
        model_identification_certified=False,headline=headline))
    out=package_report(report,args.transfer_root,run_id)
    log('REPORT: '+str(out));log('Upload the report ZIP and its SHA-256 sidecar.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        log('STOPPED: '+str(exc));raise
