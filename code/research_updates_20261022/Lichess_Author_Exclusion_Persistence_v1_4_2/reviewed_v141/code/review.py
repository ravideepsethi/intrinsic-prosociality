"""Read-only review of returned v141 aggregates; no model estimation."""
from compare import *
import argparse
from concurrent.futures import ProcessPoolExecutor


def one_family(job):
    report,family=job
    report=Path(report);aa=report/'tables/included'/family;bb=report/'tables/excluded'/family
    rows=[];coverage=[]
    names=sorted({str(p.relative_to(aa)) for p in aa.rglob('*.csv')} |
                 {str(p.relative_to(bb)) for p in bb.rglob('*.csv')})
    for name in names:
        require((aa/name).is_file() and (bb/name).is_file(),'Missing paired table: '+family+'/'+name)
        out,audit=compare_frames(pd.read_csv(aa/name),pd.read_csv(bb/name),family,name)
        rows.extend(out);coverage.append(audit)
    return rows,coverage


def summary(rows,inventory):
    points=[r for r in rows if r['metric'] in MEASURES and r['status']=='MATCHED']
    return dict(paired_numeric_metrics=sum(r['status']=='MATCHED' for r in rows),
        point_estimates_compared=len(points),tables_compared=len(inventory),
        tables_requiring_alignment_review=sum(r['status']!='COMPARED' for r in inventory),
        tables_with_membership_changes=sum(bool(r.get('included_only',0) or r.get('excluded_only',0)) for r in inventory),
        status_changes=sum(r['status']=='IDENTIFICATION_OR_STATUS_CHANGED' for r in rows),
        sign_changes=sum(bool(r.get('sign_changed')) for r in points),
        approx_95pct_boundary_changes=sum(bool(r.get('crosses_approx_95pct_zero_boundary')) for r in points),
        maximum_absolute_change_in_included_se_units=max((r['absolute_change_in_included_se_units'] for r in points if 'absolute_change_in_included_se_units' in r),default=None),
        substantive_equivalence='REQUIRES_SCIENTIFIC_REVIEW',
        inference='Paired changes in overlapping samples; SE units are a descriptive scale, not an equivalence test.')


def save_frame(path,frame,csv=False):
    frame=pd.DataFrame(frame);frame.to_parquet(path.with_suffix('.parquet'),index=False,compression='zstd')
    if csv:frame.to_csv(path.with_suffix('.csv'),index=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    a.report=a.report.resolve();a.out=a.out.resolve()
    require(a.report!=a.out and a.report not in a.out.parents,'Review must not write within the source report')
    entries=read(a.report/'REPORT_HASHES.json')
    for r in entries:
        source=(a.report/r['file']).resolve()
        require(a.report in source.parents,'Unsafe report path')
        require(source.stat().st_size==r['bytes'] and sha(source)==r['sha256'],'Report content changed: '+r['file'])
    execution=read(a.report/'EXECUTION_STATUS.json');families=execution['paired_families']
    a.out.mkdir(parents=True,exist_ok=True);rows=[];coverage=[]
    log(f'Authenticated {len(entries)} files; comparing {len(families)} families; expected runtime 1–5 minutes.')
    with ProcessPoolExecutor(max_workers=max(1,min(4,a.workers))) as pool:
        for family,(rr,cc) in zip(families,pool.map(one_family,[(str(a.report),f) for f in families])):
            rows.extend(rr);coverage.extend(cc);log('Reviewed '+family)
    result=summary(rows,coverage)
    save_frame(a.out/'before_after',rows)
    save_frame(a.out/'comparison_coverage',coverage,True)
    write(a.out/'COMPARISON_SUMMARY.json',result)
    by_family=[]
    for family in families:
        by_family.append(dict(family=family,**summary([r for r in rows if r['family']==family],[c for c in coverage if c['family']==family])))
    save_frame(a.out/'family_summary',by_family,True)
    points=pd.DataFrame([r for r in rows if r.get('absolute_change_in_included_se_units') is not None])
    save_frame(a.out/'largest_standardized_changes',points.sort_values('absolute_change_in_included_se_units',ascending=False).head(30),True)
    # This candidate failed original-manuscript reproduction. Its paired changes
    # must remain separate from the nineteen successful families.
    candidate_rows=[];candidate_coverage=[]
    for name in ['regressions','normalized_contrasts','equal_account_diagnostic']:
        aa=pd.read_csv(a.report/'failures'/('included_state_persistence_'+name+'.csv'))
        bb=pd.read_csv(a.report/'tables/excluded/state_persistence/report'/(name+'.csv'))
        rr,cc=compare_frames(aa,bb,'state_persistence_candidate','report/'+name+'.csv')
        candidate_rows.extend(rr);candidate_coverage.append(cc)
    save_frame(a.out/'persistence_candidate_comparison',candidate_rows,True)
    write(a.out/'PERSISTENCE_CANDIDATE_STATUS.json',dict(status='FAILED_ORIGINAL_REPRODUCTION',
        claim='Tiny author-exclusion changes in this candidate do not validate its match to the original manuscript.',
        comparison=summary(candidate_rows,candidate_coverage),
        reproduction=read(a.report/'failures/included_state_persistence_REPRODUCTION.json')))
    write(a.out/'REVIEW_PROVENANCE.json',dict(source_report_manifest_sha256=sha(a.report/'REPORT_HASHES.json'),
        verified_report_files=len(entries),source_failed_stages=execution['failed_stages'],
        source_elapsed_minutes=execution['elapsed_minutes'],
        source_claim_status=read(a.report/'CLAIM_STATUS.json'),
        model_refits_performed=0,
        comparison_only_corrections=[
            'First/repeat: collapse exact duplicated clearly_worse aggregates from original UNION ALL; compare multiplicity separately.',
            'Patron five-bin raw/support: use minimum_opportunities_in_each_of_five_bins as a key.',
            'Patron five-bin raw: pair gap_pp with its unpooled_se_pp.',
            'Tenure profile coverage: use returned and disabled flags with profile_source as keys.']))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
