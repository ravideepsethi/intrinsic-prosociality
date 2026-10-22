"""Pin source history and refresh bounded February lineage; no new downloads."""
from common import *

def source_evidence():
    d=load(PACKAGE/'source_audit/grace_commit.json');prs=load(PACKAGE/'source_audit/grace_pulls.json')
    pr=next(p for p in prs if p['number']==19258)
    if d['sha']!='f1cca2f8dea59f34c29abf31e225451ff4d05133' or pr['merged_at']!='2026-02-01T10:31:02Z':
        raise RuntimeError('Pinned source history changed')
    patch=next(f['patch'] for f in d['files'] if f['filename']=='modules/round/src/main/RoundSocket.scala')
    return dict(commit=d['sha'],parent=d['parents'][0]['sha'],source_url=d['html_url'],
        author_timestamp=d['commit']['author']['date'],committer_timestamp=d['commit']['committer']['date'],
        pull_request_url=pr['html_url'],merge_timestamp=pr['merged_at'],merge_commit=pr['merge_commit_sha'],patch=patch,
        verified_source_change='Material-disadvantage divisor 3 to 2 at the signed four-point threshold; standard chess is covered.',
        speed_mapping='Base 30 seconds; classical x10, rapid x4, blitz x2, default x1 including bullet and ultrabullet. Registered-player divisor 1.',
        duration_scope='Nominal source formula, not observed disconnect durations or realized user waiting time.',
        deployment_timestamp=None,mechanics_censor=None,
        conclusion='Commit and merge are independently distinct from production deployment. No diagnostic endpoint is adopted.',
        broader_incident_denominator='Targeted time-forfeit candidates, an active-only source overlay, and all-rated-game totals do not establish all platform disconnection incidents.',
        evidence_retrieved_utc='2026-10-02')

def lineage(project):
    old=load(PACKAGE/'authority/previous_february_lineage.json');rows=[];seen=set()
    def note(p,role):
        p=Path(p)
        if str(p) in seen:return
        seen.add(str(p));r=dict(path=str(p),role=role,exists=p.is_file(),rows=None,columns=None)
        if p.is_file():
            r['bytes']=p.stat().st_size
            if p.suffix=='.parquet':
                try:
                    pf=pq.ParquetFile(p);r.update(rows=pf.metadata.num_rows,columns=pf.schema_arrow.names)
                except (OSError,pa.ArrowException):r['read_status']='PARQUET_METADATA_READ_ERROR'
            elif p.suffix=='.json' and p.stat().st_size<4*1024**2:
                try:
                    j=load(p);r['completion_marker']={k:j[k] for k in ('final_ok','status','rows','n_games','n_success','n_failed') if k in j}
                except (ValueError,TypeError):r['read_status']='JSON_NOT_A_COMPLETION_OBJECT'
        rows.append(r)
    # Check the exact producer locations, not a whole-drive or history rescan.
    note(project/'derived/replication/pgn_timeforfeit_candidates/month=2026-02/api_target_candidates_ge5s_or_missing.parquet','canonical full selected candidate frame')
    for base in ('derived/replication/api_timeout_enrichment','derived/replication_36m/api_timeout_enrichment_extension'):
        root=project/base/'month=2026-02';note(root/'_SUCCESS.json','candidate API completion marker')
        for p in sorted((root/'responses').glob('unit-*.parquet')):note(p,'candidate API response part; frame must be authenticated')
    for r in old['known_sources']+old['referenced_candidates']:
        p=r.get('path','')
        if p.endswith('.parquet') and ('feb2026' in p.lower() or '2026-02' in p.lower()):
            note(relocated(p,project),'previously located February product; not automatically a denominator')
    note(project/'derived/replication_36m/receipt_iv_source_api_v100_PRIVATE/final/SOURCE_SUPPLEMENT_READY_PRIVATE.json',
         'completed active-opportunity source overlay; not the full candidate denominator')
    return dict(status='BOUNDED_EXISTING_LINEAGE_REFRESH',files=rows,source_requests=0,
        full_candidate_api_frame_certified=False,
        interpretation='This inventory checks presence and schema only. A located file or completion marker alone does not certify candidate/API coverage or deployment.',
        previous_review='January, March and April selected-frame diagnostics reconciled; February active-only products did not supply the complete candidate denominator.',
        next_evidence_needed='A source-bound February candidate/API join, complete diagnostic windows and a justified production interval or independently chosen conservative analysis censor.')
