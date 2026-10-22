"""Aggregate results only: no usernames, game IDs, or person-level exports."""
from common import *
import shutil,zipfile

def assemble_report(work,desktop,key,stage='COMPLETE',failure=None):
    work=Path(work);out=work/'report';out.mkdir(parents=True,exist_ok=True)
    coverage=[];material=[];payoffs=[];receipt_audits=[];receipt_patterns=[];secondary=[]
    for folder in sorted((work/'months').glob('*')):
        if not (folder/'PRIMARY_DONE.json').exists():continue
        primary=read(folder/'PRIMARY_DONE.json')
        if primary['key']!=key or any(not (folder/r['path']).is_file() or sha(folder/r['path'])!=r['sha256'] for r in primary['files']):
            raise RuntimeError('Primary report checkpoint is incomplete or changed: '+str(folder))
        with (folder/'coverage.csv').open() as f:coverage+=list(csv.DictReader(f))
        material.append(read(folder/'material_inventory.json'))
        if (folder/'payoff_audit.json').exists():payoffs.append(read(folder/'payoff_audit.json'))
        if (folder/'receipt_audit.json').exists():receipt_audits.append(read(folder/'receipt_audit.json'))
        if (folder/'secondary_status.json').exists():secondary.append(read(folder/'secondary_status.json'))
        if (folder/'receipt_patterns.csv').exists():
            with (folder/'receipt_patterns.csv').open() as f:receipt_patterns += [dict(month=folder.name,**r) for r in csv.DictReader(f)]
    csvwrite(out/'coverage.csv',coverage);csvwrite(out/'material_inventory.csv',material);csvwrite(out/'payoff_audit.csv',payoffs)
    csvwrite(out/'receipt_cohort_audit.csv',receipt_audits);csvwrite(out/'receipt_arm_patterns.csv',receipt_patterns)
    write(out/'secondary_status.json',secondary)
    if (work/'preparation_failures.json').exists():shutil.copyfile(work/'preparation_failures.json',out/'preparation_failures.json')
    if (work/'focal/feature_flow.csv').exists():shutil.copyfile(work/'focal/feature_flow.csv',out/'feature_flow.csv')
    estimates=[];support=[];balance=[];summaries=[];doses=[];dose_summaries=[]
    for folder in sorted((work/'comparisons').glob('*')):
        if not (folder/'_DONE.json').exists():continue
        s=read(folder/'summary.json');summaries.append(s)
        tag=dict(comparison=s['name'],specification=s['specification'])
        for name,dest in [('estimates',estimates),('support',support),('balance',balance)]:
            p=folder/(name+'.csv')
            if p.exists():
                with p.open() as f:dest += [dict(tag,**r) for r in csv.DictReader(f)]
    for folder in sorted((work/'dose_models').glob('*')):
        if not (folder/'_DONE.json').exists():continue
        dose_summaries.append(dict(name=folder.name,**read(folder/'summary.json')))
        if (folder/'estimates.json').exists():doses += [dict(model=folder.name,**r) for r in read(folder/'estimates.json')]
        if (folder/'unadjusted_dose_bins.csv').exists():shutil.copyfile(folder/'unadjusted_dose_bins.csv',out/(folder.name+'_bins.csv'))
    csvwrite(out/'comparison_estimates.csv',estimates);csvwrite(out/'overlap.csv',support);csvwrite(out/'balance.csv',balance)
    write(out/'comparison_summaries.json',summaries);csvwrite(out/'secondary_dose_estimates.csv',doses);write(out/'secondary_dose_summaries.json',dose_summaries)
    nforced=sum(int(r['rows']) for r in coverage if r['exposure_group']=='no_material_draw' and r['entry_eligible']=='True' and r['complete90']=='True')
    summary=dict(status=stage,version=VERSION,run_key=key,completed_months=len(material),
       completed_comparisons=len(summaries),completed_dose_models=len(dose_summaries),
       secondary_blocked_months=[r['month'] for r in secondary if r['status']!='VERIFIED'],
       eligible_no_material_draws=nforced,network_requests=0,stockfish_searches=0,
       original_IV_modified=False,causal_mechanism_identified=False,
       no_material_scope='Existing certified opportunity panels only; no absence interpreted as absence from Lichess',
       missing_no_material_data=(nforced==0 if len(material)==24 else None),failure=failure)
    write(out/'summary.json',summary)
    text='''READ THIS FIRST

The main tables are observational comparisons from the NEW phase-25 fixed frame.
The secondary stake models use the separate, larger author-clean frozen receipt
cohort. They are never pooled into the main comparisons. The original IV is not
refit, controlled for its consequences, or mechanically decomposed.

receipt_cohort_audit.csv and receipt_arm_patterns.csv identify secondary
disagreements by field and arm. Recorded claimed wins follow the original
kind_draw OR timeout_chooser_win definition; their material flag is reported,
not used to add a new exclusion. An unresolved identity, treatment, timing,
position or payoff disagreement withholds ALL secondary dose fits. No rows
are silently discarded and no forced draw is relabelled a claimed loss.
PRIMARY_COMPLETE_SECONDARY_BLOCKED means the comparisons finished but the
separate receipt-to-payoff join needs review. Read the audit, not a guess.

comparison_estimates.csv: positive means the first-named group has more later
kindness (y) or more later opportunities (reached), in percentage points.
Main specification: overlap. exact_time_control and within_recipient are
sensitivities with different supported populations. All draw types are labeled.

overlap.csv and balance.csv: read these before reading coefficient signs.
Poor retention or large standardized differences weakens interpretation.
Shared-account nominal intervals cover repeated recipients, exposure opponents,
and later opponents across roles. Generated histories, scores and weights are
treated as fixed. Intervals are not adjusted for multiple comparisons.

A nonsignificant contrast does NOT establish similarity. Two illustrative
95%-CI containment checks use +/-0.10 and +/-0.25 percentage points; these are
sensitivity margins, not an investigator-approved smallest meaningful effect.

Both y and reached use the frozen complete 90-day window. Complete-window
nonreachers have y=0; incomplete follow-up is missing, never a zero.
Kindness among reachers in overlap.csv is descriptive and conditions on a
post-exposure event; it is not the primary outcome.

No-material draws require explicit flags and the disconnected role. These may
be a selected endgame population. If none are available here, the code reports
that limitation and produces NO estimate for that comparison. A broader forced-
draw sample would require a separately authenticated opportunity source and
cohort; this package never relabels unclassified timeouts as forced draws.
The historical recipient UI and awareness of discretion have NOT been verified.

Ordinary games have no comparable pre-disconnection board state in this cache.
Stalemates are rule-determined endings but differ from granted draws in play
and expectations. 'draw' combines unspecified reasons, potentially agreement.
Do not describe either matched contrast as randomized or a causal mediation
effect. A pattern may be consistent with gratitude, denied leniency, or result
effects, but cannot uniquely identify any one mechanism.

Stake estimates use pregame modeled potential payoffs on BOTH treatment arms,
with separate giver cost and recipient benefit. The recipient measure is the
recipient-side half-win stake from the frozen common-scale replay, not a new
Glicko counterfactual with outcome-dependent volatility. The grants-only model
selects on granting and is secondary. Inspect RD correlations, VIF and rank.

All windows, cached histories, source identities, authors, chronology, and
earlier quarantine decisions are inherited. Results are conditional on the
fixed available-case frame and its prehistory/first-meeting/cooldown support.
See ANALYSIS_PLAN.txt in the code package for exact estimators and choices.
'''
    if nforced==0 and len(material)==24:text+='\nNO ELIGIBLE NO-MATERIAL DRAWS IN THE AVAILABLE CERTIFIED SOURCE.\n'
    elif len(material)<24:text+='\nPRIMARY COVERAGE IS INCOMPLETE; NO-MATERIAL AVAILABILITY IS NOT YET DETERMINED.\n'
    (out/'READ_RESULTS.txt').write_text(text)
    manifest=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(out.glob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    write(out/'REPORT_MANIFEST.json',manifest)
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    z=desktop/('RECEIPT_MECHANISMS_REPORT_'+key[:12]+'.zip');tmp=z.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(out.glob('*')):
            if p.is_file():archive.write(p,p.name)
    os.replace(tmp,z);log('Report: '+str(z));return z
