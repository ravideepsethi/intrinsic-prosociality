"""Frame accounting only. Current Score A estimates are exported separately."""
from phase100_common import *
from release100 import zip_report
import time

def export(root,desktop,conf,coverage,status,started,details=None):
    folder=root/'report';folder.mkdir(exist_ok=True)
    summary=dict(version='1.0.0',status=status,phase_percent=100,config_sha256=conf,
        network_requests=0,stockfish_searches=0,behavioral_estimates_computed=False,
        fixed_additional_frame_rows=sum(x['selected_frame_rows'] for x in coverage),
        pool_games_before_chronology=sum(x['pool_rows'] for x in coverage),
        ordinary_games_before_chronology=sum(x['ordinary_rows'] for x in coverage),
        unresolved_selected_rows=sum(x['unresolved_rows'] for x in coverage),
        elapsed_seconds=time.monotonic()-started,abstract_gate_cleared=False)
    summary.update(details or {})
    for name,path in [('metadata_quarantine',root/'quarantine/summary.json'),
        ('quarantine_diagnostic',root/'quarantine_diagnostic.json'),('early_eligibility',root/'early/summary.json'),
        ('score_support',root/'support/summary.json'),('chronology_eligibility',root/'work/summary.json'),
        ('feature_bridge',root/'split/bridge.json'),('performance',root/'performance.json'),
        ('original_numerical_reproduction',root/'prepared/baseline_reproduction.json'),
        ('original_feature_check',root/'baseline_feature_check/summary.json')]:
        if path.is_file():
            data=io.load(path);summary[name]=data;io.js(folder/(name+'.json'),data)
    if status=='PHASE_100_FRAMES_COMPLETE':
        env_common.checked_stage_files(root/'split',conf,['bridge.json','entry_new_phase100.parquet','ordinary_new_phase100.parquet'])
        bridge=io.load(root/'split/bridge.json')
        if not bridge['checks'] or not all(v['game_identity_and_all_features_reproduced'] for v in bridge['checks']):raise RuntimeError('Prior 75% feature bridge did not pass')
        summary['sample_accounting']=bridge['sample_counts']
        if summary['unresolved_selected_rows'] and not summary.get('metadata_quarantine'):raise RuntimeError('Unresolved exclusions have no audit')
    write_rows(folder,'frame_dispositions',[dict(month=v['month'],disposition=k,rows=n) for v in coverage for k,n in v['dispositions'].items()])
    write_rows(folder,'coverage_by_ending',[x for v in coverage for x in v['ending_counts']])
    io.js(folder/'summary.json',summary)
    (folder/'READ_RESULTS.txt').write_text('Full fixed-hash comparison frame: '+status+'\n'
        'This is sample accounting, not behavioral estimates. The next stage fits current Score A.\n'
        'Three previously reviewed focal exclusions are carried only after exact identity and metadata checks. Any new discrepancy stops and is reported.\n'
        'The completed 75% games and every saved feature must reproduce by game identity, with row IDs rebound.\n')
    zip_report(folder,desktop,'RUN2_PHASE_100_FRAMES_REPORT_'+conf[:12]);return summary
