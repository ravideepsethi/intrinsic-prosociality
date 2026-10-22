"""Aggregate summaries and scientific figures; no account IDs in reports."""
from common import *
from design import MODELS

def score_comparisons(scores,seed=2026092602):
    out=[];status=[];rng=np.random.default_rng(seed)
    for (state,comparison),s in scores.groupby(['state','comparison']):
        if s.training_status.ne('ESTIMATED').any() or not np.isfinite(s.loglik).all():
            status.append(dict(state=state,comparison=comparison,status='FIT_FAILURE',compatible_models=[]));continue
        p=s.pivot(index='month',columns='model',values='loglik')
        if set(p.columns)!=set(MODELS) or len(p)!=12 or p.isna().any().any() or s.informative_groups.sum()==0:
            status.append(dict(state=state,comparison=comparison,status='INSUFFICIENT_COMMON_VALIDATION',compatible_models=[]));continue
        best=p.sum().idxmax();retained=[]
        for model in p.columns:
            v=(p[best]-p[model]).to_numpy();se=v.std(ddof=1)/np.sqrt(len(v))
            if model==best or v.mean()<=2*se:retained.append(model)
        status.append(dict(state=state,comparison=comparison,status='COMPARED',compatible_models=retained,
            unique_selection=retained[0] if len(retained)==1 else 'INDISTINGUISHABLE',highest_total_score=best,
            interpretation='Same frozen descriptive two-monthly-SE rule; not a familywise model-truth test'))
        for i,a in enumerate(p.columns):
            for b in p.columns[i+1:]:
                v=(p[a]-p[b]).to_numpy();boot=v[rng.integers(0,len(v),size=(2000,len(v)))].mean(axis=1)
                out.append(dict(state=state,comparison=comparison,model_a=a,model_b=b,months=len(v),
                    mean_month_logscore_difference=v.mean(),se=v.std(ddof=1)/np.sqrt(len(v)),
                    lo=np.quantile(boot,.025),hi=np.quantile(boot,.975),
                    interpretation='Monthly conditional log-score units, not percentage-point effects; 12-month descriptive uncertainty'))
    return out,status

def training_comparisons(scores):
    a=scores[scores.comparison.eq('original_train_rd110_test')]
    b=scores[scores.comparison.eq('rd110_train_rd110_test')]
    j=a.merge(b,on=['state','model','month','fold'],suffixes=('_original','_capped'),validate='one_to_one')
    for field in ('rows','informative_rows','informative_groups','grants'):
        if not (j[field+'_original']==j[field+'_capped']).all():raise RuntimeError('Common validation support differs')
    j['refitting_gain']=j.loglik_capped-j.loglik_original
    rows=[]
    for (state,model),s in j.groupby(['state','model']):
        v=s.refitting_gain.to_numpy();valid=np.isfinite(v).all() and len(v)==12
        rows.append(dict(state=state,model=model,months=len(v),mean_month_gain=v.mean() if valid else None,
            se=v.std(ddof=1)/np.sqrt(len(v)) if valid else None,
            total_gain=v.sum() if valid else None,
            interpretation='Capped training minus original training, evaluated on identical RD<=110 test rows/groups'))
    return j,pd.DataFrame(rows)

def repair_original_counts(report):
    for p in sorted((ROOT/'authority').glob('*_cost_or_bundle.parquet')):
        name=p.stem.removesuffix('_cost_or_bundle');f=pd.read_parquet(p)
        s=pd.read_parquet(ROOT/'authority'/(name+'_support.parquet')).set_index('window')
        for window,index in f.groupby('window').groups.items():
            a=s.loc[window]
            if not (f.loc[index,'grants']==100*a.grants).all() or not (f.loc[index,'n']==a.n).all():
                raise RuntimeError('Unexpected original cost count structure')
            f.loc[index,'grants']=int(a.grants)
        f['scope_note']='Original coefficients unchanged; grant counts corrected. Original IQR/elasticity normalizations include singleton eligible accounts.'
        table(f,Path(report)/'prior_reporting_corrections'/(name+'_cost_or_bundle_corrected.parquet'))

def collapsed_curves(d,y,tolerance=1e-5):
    groups=[]
    for model,x in d.groupby('model',sort=False):
        x=x.sort_values('gap');placed=False
        for item in groups:
            ref=item['data']
            if np.array_equal(x.gap.to_numpy(),ref.gap.to_numpy()) and np.allclose(x[y],ref[y],rtol=0,atol=tolerance):
                item['models'].append(model);placed=True;break
        if not placed:groups.append(dict(models=[model],data=x))
    return groups

def make_figures(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report=Path(report);plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    names={'cost':'Cost','curved':'Curved utility','loss':'Loss aversion','framing':'Draw framing',
           'strength':'Gap','strength_loss':'Gap + loss','strength_framing':'Gap + framing'}
    def plot(ax,d,y):
        for item in collapsed_curves(d,y):
            x=item['data'];label=' / '.join(names[m] for m in item['models'])
            ax.plot(x.gap,x[y],label=label,lw=1.7)
        ax.axhline(0,color='gray',lw=.6);ax.axvline(0,color='gray',lw=.6)
        ax.set_xlabel('Opponent minus chooser rating');ax.legend(frameon=False,fontsize=7)
    prior=pd.read_parquet(ROOT/'authority/regular_equal_predicted_gap_profiles.parquet')
    fig,ax=plt.subplots(figsize=(7.5,4.8));plot(ax,prior,'pp_difference')
    ax.set_ylabel('Model-predicted contrast (pp)');ax.set_title('Prior primary predictions: coincident curves combined')
    fig.text(.08,.015,'Conditional logit with additional baseline calibration; these are not the full-sample LPM coefficients.',fontsize=8)
    fig.tight_layout(rect=(0,.055,1,1))
    for ext in ('png','pdf'):fig.savefig(report/('Figure_prior_M2_corrected.'+ext),dpi=180)
    plt.close(fig)
    p=report/'common_index_profiles.parquet'
    if not p.exists():return
    profiles=pd.read_parquet(p)
    for state,d in profiles.groupby('state'):
        fig,axes=plt.subplots(1,2,figsize=(11,4.6),sharex=True,sharey=True)
        for ax,cohort,title in zip(axes,['original','rd110'],['Original fitted models','Models fitted with both RDs <=110']):
            plot(ax,d[d.training==cohort],'index_difference');ax.set_title(title)
        axes[0].set_ylabel('Conditional index contrast relative to gap zero')
        fig.suptitle('Roughly equal positions' if state=='equal' else 'Clearly losing positions')
        fig.text(.06,.012,'Both panels use the same RD<=110 standardization rows. Units are index changes, not probability changes.',fontsize=8)
        fig.tight_layout(rect=(0,.05,1,.94))
        for ext in ('png','pdf'):fig.savefig(report/('Figure_common_index_'+state+'.'+ext),dpi=180)
        plt.close(fig)

def assemble(report):
    report=Path(report)
    for name in ('coefficients','heldout_scores','heldout_calibration','conditional_score_diagnostics','common_index_profiles'):
        paths=sorted((report/'models').glob('*/*/'+name+'.parquet'))
        if paths:
            rows=[pd.read_parquet(p) for p in paths]
            rows=[x for x in rows if 'status' not in x or len(x.columns)>1]
            if rows:table(pd.concat(rows,ignore_index=True),report/(name+'.parquet'))
    scores=pd.read_parquet(report/'heldout_scores.parquet')
    comparisons,status=score_comparisons(scores)
    table(comparisons,report/'model_comparisons.parquet');write(report/'MODEL_COMPARISON_STATUS.json',status)
    months,summary=training_comparisons(scores)
    table(months,report/'same_test_refitting_by_month.parquet');table(summary,report/'same_test_refitting_summary.parquet')
    calibration=pd.read_parquet(report/'heldout_calibration.parquet')
    if 'rows' in calibration:
        x=calibration.groupby(['state','comparison','model','gap_bin'],as_index=False)[['rows','observed_grants','predicted_grants']].sum()
        x['observed_rate_pp']=100*x.observed_grants/x.rows;x['predicted_rate_pp']=100*x.predicted_grants/x.rows
        x['residual_pp']=x.observed_rate_pp-x.predicted_rate_pp
        x['scope']='Identical informative held-out chooser-month groups; totals conditioned on, no marginal probability forecast'
        table(x,report/'heldout_gap_calibration.parquet')
    repair_original_counts(report);make_figures(report)
