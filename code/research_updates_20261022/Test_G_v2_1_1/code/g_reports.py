"""Aggregate-only reports and scientific figures; no manuscript mutations."""
from __future__ import annotations
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from g_common import *
from g_statistics import *

OUTPUTS=['tabGdata_inventory','tabGdata_ending_status','tabG0_engine_alignment','tabG1_calibration','tabG1_stability',
 'tabG1_exchange_rate','tabG1_marginal_effects','tabG1_ply_quotas','tabG2a_sufficiency_oos','tabG2a_sufficiency_insample',
 'tabG2a_stability','tabG2b_exchange_rate','tabG2c_state_contrast','tabG2d_clocks','tabG2e_stage_bands','tabG2f_by_group',
 'tabG3a_stakes_by_omega','tabG3b_path_given_omega','tabG_bootstrap_meta','tabG_robustness']

def default_meta(run,N=None,sample='All-state opportunities after ply 10; complete chooser histories'):
    fit=run/'g1/fit/META.json';m=load(fit)['meta'] if fit.exists() else {}
    return dict(N=N,sample=sample,source_months=m.get('source_months',MONTHS),ending_status_coverage=m.get('ending_status_coverage','Inventory pending'),
        outcome_units='Grant effects in percentage points; squared loss uses 0/1 responses',confidence='95% two-stage percentile bootstrap unless stated')
def fill_unrun(run,reason):
    for name in OUTPUTS:
        if not (run/'report'/(name+'.csv')).exists():table(run/'report',name,[dict(status='NOT_RUN',reason=reason)],default_meta(run))

def summary_row(name,point,records,prefix=None):
    selected=[r for r in records if name in r['statistics']] if name.startswith('logloss:') else records
    values=[r['statistics'].get(name,np.nan) for r in selected];lo,hi=interval(values)
    return dict(statistic=name if prefix is None else prefix,estimate=point.get(name,np.nan),ci_low=lo,ci_high=hi,replicates=len(values),unresolved_draws=int(np.sum(~np.isfinite(values))))

def write_results(run,point,records,exchange_info,mc,stopping,point_fits,templates):
    report=run/'report';N=int(point_fits['M0']['counts'][2]);meta=default_meta(run,N);bounds={k:interval([r['statistics'].get(k,np.nan) for r in records]) for k in point}
    mcmap={r['statistic']:r for r in mc}
    def resolved(*names):return all(mcmap.get(n,{}).get('simulation_resolved',False) for n in names)
    categories=dict(primary=sufficiency(bounds,resolved('MRU:gain','D10','D25')),
                    expected_score=sufficiency(bounds,resolved('MRUprime:gain','primeD10','primeD25'),'prime'))
    ll_bounds={};ll_resolved=True
    for name in ['MRU:gain','D10','D25']:
        selected=[r for r in records if 'logloss:'+name in r['statistics']];values=[r['statistics']['logloss:'+name] for r in selected]
        ci=interval(values);se=monte_carlo_endpoints(values,[r['family'] for r in selected]);ll_bounds[name]=ci
        ll_resolved &= all(np.isfinite(v) and np.isfinite(s) and abs(v)>2*s for v,s in zip(ci,se))
    categories['log_loss_secondary']=sufficiency(ll_bounds,ll_resolved)
    blocks={n:point[n] for n in point if n.startswith('added_test_gain:') and np.isfinite(point[n])}
    if blocks:categories['largest_estimated_raw_block']=max(blocks,key=blocks.get).split(':',1)[1]
    rows=[]
    for name in point:
        if name.startswith(('within:','Xr:','X_w:','X_eq:','G1_APE:','roughly_equal:','year2_groups:','partial_R2:','added_test_gain:','year1:','year2:','competitive:','unflagged:','random_holdout:')):continue
        if ':gap_' in name or ':clock_' in name or ':eval100_' in name or name.startswith('difference:'):continue
        row=summary_row(name,point,records);row['metric']='clipped log loss' if name.startswith('logloss:') else 'unclipped LPM squared error'
        row['primary_classification']=categories['primary'];row['expected_score_classification']=categories['expected_score'];row['log_loss_secondary_classification']=categories['log_loss_secondary'];rows.append(row)
    table(report,'tabG2a_sufficiency_oos',rows,dict(meta,N_test=int(point_fits['M0']['counts'][1]),S_R_untruncated=True,
        denominator_gate='Interpret S_R only when gain_MRU CI is strictly positive',Brier_definition='Mean squared error of the raw LPM prediction, unbounded; probability clipping is only for log loss'))
    inside=[summary_row(n,point,records) for n in point if n.startswith(('within:','partial_R2:','added_test_gain:'))]
    if (report/'MRU_WALD.json').exists():inside.append(dict(statistic='MU_terms_joint_chooser_CR1_Wald',**load(report/'MRU_WALD.json')))
    table(report,'tabG2a_sufficiency_insample',inside,dict(meta,partial_blocks='Overlapping partial tests: all interactions containing the named input are removed. Partials are not additive.'))
    for file,labels in [('tabG2c_state_contrast',['gap_competitive','gap_clearly_worse']),('tabG2d_clocks',['clock_competitive'])]:
        out=[]
        for label in labels:
            for m in ['MR','MU','MRprime']:out.append(dict(contrast=label,model=m,**summary_row(m+':'+label,point,records)))
            name='difference:'+label;margin=.05 if 'clearly_worse' in label else .10
            out.append(dict(contrast=label,model='MU minus MR',margin_pp=margin,reading=equivalence(bounds[name],(-margin,margin),resolved(name)),**summary_row(name,point,records)))
            pred=point['MR:'+label];pci=bounds['MR:'+label]
            if abs(pred)>.05 and (pci[0]>0 or pci[1]<0):
                values=[]
                for r in records:
                    den=r['statistics']['MR:'+label];num=r['statistics']['MU:'+label]
                    values.append(num/den if den!=0 and np.sign(den)==np.sign(pred) else np.nan)
                lo,hi=interval(values);out.append(dict(contrast=label,model='MU / MR',estimate=point['MU:'+label]/pred,ci_low=lo,ci_high=hi,
                    status='unresolved' if any(not np.isfinite(v) for v in values) else 'descriptive',unresolved_draws=sum(not np.isfinite(v) for v in values)))
        table(report,file,out,dict(meta,rating_counterfactual='Chooser rating fixed; opponent rating +100, mean rating +50; every derived feature rebuilt'))
    er=[]
    for name in point:
        if name.startswith(('X_w:','X_eq:')):
            field,cell,edge,stm=name.split(':');er.append(dict(cell=int(cell),rating_edge=int(edge),f_to_move=stm,definition=field,**summary_row(name,point,records)))
    er.append(dict(definition='pre-game descriptive reference, not a benchmark',rating_edge=100,estimate=156.,ci_low=np.nan,ci_high=np.nan,status='Fixed reference; not an estimated G1 quantity'))
    table(report,'tabG1_exchange_rate',er,default_meta(run,load(run/'g1/fit/META.json')['meta']['N'],'Completed-game outcome model; equal cell-median clocks'))
    for year in [1,2]:
        old=report/f'tabG1_exchange_rate_year{year}.csv'
        if old.exists():
            df=pd.read_csv(old,comment='#');out=[]
            for r in df.to_dict('records'):
                for field in ['X_w','X_eq']:
                    name=f'year{year}:{field}:{r["cell"]}:{r["rating_edge"]}:{r["f_to_move"]}'
                    lo,hi=interval([b['statistics'].get(name,np.nan) for b in records]);out.append(dict(cell=r['cell'],definition=field,rating_edge=r['rating_edge'],f_to_move=r['f_to_move'],estimate=r[field],ci_low=lo,ci_high=hi))
            table(report,f'tabG1_exchange_rate_year{year}',out,meta)
    table(report,'tabG1_marginal_effects',[summary_row(n,point,records) for n in point if n.startswith('G1_APE:')],dict(meta,sample='Context medians, opponent to move',effect_units='Win/draw/loss probability'))
    exrows=[]
    for cc in templates.cell:
        for name in [f'Xr:{cc}',f'X_w:{cc}:100:0']:
            exrows.append(dict(cell=int(cc),included_in_R=int(cc) in exchange_info['cells'],resolved_share=float(np.mean([np.isfinite(r['statistics'].get(name,np.nan)) for r in records])),**summary_row(name,point,records)))
    for key,values in [('R',exchange_info['draws']),('slope',exchange_info['slope_draws']),('intercept',exchange_info['intercept_draws'])]:
        lo,hi=interval(values)
        reading='Descriptive; no EIV equivalence claim'
        if key=='R':
            reading='inconclusive' if exchange_info['status']=='unresolved' or not np.isfinite([lo,hi]).all() else 'unresolved by simulation' if not resolved('R') else 'similar' if lo>=.8 and hi<=1.25 else 'undervalue' if hi<.8 else 'overvalue' if lo>1.25 else 'inconclusive'
            categories['exchange_rate']=reading
        exrows.append(dict(statistic=key,estimate=exchange_info[key],ci_low=lo,ci_high=hi,status=exchange_info['status'],opportunity_coverage=exchange_info['coverage'],reading=reading))
    eiv_values=exchange_info['eiv_slope_draws'];elo,ehi=interval(eiv_values)
    emc=monte_carlo_endpoints(eiv_values,[r['family'] for r in records])
    exrows.append(dict(statistic='EIV_corrected_slope',estimate=exchange_info['eiv_slope'],ci_low=elo,ci_high=ehi,
        Xw_reliability=exchange_info['eiv_reliability'],centered_Xw_error_variance=exchange_info['eiv_centered_error_variance'],mcse_low=emc[0],mcse_high=emc[1],
        status='estimated' if np.isfinite([elo,ehi,exchange_info['eiv_slope']]).all() else 'unresolved',
        reading='Secondary known-variance plug-in slope/reliability. Classical EIV assumptions required; correlated Xr/Xw estimation errors are not corrected. No automatic tracking equivalence claim.'))
    table(report,'tabG2b_exchange_rate',exrows,dict(meta,unresolved_roots='Retained via conservative infinite endpoint bounds; never discarded',fixed_weights='First 50 G1 draws; 1/(var_Xr+var_Xw)'))
    table(report,'tabG2e_stage_bands',[summary_row(n,point,records) for n in point if n.startswith('roughly_equal:')],dict(meta,sample='Roughly equal positions; stage 41–80 reference',prediction_comparison='Held-out rows; in-sample stage-fit equality is not evidence'))
    table(report,'tabG2f_by_group',[summary_row(n,point,records) for n in point if n.startswith('year2_groups:')],dict(meta,sample='P2 competitive after ply 10; P1 groups require >=4 competitive and >=4 clearly-worse opportunities',group_codes={0:'CO',1:'BOTH',2:'LO',3:'NEI'},response_units='Marginal response per 0.10 increase of the index, and share of group base rate'))
    table(report,'tabG_robustness',[summary_row(n,point,records) for n in point if n.startswith(('competitive:','unflagged:','random_holdout:'))],meta)
    meta_rows=[dict(kind='precision_endpoint',**r) for r in mc];meta_rows.append(dict(kind='run',G1_draws=len({r['family'] for r in records}),combined_replicates=len(records),stopping_reason=stopping))
    if (report/'ACCOUNT_OVERLAP.json').exists():meta_rows.append(dict(kind='account_overlap',**load(report/'ACCOUNT_OVERLAP.json')))
    if (report/'BOOTSTRAP_PILOT.json').exists():meta_rows.append(dict(kind='timing',**load(report/'BOOTSTRAP_PILOT.json')))
    table(report,'tabG_bootstrap_meta',meta_rows,meta)
    save(report/'READING.json',dict(categories=categories,exchange_status=exchange_info['status'],CAVEAT=CAVEAT,conditional_manuscript_changes_only=True))
    plots(report,er,exrows,point,records)

def plots(report,er,exrows,point,records):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    primary=[r for r in er if r.get('definition')=='X_w' and r.get('rating_edge')==100 and str(r.get('f_to_move'))=='0']
    fig,ax=plt.subplots(figsize=(8,4))
    good=[r for r in primary if np.isfinite(r['estimate']) and np.isfinite(r['ci_low']) and np.isfinite(r['ci_high'])]
    if good:
        x=np.array([r['cell'] for r in good]);y=np.array([r['estimate'] for r in good]);lo=np.array([r['ci_low'] for r in good]);hi=np.array([r['ci_high'] for r in good])
        ax.vlines(x,lo,hi,color='#7d96b2',linewidth=1);ax.scatter(x,y,s=14,color='#183c64')
    else:ax.text(.5,.5,'Exchange rates unresolved',ha='center',transform=ax.transAxes)
    ax.set(xlabel='Context cell',ylabel='Chooser evaluation advantage (cp)',title='Outcome exchange rate: 100 rating points, opponent to move');fig.tight_layout();fig.savefig(report/'figG1_exchange_rate.pdf');plt.close(fig)
    fig,ax=plt.subplots(figsize=(5,5));xs=[];ys=[];rowmap={r.get('statistic'):r for r in exrows}
    for k in point:
        if k.startswith('Xr:'):
            cc=k.split(':')[1];x=point.get(f'X_w:{cc}:100:0',np.nan);y=point[k]
            if np.isfinite(x+y):
                xs.append(x);ys.append(y);rx=rowmap.get(f'X_w:{cc}:100:0',{});ry=rowmap.get(k,{})
                if np.isfinite([rx.get('ci_low',np.nan),rx.get('ci_high',np.nan),ry.get('ci_low',np.nan),ry.get('ci_high',np.nan)]).all():
                    ax.hlines(y,rx['ci_low'],rx['ci_high'],color='#7d96b2',alpha=.3,lw=.7);ax.vlines(x,ry['ci_low'],ry['ci_high'],color='#7d96b2',alpha=.3,lw=.7)
    if xs:
        ax.scatter(xs,ys,s=18,color='#183c64',alpha=.7);lim=[min(xs+ys),max(xs+ys)];ax.plot(lim,lim,'--',color='#999999')
    else:ax.text(.5,.5,'No jointly resolved cells',ha='center',transform=ax.transAxes)
    ax.set(xlabel='Outcome exchange rate Xw (cp)',ylabel='Granting exchange rate Xr (cp)',title='Revealed versus outcome trade-off');fig.tight_layout();fig.savefig(report/'figG2b_revealed_vs_outcome.pdf');plt.close(fig)
    fig,ax=plt.subplots(figsize=(6,4));labels=['11–20','21–40','41–80','81–120','121+']
    for field,label,color in [('observed_oos_pp','Observed','#183c64'),('predicted_oos_pp','MR prediction','#ce7939')]:
        values=[point.get(f'roughly_equal:MR:stage{k}:{field}',np.nan) for k in range(5)];ax.plot(range(5),values,'o-',label=label,color=color)
        for k in range(5):
            name=f'roughly_equal:MR:stage{k}:{field}';lo,hi=interval([r['statistics'].get(name,np.nan) for r in records])
            if np.isfinite([lo,hi]).all():ax.vlines(k,lo,hi,color=color,lw=1)
    ax.set_xticks(range(5),labels);ax.set(xlabel='Ply band',ylabel='Grant rate (pp)',title='Roughly equal positions: held-out opportunities');ax.legend(frameon=False);fig.tight_layout();fig.savefig(report/'figG2e_late_stage.pdf');plt.close(fig)
