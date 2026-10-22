"""Portable aggregate results; private row-level influence and move files stay local."""
from r7_common import *
import zipfile

def collect(root):
    rows={k:[] for k in TABLES};models=0
    for path in sorted((root/'models').glob('*/result.json')):
        if '.partial_' in str(path):continue
        data=io.load(path);models+=1
        for key in TABLES:rows[key]+=data.get(key,[])
    # Separate requested views while retaining the complete estimate table.
    for r in rows['B_estimates']:
        sample=r.get('sample','')
        if sample.startswith('F50'):rows['B_entry'].append(r)
        if sample.startswith('O50'):rows['B_placebo'].append(r)
        if 'repeat' in sample:rows['B_repeated'].append(r)
        if sample in ('S0_env','S0_CSE'):rows['B_ladder'].append(r)
    cp=root/'contrasts/result.json'
    if cp.exists():rows['B_placebo_contrasts']=io.load(cp)
    return rows,models

def export(root,desktop,conf,status,started,expected_jobs=0,error=None):
    rows,models=collect(root);report=root/'report';report.mkdir(exist_ok=True)
    for name,data in rows.items():write_rows(report,name,data)
    support=io.load(root/'support.json') if (root/'support.json').exists() else []
    write_rows(report,'support',support)
    gate=io.load(root/'reproduction/checks.json') if (root/'reproduction/checks.json').exists() else []
    io.js(report/'reproduction.json',gate)
    for relative,name in [('entry_outcomes/summary.json','entry_outcome_attachment'),
                          ('input_preflight.json','input_preflight'),('reproduction/reuse.json','reproduction_reuse')]:
        source=root/relative
        if source.exists():io.js(report/(name+'.json'),io.load(source))
    if (root/'performance.json').exists():io.js(report/'performance.json',io.load(root/'performance.json'))
    for name in ('original_panel_A','original_primary_balance'):
        source=root/'reproduction'/(name+'.json')
        if source.exists():io.js(report/(name+'.json'),io.load(source))
    coverage=[]
    for p in sorted((root/'models').glob('C_*/coverage.json')):
        if '.partial_' not in str(p):coverage.append(io.load(p))
    io.js(report/'move_coverage.json',coverage)
    missing=sum(r['missing_move_rows'] for r in coverage)
    unavailable_y=sorted({r['sample'] for r in rows['A_predicted_outcome']
                          if r.get('reason')=='INCOMPLETE_FOLLOWUP_ON_FROZEN_ROWS'})
    if status=='R7_ANALYSIS_COMPLETE' and missing:status='R7_AB_COMPLETE_C_AVAILABLE_RECORDS_ONLY'
    if unavailable_y and status in ('R7_ANALYSIS_COMPLETE','R7_AB_COMPLETE_C_AVAILABLE_RECORDS_ONLY','AB_COMPLETE_C_PENDING'):
        status+='_WITH_UNAVAILABLE_F50_Y'
    summary=dict(version=VERSION,config_sha256=conf,previous_R7_ENV_reused=(root/'REUSED_R7_PRIVATE.json').exists(),status=status,elapsed_seconds=time.monotonic()-started,
        completed_models=models,expected_models=expected_jobs,reproduction_passed=bool(gate),
        reproduction_reused=(root/'REUSED_REPRODUCTION_PRIVATE.json').exists(),
        full_row_F50_Y_unavailable_samples=unavailable_y,
        original_headline_rows=2682330,author_clean_diagnostic_rows=2682329,
        author_clean_model_scope='all R7 A/B/C diagnostics',original_model_scope='reproduction only',
        no_headline_promotion=True,network_requests=0,stockfish_searches=0,
        nominal_interim_intervals=True,diagnostic_after_reviewed_results=True,causal_identification_certified=False,
        missing_move_rows=missing,part_C_full_population_classification=bool(coverage) and missing==0,
        C5='DEFERRED; no trap-opening propensity estimated',error=error)
    io.js(report/'summary.json',summary)
    lines=[f'R7 {VERSION}: {status}',f'Completed model checkpoints: {models}/{expected_jobs}',
        'Specification order: A (joint balance/calibration), B (same-row ENV), C (exit composition).',
        'Execution: authenticate -> reproduce or verify pinned production gate -> reuse/extend ENV -> attach cached F50 outcomes -> input preflight -> A/B -> contrasts -> C.',
        'F50 later outcomes come from the authenticated Phase-050 assembled feature cache; the ordinary-frame outcomes are reconciled exactly.',
        'All frozen rows are retained. Incomplete-window outcomes remain null; if present in a selected F50 sample, its full-row A1/A3 Y column is explicitly unsupported.',
        'Original Panel A: 2,682,330 rows, reproduction only. R7 diagnostics: 2,682,329 author-clean rows.',
        'B1: X0 and X0+ENV use identical ENV-supported rows. XC requires extra competitive support;',
        'the S0_CSE bridge refits X0, X0+ENV, XC, XC+ENV on exactly those common rows.',
        'B2 and its F50/O50 analogues: unsupported ENV values = 0 plus an unscaled availability indicator.',
        'This is a separate control convention. The original histories and rate caches remain missing.',
        'A3: NH and full-model outer controls are explicitly separated. In-sample and 4-fold predictions are both reported.',
        'Prediction coefficient uncertainty enters a full first-order shared-account/date sandwich.',
        'Crossfit training excludes both roles of accounts hashed to the held-out recipient fold; shared-opponent/date dependence remains clustered.',
        'A3 is observed-history calibration, not an identified bias estimate, selection bound, or test of all unobservables.',
        'B4 contrasts use joint receipt-minus-ordinary influence functions with shared actual accounts and dates.',
        'Units use exact inherited reference SDs (not manuscript-rounded values); each row also gives its native residual score SD.',
        'C material means net own-minus-opponent material change over the last min(4, final ply) plies, including promotions.',
        'C clocks are the certified last observed clock, not clock at disconnection. Missing moves/clocks are explicit classes.',
        'C4 excludes OBSERVED swing exits; any retained unknowns are disclosed, with a matched known-move sensitivity.',
        'C4 is a post-assignment influence check. Observed exit classes do not identify marginal entrants.',
        'A null crude swing proxy does not rule out broader opening or connection-related selection.',
        'All intervals are nominal; generated scores fixed; no headline model is promoted; causal_identification_certified=false.',
        'No network/API/Stockfish work. Private rows, account IDs, moves and influence files are not in this report ZIP.',
        '', 'Environment support counts:']
    lines += [json.dumps(io.clean(r),sort_keys=True) for r in support]
    if unavailable_y:lines+=['','UNAVAILABLE full-row F50 Y analyses due to incomplete follow-up: '+', '.join(unavailable_y)+'. No rows removed and no outcomes filled.']
    lines+=['','Move coverage:']+[json.dumps(r,sort_keys=True) for r in coverage]
    if coverage:
        s=next((r for r in coverage if r['sample']=='S0'),None)
        if s and s['swing_share'] is not None and s['swing_share']<.01:
            lines.insert(2,f'OBSERVED swing exits are {100*s["swing_share"]:.4f}% of S0 (<1%); C4(a) is not estimable under the handoff rule. Missing move rows: {s["missing_move_rows"]:,}.')
    if error:lines+=['', 'STOPPED: '+error,'Completed checkpoints remain reusable; this is not a completed production analysis.']
    (report/'READ_RESULTS.txt').write_text('\n'.join(lines)+'\n')
    manifest=[dict(path=p.name,sha256=io.sha(p),bytes=p.stat().st_size) for p in sorted(report.iterdir()) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    io.js(report/'REPORT_MANIFEST.json',manifest)
    desktop.mkdir(parents=True,exist_ok=True);zip_path=desktop/f'R7_ANALYSIS_REPORT_{conf[:12]}.zip';temp=zip_path.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(temp,zip_path);digest=io.sha(zip_path)
    zip_path.with_suffix('.zip.sha256').write_text(digest+'  '+zip_path.name+'\n')
    io.log('Report: '+str(zip_path)+' | SHA256 '+digest)
    return summary
