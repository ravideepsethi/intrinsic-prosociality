"""Original account bootstrap, immutable shared matrices and hashed checkpoints."""
from util import *
import sys,time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
sys.path.insert(0,str(ROOT/'vendor/bootstrap'))
import bootstrap_table3 as original

def matrices(c,run):
    # Stable ordering makes the seed independent of DuckDB's thread scheduling.
    cols=','.join(f'{k}_{s}{y}' for y in (1,2) for s in 'cl' for k in ('n','y'))
    a=c.execute('SELECT '+cols+' FROM f_wide WHERE n_c1>=1 AND n_c2>=1 AND n_c1+n_c2>=4 ORDER BY chooser').fetchdf()
    b=c.execute('SELECT '+cols+' FROM f_wide WHERE n_c1>=4 AND n_c2>=4 AND n_l1>=4 AND n_l2>=4 ORDER BY chooser').fetchdf()
    ma=original.matrix_a(a);mb=original.matrix_b(b)
    require(np.isfinite(ma).all() and np.isfinite(mb).all(),'Nonfinite bootstrap sufficient statistics')
    pa=original.decode_a(ma.sum(axis=0));pb=original.decode_b(mb.sum(axis=0))
    report=run/'report/persistence'
    ref=pd.read_csv(report/'tabF0_original_competitive_reconciliation.csv').iloc[0]
    require(len(a)==ref.accounts and np.allclose(pa[:2],[ref.pearson_equal_account,ref.pearson_total_comp_opportunities_weighted],atol=2e-8,rtol=0),'Bootstrap cohort A does not reproduce the fresh point estimates')
    cors=pd.read_csv(report/'tabF4_cross_year_correlations.csv')
    cors=cors[cors.min_opportunities_each_year_and_state==4]
    values=[float(cors[(cors.period1_state==s)&(cors.period2_state==t)].correlation_equal_account.iloc[0]) for s,t in [('c','c'),('l','l'),('c','l'),('l','c')]]
    require(np.allclose(pb[:4],values,atol=2e-8,rtol=0),'Bootstrap cohort B does not reproduce the fresh point estimates')
    transition=pd.read_csv(report/'tabF2_transition_4x4.csv')
    expected=np.array([int(transition[(transition.p1_group==s)&(transition.p2_group==t)].accounts.iloc[0]) for s in original.GROUPS for t in original.GROUPS])
    require(np.array_equal(mb[:,24:].sum(axis=0),expected),'Bootstrap transitions do not reproduce the fresh counts')
    groups=original.group(b.y_c1,b.y_l1)
    cohort=dict(A=len(a),B=len(b),A_no_prior=int((a.y_c1==0).sum()),A_prior=int((a.y_c1>0).sum()),
                B_groups={g:int((groups==i).sum()) for i,g in enumerate(original.GROUPS)},
                A_opportunities=int(a.n_c1.sum()+a.n_c2.sum()),A_grants=int(a.y_c1.sum()+a.y_c2.sum()))
    save(run/'report/BOOTSTRAP_POINT_GATES.json',dict(all_passed=True,cohorts=cohort,A=pa.tolist(),B_C=pb.tolist()))
    ma.flags.writeable=False;mb.flags.writeable=False
    return ma,mb,pa,pb,cohort

def sample(ma,mb,out,key,replications=1999,seed=20261025,workers=10,stop_after=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    receipt=out/'BOOTSTRAP_CHECKPOINT.json'
    da=np.empty((replications,len(original.NAMES_A)));db=np.empty((replications,len(original.NAMES_B)))
    configuration=dict(key=key,replications=replications,seed=seed,shape_A=list(ma.shape),shape_B=list(mb.shape))
    start=0
    if receipt.exists():
        stored=read(receipt)
        require(stored['configuration']==configuration,'Bootstrap checkpoint configuration differs')
        saved=verify(stored['file'],out)
        with np.load(saved,allow_pickle=False) as prior:
            start=stored['completed']
            require(0<=start<=replications and prior['A'].shape==(start,da.shape[1]) and prior['B'].shape==(start,db.shape[1]),'Bootstrap checkpoint dimensions differ')
            require(np.isfinite(prior['A']).all() and np.isfinite(prior['B']).all(),'Nonfinite bootstrap checkpoint')
            da[:start]=prior['A'];db[:start]=prior['B']
        log(f'Bootstrap: {start}/{replications} validated resamples per cohort reused')
    began=time.monotonic();initial=start
    def job(j):return original.draw_stat(ma,0,seed,j),original.draw_stat(mb,1,seed,j)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while start<replications:
            end=min(start+25,replications)
            if stop_after is not None:end=min(end,stop_after)
            if end<=start:break
            with heartbeat('Account bootstrap batch'):
                for j,(a,b) in zip(range(start,end),pool.map(job,range(start,end))):da[j]=a;db[j]=b
            require(np.isfinite(da[start:end]).all() and np.isfinite(db[start:end]).all(),'Undefined bootstrap replicate; no resamples discarded')
            start=end
            # Versioned data precede the atomic pointer update. Interruption
            # cannot overwrite the last committed checkpoint's bytes.
            savefile=out/f'bootstrap_draws_{start:05d}_PRIVATE.npz'
            temporary=savefile.with_suffix('.npz.partial')
            with temporary.open('wb') as f:
                np.savez(f,A=da[:start],B=db[:start]);f.flush();os.fsync(f.fileno())
            os.replace(temporary,savefile)
            save(receipt,dict(configuration=configuration,completed=start,file=record(savefile,out)))
            elapsed=time.monotonic()-began
            log(f'Bootstrap {start}/{replications} per cohort; elapsed {elapsed/60:.1f} min; estimated remaining {elapsed/max(1,start-initial)*(replications-start)/60:.1f} min')
    return da[:start],db[:start]

def table_tex(frame,cohort,replications,path):
    lookup=frame.set_index(['panel','statistic'])
    def cell(panel,name):
        row=lookup.loc[(panel,name)];return f'{row.estimate:.3f} ({row.bootstrap_se:.3f})'
    lines=[r'\begin{table}[!htbp]',r'\centering',r'\caption{Persistence of granting across years}',r'\label{tab:persistence}',r'\begin{threeparttable}',r'\footnotesize',r'\begin{tabular}{p{0.63\textwidth}r}',r'\toprule',
           r'\multicolumn{2}{l}{\textit{Panel A. Competitive-position rate, '+f'{cohort["A"]:,}'+r' accounts}} \\',r'\midrule']
    labels=['Correlation, equal account weights','Correlation, total-opportunity weights',r'Second-year rate, no first-year grant (\%)',r'Second-year rate, at least one first-year grant (\%)','Rate ratio: prior grant / none']
    for name,label in zip(original.NAMES_A,labels):lines.append(label+' & '+cell('A',name)+r' \\')
    lines += [r'\addlinespace',r'\multicolumn{2}{l}{\textit{Panel B. By board state, '+f'{cohort["B"]:,}'+r' accounts}} \\']
    labels=['Competitive rate across years','Clearly-worse rate across years','First-year competitive with second-year clearly-worse','First-year clearly-worse with second-year competitive','Implied correlation, first-year competitive direction','Implied correlation, first-year clearly-worse direction']
    for name,label in zip(original.NAMES_B[:6],labels):lines.append(label+' & '+cell('B',name)+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\medskip',r'\begin{tabular}{lrrrrr}',r'\toprule',r'\multicolumn{6}{l}{\textit{Panel C. Second-year group by first-year group (percent of row)}} \\',r'First-year group & Accounts & Neither & Competitive only & Clearly worse only & Both \\',r'\midrule']
    for g,label in zip(original.GROUPS,original.GROUP_LABELS):
        lines.append(label+' & '+f'{cohort["B_groups"][g]:,}'+' & '+' & '.join(cell('C',f'transition_{g}_{h}_percent') for h in original.GROUPS)+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\begin{tablenotes}[flushleft]',r'\scriptsize',
       r'\item Notes: November 2023--October 2024 and November 2024--October 2025. Panel A requires at least one competitive opportunity in each year and four in total. Panels B and C require at least four opportunities in each state in each year. '+f'{replications:,} uniform account bootstrap resamples retain complete two-year histories and original opportunity weights; B and C share each resample. Standard errors are the replication standard deviations. Never-granting accounts remain. Inference conditions on each observed returning cohort.',
       r'\end{tablenotes}',r'\end{threeparttable}',r'\end{table}']
    Path(path).write_text('\n'.join(lines)+'\n')

def publish(run,da,db,pa,pb,cohort,seed):
    report=run/'report/bootstrap';report.mkdir(parents=True,exist_ok=True)
    rows=[]
    for panel,names,points,draws in [('A',original.NAMES_A,pa,da),('B',original.NAMES_B,pb,db)]:
        for j,name in enumerate(names):
            lo,hi=np.quantile(draws[:,j],[.025,.975])
            rows.append(dict(panel='C' if name.startswith('transition_') else panel,statistic=name,
                             estimate=float(points[j]),bootstrap_se=float(draws[:,j].std(ddof=1)),ci95_low=float(lo),ci95_high=float(hi),replications=len(draws),accounts=cohort[panel]))
    frame=pd.DataFrame(rows);table(report/'table3_bootstrap.csv',frame);table(run/'report/tab_persistence.csv',frame)
    np.savez(report/'bootstrap_joint_covariance.npz',A=np.cov(da,rowvar=False,ddof=1),B_C=np.cov(db,rowvar=False,ddof=1),names_A=np.array(original.NAMES_A),names_B_C=np.array(original.NAMES_B))
    pd.DataFrame(da,columns=original.NAMES_A).to_parquet(report/'replicates_A.parquet',index=False,compression='zstd')
    pd.DataFrame(db,columns=original.NAMES_B).to_parquet(report/'replicates_B_C.parquet',index=False,compression='zstd')
    table_tex(frame,cohort,len(da),run/'report/tab_persistence.tex')
    save(report/'METHOD.json',dict(status='COMPLETE',replications=len(da),seed=seed,cohorts=cohort,
         resampling='Uniform iid accounts within each fixed eligible cohort, complete histories and opportunity weights retained; no within-account game resampling',
         dependence='A separately; B and C share every resample',
         order='Account IDs sorted lexicographically; deterministic SeedSequence([seed,panel,replicate])',
         se='Replication SD, ddof=1',interval='Percentile 95%',
         original_matrix_and_decode_and_draw_functions_unchanged=True))
