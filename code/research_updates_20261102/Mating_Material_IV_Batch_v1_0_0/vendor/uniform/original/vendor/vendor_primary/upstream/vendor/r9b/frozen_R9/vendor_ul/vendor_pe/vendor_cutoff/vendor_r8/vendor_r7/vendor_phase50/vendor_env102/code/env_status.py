"""Validate recorded endings without treating absent legacy metadata as a result.

A Parquet column containing only nulls can be materialized as a nullable integer
by DuckDB and read by Arrow/NumPy as floating NaN. The frozen active_timeout
label remains authoritative for these legacy rows. Missing status is NOT a
non-timeout, outoftime, or any other observed ending.
"""
from env_common import *


def inspect(d,cohort='unspecified'):
    raw=np.asarray(d['status']);n=len(raw)
    missing=np.fromiter((v is None or isinstance(v,(float,np.floating)) and np.isnan(v) for v in raw),bool,count=n)
    text=np.fromiter((isinstance(v,(str,np.str_)) for v in raw),bool,count=n)
    # Do not turn unknown codes or literal 'nan'/'None' strings into missing data.
    valid_label=text & np.isin(raw,sorted(core.TERMINAL))
    invalid=~missing & ~valid_label
    known=~missing & ~invalid
    mismatch=known & (np.asarray(d['active_timeout'],bool)!=(raw=='timeout'))
    previous=np.asarray(d['previous_frame'])
    if not np.isin(previous,[False,True]).all():raise RuntimeError('Missing or nonbinary previous_frame in status audit')
    previous=previous.astype(bool)
    counts={name:int(np.count_nonzero(known & (raw==name))) for name in sorted(core.TERMINAL)}
    summary=dict(cohort=cohort,rows=n,recorded_status_rows=int(known.sum()),missing_status_rows=int(missing.sum()),
        missing_legacy_rows=int((missing & previous).sum()),missing_expansion_rows=int((missing & ~previous).sum()),
        missing_as_None=int(sum(v is None for v in raw)),missing_as_numeric_NaN=int(sum(isinstance(v,(float,np.floating)) and np.isnan(v) for v in raw)),
        invalid_nonmissing_status_rows=int(invalid.sum()),recorded_timeout_label_mismatches=int(mismatch.sum()),
        ending_counts=counts,ending_regressions_available=bool(n and known.all()),
        entry_labels_preserved=True,missing_status_rows_excluded_from_entry_models=0)
    summary['valid']=not any(summary[k] for k in ('missing_expansion_rows','invalid_nonmissing_status_rows','recorded_timeout_label_mismatches'))
    return known,summary


def validate(d,cohort='unspecified'):
    known,summary=inspect(d,cohort)
    if not summary['valid']:
        raise RuntimeError('Status audit failed for '+cohort+': '+json.dumps({k:summary[k] for k in ('missing_expansion_rows','invalid_nonmissing_status_rows','recorded_timeout_label_mismatches')})+'. No labels changed; inspect status_coverage.json.')
    return known,summary


def audit_prepared(prepared,root,conf):
    """Write all aggregate diagnostics before deciding whether models may run."""
    def build(tmp):
        rows=[]
        for cohort in COHORTS:
            path=Path(prepared)/(cohort+'.parquet')
            checked_columns(path,['status','previous_frame','active_timeout'])
            _,summary=inspect(arrays(io.read(path,['status','previous_frame','active_timeout'])),cohort)
            summary['physical_status_type']=str(pq.ParquetFile(path).schema_arrow.field('status').type)
            rows.append(summary)
            io.log(f'{cohort}: {summary["recorded_status_rows"]:,} recorded endings; {summary["missing_legacy_rows"]:,} missing legacy endings; {summary["recorded_timeout_label_mismatches"]:,} recorded-label disagreements')
        io.js(tmp/'status_coverage.json',rows)
        oldreport.write_rows(tmp,'status_coverage',rows)
        return dict(valid=all(r['valid'] for r in rows),missing_status_rows_by_cohort={r['cohort']:r['missing_status_rows'] for r in rows})
    return stable_stage(root,conf,build,[Path(prepared)/(c+'.parquet') for c in COHORTS])
