from common import *
import zipfile,shutil,datetime as dt

def figures(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    out=report/'figures';out.mkdir(exist_ok=True)
    p=report/'B1/B1_profiles.csv'
    if p.exists():
        rows=csvrows(p);rows=[r for r in rows if r['M']=='20' and r['year']=='1'];fig,ax=plt.subplots(figsize=(7.5,4.5))
        for k in sorted({r['type'] for r in rows}):
            a=sorted([r for r in rows if r['type']==k],key=lambda r:int(r['state']));ax.plot(range(5),[100*float(r['p']) for r in a],marker='o',label=f'Type {k} ({100*float(a[0]["share"]):.1f}%)')
        pp=report/'E/G1_year_state.csv'
        if pp.exists():
            a=sorted([r for r in csvrows(pp) if r['year']=='1'],key=lambda r:int(r['state']));ax.plot(range(5),[float(r['rate_pct']) for r in a],color='black',ls='--',label='Pooled Year 1')
        ax.set_xticks(range(5),['Clearly lost','Behind','Equal','Ahead','Well ahead']);ax.set_xlabel('Disconnected recipient’s position');ax.set_ylabel('Grant probability (%)');ax.set_title('Year 1 account mixture: profiles, M = 20');ax.legend(frameon=False);fig.tight_layout();fig.savefig(out/'B1_profiles.pdf');fig.savefig(out/'B1_profiles.png',dpi=160);plt.close(fig)
    p=report/'C1/C1_exposure_deciles.csv'
    if p.exists():
        r=csvrows(p)
        if r:
            fig,ax=plt.subplots(figsize=(7.5,4));ax.errorbar([int(x['decile'])+1 for x in r],[float(x['rate_pct']) for x in r],yerr=[1.96*float(x['cluster_se_pp'] or 0) for x in r],fmt='o-',capsize=3)
            ax.set_xlabel('Prior observed-opportunity count: decile (ties preserved)');ax.set_ylabel('First observed competitive grant (%)');ax.set_title('Descriptive hazard among accounts still at risk');fig.tight_layout();fig.savefig(out/'C1_hazard.pdf');fig.savefig(out/'C1_hazard.png',dpi=160);plt.close(fig)
    p=report/'H_deciles/H_adjusted_score_deciles.csv'
    if p.exists():
        r=csvrows(p);fig,axs=plt.subplots(1,2,figsize=(10,4))
        for ax,label in zip(axs,['first_stage','reduced_form']):
            a=sorted([x for x in r if x['outcome']==label],key=lambda x:int(x['decile']));ax.errorbar([int(x['decile'])+1 for x in a],[float(x['estimate_pp']) for x in a],yerr=[1.96*float(x.get('standard_error_pp') or 0) for x in a],fmt='o-',capsize=3)
            ax.axhline(0,color='#999999',lw=.8);ax.set_title(label.replace('_',' ').capitalize());ax.set_xlabel('Opponent leniency score decile');ax.set_ylabel('Adjusted difference from first decile (pp)')
        fig.tight_layout();fig.savefig(out/'H_deciles.pdf');fig.savefig(out/'H_deciles.png',dpi=160);plt.close(fig)
    p=report/'G/G2_relative_event_study.csv'
    if p.exists():
        r=csvrows(p);fig,axs=plt.subplots(3,2,figsize=(10,10),sharex=True)
        for s,ax in enumerate(axs.flat):
            if s==5:ax.set_visible(False);continue
            for speed in ('blitz','rapid','classical'):
                a=sorted([x for x in r if x['state']==str(s) and x['speed']==speed and x.get('status')=='ESTIMATED'],key=lambda x:int(x['week']))
                if not a:continue
                ax.plot([int(x['week']) for x in a],[float(x['estimate']) for x in a],marker='.',label=speed)
            ax.axhline(0,color='#999999',lw=.8);ax.axvline(-.5,color='#999999',ls='--',lw=.8)
            ax.set_title(['Clearly lost','Behind','Equal','Ahead','Well ahead'][s]);ax.set_ylabel('Relative change vs bullet (pp)');ax.set_xlabel('Week relative to merge-date proxy')
        if axs.flat[0].get_legend_handles_labels()[0]:axs.flat[0].legend(frameon=False)
        fig.suptitle('Descriptive event-study contrasts; reference week -1\nAll speed groups changed; intervals are in the companion table',fontsize=11)
        fig.tight_layout();fig.savefig(out/'G2_relative_event_study.pdf');fig.savefig(out/'G2_relative_event_study.png',dpi=160);plt.close(fig)
    p=report/'D1/D1_equal_profiles.csv'
    if p.exists():
        r=csvrows(p);fig,ax=plt.subplots(figsize=(8,5))
        for stage in sorted({x['stage'] for x in r},key=int):
            a=sorted([x for x in r if x['stage']==stage],key=lambda x:float(x['probability_bin']))
            ax.plot([float(x['probability_bin'])+.025 for x in a],[float(x['rate_pct']) for x in a],marker='.',label='Stage '+stage)
        ax.set_xlabel('Estimated chooser win probability (5-point bins)');ax.set_ylabel('Grant rate (%)')
        ax.set_title('Roughly equal positions, supported calibration cells');ax.legend(frameon=False,ncol=2)
        fig.tight_layout();fig.savefig(out/'D1_equal_profiles.pdf');fig.savefig(out/'D1_equal_profiles.png',dpi=160);plt.close(fig)

def assemble(work,desktop,key,status,stages,failure=None,plots=False):
    work=Path(work);report=work/'report';report.mkdir(exist_ok=True)
    for name in ['00_aggregates','00_markers','00_inventory','E','G','C1','C23','H_deciles','H_dynamic','B1','B2','B3','D1','D2','F']:
        root=work/name
        if not root.exists():continue
        dest=report/name;dest.mkdir(exist_ok=True)
        for p in root.glob('*'):
            if p.is_file() and p.suffix in ('.json','.csv') and p.name!='_DONE.json' and 'PRIVATE' not in p.name:shutil.copy2(p,dest/p.name)
    env=ROOT/'authority/environment/estimates.csv'
    if env.exists():
        rows=[r for r in csvrows(env) if r.get('kind')=='iv' and r.get('control_level') in ('XC','XC_both_rates')]
        csvwrite(report/'H_archived_environment_controls.csv',rows)
        if not rows:raise RuntimeError('Archived environment-control selection is empty')
    shutil.copy2(ROOT/'ANALYSIS_PLAN.md',report/'ANALYSIS_PLAN.md')
    shutil.copy2(ROOT/'EXTENDED_INPUTS.md',report/'EXTENDED_INPUTS.md')
    summary=dict(status=status,run_key=key,stages=stages,failure=failure,network_requests=0,stockfish_searches=0,
      production_data_stays_local=True,psychological_types_identified=False,lifetime_history_observed=False,
      existing_headline_IV_modified=False,year1_types_never_use_year2=True)
    write(report/'summary.json',summary)
    coverage=[]
    for item,stage_name,note in [
      ('0.1 opportunity proxies and Patron','00_markers','Rating at main opportunities; tenure where covered; selected later Patron snapshot. Not all-game markers.'),
      ('E1 lost-position persistence','E','Raw, harmonic-weighted correlation and account bootstrap; rare-event null does not establish noise.'),
      ('E2 clock and speed','E','Clock is measured at last recorded move, not at actual click.'),
      ('E3 lost-granter profiles','E','Selected in Year 1; Year 2 validates without reselecting.'),
      ('E4 and G2 rule change','G','Relative contrasts; all speeds changed; deployment date unverified.'),
      ('B1 finite mixture','B1','K1-6; M20/50/4; 20 full-data starts; main-profile 200-account bootstrap.'),
      ('B2 covariate mixture','B2','B1-selected K; type-specific cost slopes; main-profile 200-account bootstrap.'),
      ('B3 held-out validation','B3','Year-1 modal types; selected-marker coverage and Year-2 independent fits.'),
      ('C1 first observed grant hazard','C1','Observed panel starts in November 2023. Lifetime first grant is not identified.'),
      ('C2/C3 receipt splits','C23','Joint IV effects, subgroup difference, per-1000 scaling; observed-history definitions.'),
      ('G1 local year comparisons','E','Descriptive main-panel totals/profiles; receipt year split in C23. Not every headline in the paper.'),
      ('H instrument deciles','H_deciles','Raw and adjusted first-stage/reduced-form contrasts.'),
      ('H receipt dynamics','H_dynamic','Kind-act and opportunity counts in frozen 0-7/7-30/30-90 day windows.'),
      ('D1 continuation model','D1','Requires authenticated ordinary-game continuation cells; conditional calibration uncertainty only.'),
      ('D2 accuracy model','D2','Requires full-game accuracy inputs; chooser and exact eval/ply fixed effects.'),
      ('F waiting proxy and bounds','F','Requires evaluated outoftime events with clocks and matching pool/nonadjacent scope.')]:
        s=stages.get(stage_name,{})
        coverage.append(dict(item=item,status=s.get('status','NOT_RUN'),note=note,reason=s.get('reason','')))
    coverage += [dict(item='0.1 all-game markers',status='NEEDS_INPUT_BUILD',note='Resignation share, disconnects per all games, casual share, annual games/rating spread and provisional status require an all-game account-year build.'),
      dict(item='0.3 random ordinary-game engine calibration',status='NEEDS_INPUT_BUILD',note='Inventory and frozen contract supplied. This launcher does not scan PGNs or invoke Stockfish.'),
      dict(item='H environment-controls table',status='ARCHIVED_VERIFIED_RESULT',note='Copied from reviewed report cea0b052e5f2 with original support and instruments. Not newly estimated.'),
      dict(item='G1 other paper headlines',status='NOT_RERUN',note='Existing structural and Patron regressions have different contracts; not claimed to be replicated here.')]
    csvwrite(report/'ANALYSIS_COVERAGE.csv',coverage)
    lines=['KINDNESS TAXONOMY: EXPLORATORY ANALYSES',f'Status: {status}','',
      'Start with E1, E2 and year-2 E3 profiles; then the mixture fit/convergence path and held-out shapes.',
      'Read C2/C3 subgroup effects together with their direct difference, first stages, and reached outcome.',
      'No prior observed grant is not no lifetime grant. Screen counts are recorded eligible opportunities, not UI telemetry.',
      'The panel excludes both author accounts, including both roles in observed behavioral histories.',
      'B1/B2 type estimation uses year 1 only. Year 2 independent fits are descriptive validation, never inputs to year-1 assignments.',
      'A rare-event persistence null is not proof of noise; speed/clock patterns do not observe misclicks.',
      'A fitted flat or near-zero component is a behavioral approximation, not an identified mental state.',
      'The July event date is a source-merge proxy. All speed categories changed. Temporal comparisons are not certified policy effects.',
      'Patron means use a selected later snapshot; missing all-game markers are not filled with zeros.',
      'Inspect optional-source inventory and EXTENDED_INPUTS.md for real data gaps. COMPLETE_LOCAL does not mean D/F/new-data builds completed.',
      'The archived environment-control table retains its own cohort, score and support definition; it is not the new subgroup fit.','']
    lines += [f'{n}: {r.get("status", "unknown")}'+(' — '+r['reason'] if r.get('reason') else '') for n,r in stages.items()]
    (report/'READ_RESULTS.txt').write_text('\n'.join(lines)+'\n')
    if plots:figures(report)
    manifest=[dict(path=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    write(report/'REPORT_MANIFEST.json',manifest)
    zip_path=Path(desktop)/f'KINDNESS_TAXONOMY_REPORT_{key[:12]}.zip';tmp=zip_path.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(report)))
    os.replace(tmp,zip_path);Path(str(zip_path)+'.sha256').write_text(sha(zip_path)+'  '+zip_path.name+'\n')
    log('RETURN_ZIP: '+str(zip_path));return zip_path
