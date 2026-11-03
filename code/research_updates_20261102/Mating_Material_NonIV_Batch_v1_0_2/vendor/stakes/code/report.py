"""Small shareable aggregate results; player rows stay in PRIVATE work area."""
import shutil, zipfile
from common import *

def summarize(work,report,files,memory=4096):
    work,report=Path(work),Path(report);report.mkdir(parents=True,exist_ok=True)
    c=connect(work/'tmp/report',2,memory)
    try:
        c.execute('CREATE VIEW a AS SELECT * FROM '+scan(files))
        n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM a').fetchone()
        if n!=u:raise RuntimeError('Duplicate opportunity game across final features')
        expected=sum(read(p)['rows'] for p in (work/'targets').glob('*.json'))
        if n!=expected:raise RuntimeError(f'Final row conservation failed: {n} != {expected}')
        table=[]
        cuts=[('overall',"'all'"),('speed','speed'),('rd','rd_band'),
              ('rating200',"CAST(rating_band_200 AS VARCHAR)"),
              ('standing_decile','CAST(standing_decile AS VARCHAR)'),
              ('speed_rating200',"speed||':'||CAST(rating_band_200 AS VARCHAR)")]
        agg='''count(*) opportunities,count(DISTINCT user_id) accounts,sum(y) grants,
          quantile_cont(ki,[.25,.5,.75])[2] premium_p50,quantile_cont(ki,[.25,.5,.75])[1] premium_p25,quantile_cont(ki,[.25,.5,.75])[3] premium_p75,
          quantile_cont(percentile_pp,[.25,.5,.75])[2] percentile_pp_p50,quantile_cont(percentile_pp,[.25,.5,.75])[1] percentile_pp_p25,
          quantile_cont(percentile_pp,[.25,.5,.75])[3] percentile_pp_p75,
          sum(history100_complete::INTEGER) history100_complete,
          sum(history100_zero::INTEGER) history100_zero,
          count(premium_over_sd100) sd100_ratio_n,
          median(sd100) sd100_p50,quantile_cont(premium_over_sd100,[.25,.5,.75])[2] sd100_ratio_p50,
          quantile_cont(premium_over_sd100,[.25,.5,.75])[1] sd100_ratio_p25,quantile_cont(premium_over_sd100,[.25,.5,.75])[3] sd100_ratio_p75,
          100*avg(CASE WHEN premium_over_sd100 IS NOT NULL THEN (premium_over_sd100>=.1)::DOUBLE END) pct_ratio_ge_0_1,
          100*avg(CASE WHEN premium_over_sd100 IS NOT NULL THEN (premium_over_sd100>=.5)::DOUBLE END) pct_ratio_ge_0_5,
          100*avg(CASE WHEN premium_over_sd100 IS NOT NULL THEN (premium_over_sd100>=1)::DOUBLE END) pct_ratio_ge_1,
          count(premium_over_sd50) sd50_ratio_n,median(premium_over_sd50) sd50_ratio_p50,
          count(premium_over_iqr100) iqr100_ratio_n,median(premium_over_iqr100) iqr100_ratio_p50,
          count(premium_over_detrended_sd100) detrended_ratio_n,median(premium_over_detrended_sd100) detrended_ratio_p50,
          median(span100_days) span100_days_p50,median(last_start_age_days) last_start_age_days_p50,
          count(*) FILTER(WHERE n_prior_capped101<100) fewer_than_100_observations,
          count(*) FILTER(WHERE n_prior_capped101>=100 AND missing100>0) missing_rating_in_100,
          count(*) FILTER(WHERE tie100=1) tied_window_boundary,
          100*avg(cross_100::DOUBLE) pct_cross_100,
          100*avg(cross_p50::DOUBLE) pct_cross_p50,100*avg(cross_p90::DOUBLE) pct_cross_p90,
          100*avg(cross_p95::DOUBLE) pct_cross_p95,100*avg(cross_p99::DOUBLE) pct_cross_p99'''
        for sample,where in [('competitive_all','TRUE'),('competitive_grants','y=1'),
                             ('competitive_RD_le110','rd<=110'),('competitive_grants_RD_le110','y=1 AND rd<=110')]:
            for cut,group in cuts:
                df=c.execute(f'SELECT {q(sample)} AS sample,{q(cut)} AS cut,{group} AS band,{agg} FROM a WHERE {where} GROUP BY 1,2,3 ORDER BY 3').df()
                table.append(df)
        summary=pd.concat(table,ignore_index=True)
        summary.to_csv(report/'stakes_table.csv',index=False)
        player=c.execute('''WITH p AS (SELECT user_id,speed,count(*) opportunities,
          median(ki) premium,median(percentile_pp) percentile_pp,
          median(premium_over_sd100) ratio FROM a WHERE rd<=110 GROUP BY user_id,speed)
          SELECT speed,count(*) account_speed_units,sum(opportunities) opportunities,
          median(premium) median_account_median_premium,
          median(percentile_pp) median_account_median_percentile_pp,
          count(ratio) accounts_with_ratio,median(ratio) median_account_median_sd100_ratio
          FROM p GROUP BY speed ORDER BY speed''').df()
        player.to_csv(report/'equal_account_sensitivity.csv',index=False)
        months=c.execute('''SELECT month,speed,count(*) opportunities,sum(y) grants,
          sum(history100_complete::INTEGER) history100_complete,
          count(premium_over_sd100) ratio_eligible,
          count(*) FILTER(WHERE n_prior_capped101<100) fewer_than_100,
          count(*) FILTER(WHERE missing100>0 AND n_prior_capped101>=100) missing_prior_rating,
          count(*) FILTER(WHERE tie100=1) tied_window_boundary,
          sum(history100_zero::INTEGER) zero_sd100 FROM a GROUP BY month,speed ORDER BY month,speed''').df()
        months.to_csv(report/'history_coverage.csv',index=False)
        same=c.execute('''SELECT count(*) opportunities_with_all_ratios,median(premium_over_sd100) sd100_ratio,
          median(premium_over_sd50) sd50_ratio,median(premium_over_iqr100) iqr100_ratio,
          median(premium_over_detrended_sd100) detrended_ratio FROM a
          WHERE rd<=110 AND premium_over_sd100 IS NOT NULL AND premium_over_sd50 IS NOT NULL
          AND premium_over_iqr100 IS NOT NULL AND premium_over_detrended_sd100 IS NOT NULL''').df()
        same.to_csv(report/'same_sample_sensitivity.csv',index=False)
    finally:c.close()
    population=[];timings=[]
    for p in sorted((work/'history').glob('*/*/_DONE.json')):
        d=read(p);population.append(dict(speed=d['speed'],month=d['month'],**d['population']))
        timings.append(dict(speed=d['speed'],month=d['month'],seconds=d['seconds'],source_games=d['source']['rows'],targets=d['targets']))
    pd.DataFrame(population).to_csv(report/'reference_population_coverage.csv',index=False)
    pd.DataFrame(timings).to_csv(report/'stage_timings.csv',index=False)
    preparation=[dict(month=p.stem,**read(p)['counts']) for p in sorted((work/'targets').glob('*.json'))]
    pd.DataFrame(preparation).to_csv(report/'sample_coverage.csv',index=False)
    write(report/'SUMMARY.json',dict(status='STAKES_DESCRIPTIVES_COMPLETE',opportunities=n,
        main_sample='frozen pool nonadjacent 24 months, author excluded, engine_eval_cp_disconnected >= -100, five real-time speeds',
        usual_win_gain_status='NOT_ESTIMATED_NO_AUTHENTICATED_COMPLETION_TIMES',
        interpretation='Rating-scale stakes, not subjective utility or a causal estimate of generosity',
        history='Last 100 and 50 strictly earlier recorded same-speed starts, full window required; bounded warm-up',
        percentile='Previous calendar month active-account ECDF, one latest pregame observation per account, authors excluded',
        source_validation='Frozen main SHA256; chronology frozen rows/bytes and run-bound raw footer/fingerprint; every focal identity/rating/start reconciled',
        zero_denominator_rule='Ratios unavailable; zero histories counted explicitly',API_requests=0,rating_replays=0,Stockfish_searches=0))
    shutil.copy2(ROOT/'METHODS.txt',report/'METHODS.txt')
    write_readme(report,summary,n)
    plot(report,summary)
    return n

def write_readme(report,summary,n):
    rows=summary[(summary['cut']=='overall')]
    lines=['WIN PREMIUM STAKES — DESCRIPTIVE RESULTS','',f'Competitive opportunities: {n:,}','',
      'Start with stakes_table.csv: cut=overall, sample=competitive_RD_le110.',
      'The RD cutoff describes current rating uncertainty, not tenure or subjective stability.',
      'Compare competitive_all to assess the high-RD tail, and competitive_grants to describe realized generosity.',
      'All table medians are medians of opportunity-specific quantities.',
      'Coverage counts are denominators, not exclusions from the entire study.','']
    for _,r in rows.iterrows():
        lines.append(f"{r['sample']}: median premium {r.premium_p50:.3f} rating points; median percentile cost {r.percentile_pp_p50:.4f} percentage points; median premium / prior SD100 {r.sd100_ratio_p50:.3f}; ratio coverage {int(r.sd100_ratio_n):,}/{int(r.opportunities):,}.")
    lines += ['',
      'A percentile cost of 0.2 means 0.2 percentage points, not 20% of rank.',
      'A ratio of 0.2 means one fifth of the player\'s historical rating SD. It does not establish that the cost feels small.',
      'The 100-point and percentile crossings are descriptive threshold contrasts. They do not show that players attend to these thresholds.',
      'Equal-account and same-sample sensitivity tables separate frequent-player weighting and denominator coverage.',
      'Ordinary completed-win gains are intentionally unavailable: the reusable history has starts, not authenticated ends.',
      'No author/player-level rows are included in this shareable report.',
      'See METHODS.txt and coverage CSVs before interpreting the chart.']
    text(report/'READ_ME.txt','\n'.join(lines)+'\n')

def plot(report,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    df=summary[(summary['cut']=='standing_decile')&(summary['sample']=='competitive_RD_le110')].copy()
    df['x']=df.band.astype(int);df=df.set_index('x').reindex(range(1,11)).reset_index(names='x')
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.4),layout='constrained')
    for ax,prefix,label in zip(axes,['percentile_pp','sd100_ratio'],['Percentile cost (percentage points)','Premium / prior rating SD (100 observations)']):
        ax.fill_between(df.x,df[prefix+'_p25'],df[prefix+'_p75'],color='#bcd4ec',alpha=.8,label='25th–75th percentile')
        ax.plot(df.x,df[prefix+'_p50'],marker='o',color='#185787',label='Median')
        ax.set(xlabel='Pre-game standing decile within speed/month',ylabel=label,xticks=range(1,11),ylim=(0,None));ax.grid(axis='y',alpha=.2)
        ax.spines[['top','right']].set_visible(False)
    axes[0].legend(frameon=False,fontsize=8)
    fig.suptitle('Win premium at different rating standings\nCompetitive opportunities, chooser RD ≤ 110',fontsize=12)
    fig.savefig(report/'stakes_by_standing.png',dpi=180)
    fig.savefig(report/'stakes_by_standing.pdf');plt.close(fig)

def bundle(report,desktop):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    out=desktop/'Win_Premium_Stakes_Report.zip';tmp=out.with_suffix('.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(report).rglob('*')):
            if p.is_file():z.write(p,Path('Win_Premium_Stakes_Report')/p.relative_to(report))
    os.replace(tmp,out);return out
