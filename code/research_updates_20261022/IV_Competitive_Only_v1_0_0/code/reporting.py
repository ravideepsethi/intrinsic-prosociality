from common import *
import plots,shutil

FILTERS={'S0':'TRUE','S1':'comp_n>=5 AND isfinite(comp_z)',
         'S2':'comp_n>=5 AND isfinite(comp_z) AND non_n>=5 AND isfinite(non_z)',
         'S1_3':'comp_n>=3 AND isfinite(comp_z)'}

def descriptive(assembled,root,conf):
    def build(tmp):
        d=arrays(io.read(assembled/'iv.parquet'))
        masks={'S0':np.ones(len(d['row_id']),bool),'S1':(d['comp_n']>=5)&np.isfinite(d['comp_z']),
            'S2':(d['comp_n']>=5)&np.isfinite(d['comp_z'])&(d['non_n']>=5)&np.isfinite(d['non_z']),
            'S1_3':(d['comp_n']>=3)&np.isfinite(d['comp_z'])}
        masks.update(S0_minus_S1=~masks['S1'],S0_minus_S2=~masks['S2'],S1_minus_S2=masks['S1']&~masks['S2'])
        out=[]
        for name,m in masks.items():
            x=subset(d,m);n=int(m.sum());r=dict(sample=name,n=n)
            if n:
                _,cells=num.factor(x['month_code'],x['tc_base_s'],x['tc_inc_s'],np.floor((x['recipient_rating']+x['opponent_rating'])/200).astype(np.int64))
                reached=np.asarray(x['reached'],bool)
                r.update(recipients=len(np.unique(x['recipient_id'])),opponents=len(np.unique(x['opponent_id'])),cells=len(np.unique(cells)),
                    receipts=int(x['received'].sum()),receipt_rate_pp=100*float(x['received'].mean()),mean_Y_pp=100*float(x['y'].mean()),
                    reach_rate_pp=100*float(reached.mean()),mean_Y_given_reach_pp=100*float(x['y'][reached].mean()) if reached.any() else None,
                    **{f'mean_{k}':float(x[k].mean()) for k in ['n_7d','counterparts_7d','comp_n','non_n','comp_counterparts','non_counterparts','pre_games_30d']})
            out.append(r)
        scores=[]
        for tag,sample in [('comp','S1'),('non','S2')]:
            supported=(d[tag+'_n']>=5)&np.isfinite(d[tag+'_z']);m=masks[sample];z=d[tag+'_z'][m]
            r=dict(instrument=tag,distribution_sample=sample,supported_exposures_in_S0=int(supported.sum()),
                   supported_opponents_in_S0=len(np.unique(d['opponent_id'][supported])),
                   count_supported_but_nonfinite=int(((d[tag+'_n']>=5)&~np.isfinite(d[tag+'_z'])).sum()))
            if len(z):
                g=d[tag+'_grants'][m];_,ix=np.unique(d['opponent_id'][m],return_inverse=True)
                r.update(n=len(z),p10=float(np.quantile(z,.1)),p50=float(np.quantile(z,.5)),p90=float(np.quantile(z,.9)),
                    zero_grant_share_queries=float(np.mean(g==0)),
                    zero_grant_share_opponents_all_their_supported_query_histories_zero=float(np.mean(np.bincount(ix,weights=g>0)==0)))
                counts,edges=np.histogram(z,bins=40);plots.histogram(tmp/f'01_hist_{tag}.png',counts,edges,tag+' SCORE - '+sample)
                tables(tmp,'01_hist_'+tag,[dict(bin=k+1,left=float(edges[k]),right=float(edges[k+1]),exposures=int(v)) for k,v in enumerate(counts)])
            scores.append(r)
        m=masks['S2'];den=float(d['non_n'][m].sum())
        extra=dict(non_clearly_worse_share_exposure_history_weighted=float(d['non_clearly_worse_n'][m].sum())/den if den else None,
                   denominator='sum of non-competitive historical counts over S2 exposures; repeated histories reused',
                   comp_non_raw_correlation_S2=float(np.corrcoef(d['comp_z'][m],d['non_z'][m])[0,1]) if m.sum()>1 else None)
        io.js(tmp/'01_score_extra.json',extra);tables(tmp,'01_scores_summary',scores);tables(tmp,'02_samples',out)
        # Matched-placebo attrition is descriptive; no replacement rows.
        p=arrays(io.read(assembled/'placebo.parquet'));pm=(p['comp_n']>=5)&np.isfinite(p['comp_z']);pr=[]
        for name,mask in [('P0',np.ones(len(pm),bool)),('P1',pm),('P0_minus_P1',~pm)]:
            n=int(mask.sum());x=subset(p,mask);reach=np.asarray(x['reached'],bool)
            pr.append(dict(sample=name,n=n,recipients=len(np.unique(x['recipient_id'])),opponents=len(np.unique(x['opponent_id'])),
                mean_Y_pp=100*float(x['y'].mean()) if n else None,reach_rate_pp=100*float(reach.mean()) if n else None,
                mean_Y_given_reach_pp=100*float(x['y'][reach].mean()) if reach.any() else None))
        tables(tmp,'02_placebo_samples',pr);return dict(rows=len(d['row_id']))
    return stable(root,conf,build,[assembled/'iv.parquet',assembled/'placebo.parquet'])

def tex_escape(s):
    return str(s).replace('\\','\\textbackslash{}').replace('_','\\_').replace('%','\\%').replace('&','\\&').replace('#','\\#')
def fmt(v):return '' if v is None else str(v) if isinstance(v,str) else f'{v:.3f}'
def tex_panels(path,panels):
    lines=['% Generated aggregate table; three-decimal display, full precision in JSON/CSV.',r'\begin{tabular}{lrrrr}',r'\hline',r'Estimator & Estimate & SE & p & 95\% interval \\',r'\hline']
    for meta,rows,footer in panels:
        header=f"{meta.get('sample')} / {meta.get('control_family')} / {meta.get('instrument','')}; N={meta.get('n')}; recipients={meta.get('recipients')}; cells={meta.get('cells')}"
        lines.append(r'\multicolumn{5}{l}{'+tex_escape(header)+r'} \\')
        previous=None
        for r in rows:
            units=r.get('units','')
            if units!=previous:lines.append(r'\multicolumn{5}{l}{'+tex_escape(units)+r'} \\');previous=units
            ci=('['+fmt(r['ci_low'])+', '+fmt(r['ci_high'])+']') if r.get('ci_low') is not None else ''
            lines.append(' & '.join([tex_escape(r.get('estimator',r.get('trait',''))),fmt(r.get('estimate')),fmt(r.get('se')),fmt(r.get('p')),ci])+r' \\')
        if footer:
            ft='F='+str(round(footer['first_stage_F'])) if footer.get('first_stage_F') is not None else 'F='+str(footer.get('first_stage_F_style','NA'))
            if footer.get('partial_R2') is not None:ft+=f"; partial R2={footer['partial_R2']:.4f}"
            ar=footer.get('AR95_intervals_pp',footer.get('AR95',{}));ft+='; AR95 (pp): '+json.dumps(ar or footer.get('AR95_reason','not applicable'))
            lines.append(r'\multicolumn{5}{l}{\parbox{0.95\linewidth}{'+tex_escape(ft)+r'}} \\')
        lines.append(r'\hline')
    lines.append(r'\end{tabular}');Path(path).write_text('\n'.join(lines)+'\n')

def export(root,desktop,conf,results,subgroups,performance,status,started):
    report=root/'report';report.mkdir(exist_ok=True)
    for name in ('descriptive','prepared'):
        src=root/name
        if src.exists():
            for p in src.iterdir():
                if p.suffix in ('.csv','.json','.png') and p.name!='_DONE.json':shutil.copy2(p,report/p.name)
    shutil.copy2(ROOT/'SPECIFICATION.md',report/'00_definitions.md')
    tables(report,'performance',performance)
    allrows=[];bal=[];joints=[];bins=[];jointrows=[];meta=[];panels={k:[] for k in 'ABCDG'}
    for r in results:
        base={k:r.get(k) for k in ('sample','control_family','recipient_history_controls','n','recipients','cells','row_set_sha256')}
        meta.append({**base,'controls':r.get('controls'),'native_sds':r.get('native_sds'),'reference_sds':r.get('reference_sds'),
                     'raw_correlations':r.get('score_correlations_raw'),'residualized_correlations':r.get('score_correlations_residualized'),'correlation_order':r.get('correlation_order')})
        for row in r.get('rows',[]):allrows.append(dict(base,**row))
        bal += [dict(base,**v) for v in r.get('balance',[])];joints += [dict(base,**v) for v in r.get('joint_balance',[])]
        bins += [dict(base,**v) for v in r.get('binned',[])]
        if 'joint' in r:
            jointrows += [dict(base,**v) for v in r['joint'].get('conditional_firststage_and_RF',[])]
            io.js(report/('03_runD_inference_'+r['control_family']+'.json'),r['joint'])
        for tag in ('pooled','comp','non','both'):
            rows=[x for x in r.get('rows',[]) if x.get('instrument')==tag]
            if not rows:continue
            letter='G' if r['sample']=='P1' else {'pooled':'A','comp':'B','non':'C','both':'D'}[tag]
            footer=r.get('footers',{}).get(tag,{})
            if tag=='both':footer=dict(r.get('joint',{}).get('footer',{}),AR95=r.get('joint',{}).get('AR95',{}))
            panels[letter].append((dict(base,instrument=tag),rows,footer))
        if r.get('sample')=='S1' and r.get('recipient_history_controls'):
            for tag in ('pooled','comp'):
                rr=[x for x in r.get('binned',[]) if x['instrument']==tag]
                slope=next((x['estimate'] for x in r.get('rows',[]) if x.get('instrument')==tag and x.get('estimator')=='First stage: receipt' and x.get('units')=='pp per raw score unit'),None)
                if rr and slope is not None:plots.binned(report/f'04_runE_{tag}_{r["control_family"]}.png',rr,slope,tag+' FIRST STAGE - '+r['control_family'])
    for letter,ps in panels.items():
        name='06_runG_placebo' if letter=='G' else '03_run'+letter
        flat=[dict(m,**r) for m,rows,f in ps for r in rows];tables(report,name,flat);tex_panels(report/(name+'.tex'),ps)
    tables(report,'all_estimates',allrows);tables(report,'05_runF_balance',bal);tables(report,'05_runF_joint',joints)
    tables(report,'04_runE_bins',bins);tables(report,'07_runH_firststage_both',jointrows);tables(report,'08_runI_subgroups',subgroups)
    for name,rows in [('05_runF_balance',bal),('08_runI_subgroups',subgroups)]:
        tex_panels(report/(name+'.tex'),[({'sample':name},[dict(r,estimator=r.get('trait',r.get('label',''))+' '+r.get('adjustment','')) for r in rows],{})])
    io.js(report/'03_common_controls_manifest.json',meta)
    summaries=[]
    for p in sorted((root/'scores').glob('*/_DONE.json')):
        z=io.load(p);summaries.append({k:z.get(k) for k in ('rows','pooled_max_absolute_error','residual_sum_identity_max_absolute_error')})
    io.js(report/'01_score_identity_checks.json',summaries)
    summary=dict(status=status,version=VERSION,config_sha256=conf,elapsed_seconds=time.monotonic()-started,
        author_included=True,network_requests=0,stockfish_searches=0,chronology_scans=0,primary_changed=False,
        score_jobs=len(summaries),completed_model_jobs=len(results),subgroup_rows=len(subgroups),
        report_contains_individual_rows=False,confirmatory=False)
    io.js(report/'summary.json',summary)
    primary=next((r for r in results if r.get('sample')=='S1' and r.get('control_family')=='XC' and r.get('recipient_history_controls')),None)
    readme=[f'Status: {status}. This is a post-result instrument robustness analysis.']
    if primary:
        readme.append(f"Competitive-support S1: {primary.get('n'):,} rows; original S0 fixed at 2,682,330.")
        for name in ('First stage: receipt','Reduced form: later grant','2SLS'):
            row=next((x for x in primary.get('rows',[]) if x.get('instrument')=='comp' and x.get('estimator')==name and (name=='2SLS' or x.get('units')=='pp per reference residual SD')),None)
            readme.append(name+': '+(json.dumps(row,sort_keys=True) if row else 'unsupported'))
    else:readme+=['Core estimates pending.']*4
    readme+=['','No instrument is promoted based on these results. J non-rejection does not certify exclusion.',
        'Read 00_definitions.md, reproduction.json, 01_scores_summary.csv, 02_samples.csv, then runs A-D.',
        'X0 is the original controls; XC adds competitive history controls to EVERY instrument comparison.',
        'Intervals are nominal CR0 with historical scores fixed. Binned intervals condition on fitted residuals and bins.',
        'Private score CSV/Parquet remain in the assembled directory on the project drive.',
        'Unsupported statistics are reported with a reason; no covariance repair, row replacement or state-model refit.']
    (report/'README.txt').write_text('\n'.join(readme)+'\n')
    (report/'09_log.md').write_text('# Execution log\n\n'+json.dumps(summary,indent=2)+'\n\n## Stage timings\n\n'+json.dumps(performance,indent=2)+'\n')
    manifest=[dict(path=p.name,bytes=p.stat().st_size,sha256=io.sha(p)) for p in sorted(report.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    io.js(report/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True);dest=desktop/('IV_COMPETITIVE_ONLY_REPORT_'+conf[:12]+'.zip');temp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(temp,dest);Path(str(dest)+'.sha256').write_text(io.sha(dest)+'  '+dest.name+'\n')
    io.log('RETURN THIS AGGREGATE REPORT: '+str(dest));return dest
