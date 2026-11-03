"""Integrate new aggregates into the RA's tables; retain original source archives."""
from common_retained import *

def f5_wide(records):
    grouped={}
    for i,r in enumerate(records,2):
        sample=r.get('sample');term=r.get('term')
        if not sample or term not in ('first_stage','rf_y','rf_reached','iv_y','ols_y'):continue
        row=grouped.setdefault(sample,dict(specification=sample,n=r.get('n'),recipients=r.get('recipients'),history=r.get('history'),recipient_fe=r.get('recipient_fe'),covariance=r.get('covariance')))
        for k in ('coefficient','standard_error','p_value','ci95_low','ci95_high','wald_F'):
            if r.get(k) not in (None,''):row[term+'_'+k]=r[k]
        row[term+'_source_file']=r.get('source_file','');row[term+'_source_row']=r.get('source_row',i)
    return list(grouped.values())

def cell_lineage(row,column):
    """Resolve a printed number to its input column, including the F5 pivot."""
    source=row.get('source_file','');source_row=row.get('source_row','');field=column
    for j in range(1,7):
        prefix=f'column_{j}_'
        if column.startswith(prefix) and row.get(prefix+'source_file'):
            return dict(source_file=row[prefix+'source_file'],source_row=row[prefix+'source_row'],source_column=column[len(prefix):],source_pointer='')
    for term in ('first_stage','rf_y','rf_reached','iv_y','ols_y'):
        if column.startswith(term+'_') and row.get(term+'_source_file'):
            source=row[term+'_source_file'];source_row=row.get(term+'_source_row','');field=column[len(term)+1:];break
    if not source:
        for term in ('first_stage','rf_y','rf_reached','iv_y','ols_y'):
            if row.get(term+'_source_file'):
                source=row[term+'_source_file'];source_row=row.get(term+'_source_row','');break
    if row.get('term','').startswith('conditional_first_stage_'):
        field={'coefficient':'coefficient_pp','standard_error':'standard_error_pp','p_value':'p_value_asymptotic'}.get(column,column)
    return dict(source_file=source,source_row=source_row,source_column=field,source_pointer=row.get('source_pointer',''))

def export(a,run,conf):
    from balance_retained import combine
    required=['ACT_SYSTEM.json','table_D6_complier_characteristics.csv','table_D2_implied_bias.csv','DIAGNOSTIC_FRAME_COUNTS.json','DESIGN_COUNTS.json']
    require(all((run/'report'/p).is_file() for p in required),'One of the three authorized families is incomplete')
    combine(a,run,conf)
    dst=run/'report/RA_TABLES';shutil.copytree(ROOT/'evidence',dst,dirs_exist_ok=True)
    (dst/'checksums.txt').unlink(missing_ok=True)
    raw=dst/'raw';raw.mkdir(exist_ok=True);tables=dst/'tables';tables.mkdir(exist_ok=True)
    for name in required+['BALANCE_TRAITS.csv','BALANCE_JOINT.csv','table_F6.csv']:
        shutil.copy2(run/'report'/name,raw/name)
    def load_new(name):
        return [dict(r,source_file='raw/'+name,source_row=i+2) for i,r in enumerate(csv_rows(raw/name))]
    write_csv(tables/'table_F6.csv',csv_rows(raw/'table_F6.csv'))
    write_csv(tables/'table_D6_complier_characteristics.csv',load_new('table_D6_complier_characteristics.csv'))
    write_csv(tables/'table_D2_implied_bias.csv',load_new('table_D2_implied_bias.csv'))
    act=read(raw/'ACT_SYSTEM.json');require(len(act['estimates'])==7 and len(act['first_stages'])==6,'Act system must have seven estimates and six first stages')
    act_rows=[]
    for i,r in enumerate(act['estimates']):
        require(r['outcome']=='y','Unauthorized additional act outcome')
        act_rows.append(dict(r,panel='B',source_file='raw/ACT_SYSTEM.json',source_pointer=f'/estimates/{i}'))
    values=[r.get('conditional_F') for r in act['first_stages']]
    require(all(v is not None and math.isfinite(v) and v>=0 for v in values),'Conditional first-stage test unsupported; inspect ACT_SYSTEM.json')
    k=int(np.argmin(values));fs=act['first_stages'][k]
    act_rows.append(dict(panel='diagnostic',term='minimum_conditional_first_stage_F',conditional_F=values[k],
        n=fs['n'],recipients=fs['recipients'],account_clusters=fs.get('account_clusters'),date_clusters=fs.get('date_clusters'),
        source_file='raw/ACT_SYSTEM.json',source_pointer=f'/first_stages/{k}',note='Minimum across all six instrumented columns; full first-stage system retained in source JSON'))
    write_csv(tables/'table_D5_panelB.csv',act_rows)
    recon=csv_rows(dst/'RECONCILIATION.csv')
    destinations={'position_and_stakes_receipt_heterogeneity':'tables/table_D5_panelB.csv','spaced_complier_characteristics':'tables/table_D6_complier_characteristics.csv'}
    for r in recon:
        if r.get('status')=='AUTHORIZED_PENDING_RUN':
            r['status']='COMPUTED';r['note']='Computed on the authenticated spaced design; see the table and per-cell lineage.'
            r['source_file']=destinations.get(r.get('item'),'tables/table_F6.csv; tables/table_D2_implied_bias.csv')
    # Preserve archive gaps, undecided figure mapping, and companion requests
    # outside this run. Never turn their historical values into new estimates.
    for r in read(raw/'DIAGNOSTIC_FRAME_COUNTS.json'):
        recon.append(dict(paper_location='F.6 diagnostic frame',item=r['frame']+'_row_count',old_value=r['reference_count_in_note'],new_value=r['n'],
            source_file='raw/DIAGNOSTIC_FRAME_COUNTS.json',source_column='n',status='CONFIRMED' if r['reference_count_matches'] else 'UPDATED_DIAGNOSTIC_COUNT_REVIEW',
            note='Actual fixed-rule diagnostic count. Exposure rows used by the three analyses are unchanged.'))
    index=[]
    for path in sorted(tables.glob('*.csv')):
        rr=csv_rows(path);index.append(dict(file=str(path.relative_to(dst)),rows=len(rr)))
        for i,row in enumerate(rr,2):
            for field,value in row.items():
                if value in (None,'') or field.endswith('_source_row') or field=='source_row':continue
                try:number=float(value)
                except (ValueError,TypeError):continue
                if not math.isfinite(number):continue
                lineage=cell_lineage(row,field)
                if not lineage['source_file']:
                    lineage.update(source_file=path.relative_to(dst).as_posix(),source_row=i,source_column=field)
                recon.append(dict(paper_location=path.name,item=f'CSV row {i}: {field}',old_value='',new_value=value,status='SOURCE_BACKED',
                    note='CSV source_row includes the header (first data row is 2); JSON uses source_pointer.',**lineage))
    write_csv(dst/'RECONCILIATION.csv',recon);write_csv(dst/'TABLE_INDEX.csv',index)
    pending=[r for r in recon if r.get('status') in ('ARCHIVE_GAP','PENDING_OUTSIDE_THREE_RUNS','FIGURE_MAPPING_UNRESOLVED','UPDATED_DIAGNOSTIC_COUNT_REVIEW')]
    method=read(ROOT/'METHOD.json');method.update(status='THREE_RUNS_COMPUTED_MANUSCRIPT_PENDING',configuration=conf,whole_paper_complete=False,production_analyses_executed=True,pending_items=pending)
    save(dst/'METHOD.json',method)
    for family,details in method['families'].items():save(dst/'methods'/family/'METHOD.json',dict(status='COMPUTED',configuration=conf,**details))
    (dst/'README.txt').write_text('The three authorized analysis families have completed. This is not a whole-paper completion certificate. Review RECONCILIATION.csv and METHOD.json for unresolved archive-only numbers, companion requests outside these three runs, diagnostic-frame count differences and Figure 4 caption mapping. No dropped analysis was run or supplied as a result. All table sources are included. CSV source_row counts the header as row 1. The four position effects and the two stake interactions use exactly the additional controls specified in the revised note. Private row-level data remain on the Mac.\n')
    files=[p for p in sorted(dst.rglob('*')) if p.is_file() and p.name!='checksums.txt']
    (dst/'checksums.txt').write_text(''.join(sha(p)+'  '+p.relative_to(dst).as_posix()+'\n' for p in files))
    save(run/'report/INTEGRATION_CHECKS.json',dict(tables=len(index),checksum_files=len(files),whole_paper_complete=False,authorized_families_computed=3,pending_items=len(pending)))
