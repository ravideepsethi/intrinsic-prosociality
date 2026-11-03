"""Accurate overlap moments, independently reconciled to exact cell counts.

For cell c, each arm has total weight h_c=n0*n1/(n0+n1). SQL SUM
accumulates rounding error over millions of repeated fractional weights.
FSUM uses compensated summation; the original 1e-11 relative tolerance
and 1e-8 absolute tolerance are retained. No weights are rescaled.
"""
from closeout_common import *
import math

RTOL=1e-11
ATOL=1e-8

def matched_moments(db,audit_path=None):
    """Read views d (selected rows) and cells; return the original group layout.

    The report is saved before raising, including on a genuine disagreement.
    Counts, weight sums, squared weights and both weighted outcomes are checked
    against the independently stored matching-cell counts and means.
    """
    invalid_cells=db.execute('''SELECT count(*) FROM cells WHERE
      n0 IS NULL OR n1 IS NULL OR n0<=0 OR n1<=0 OR n0<>floor(n0) OR n1<>floor(n1)
      OR NOT coalesce(isfinite(y0) AND isfinite(y1) AND isfinite(r0) AND isfinite(r1),FALSE)
      OR least(y0,y1,r0,r1)<0 OR greatest(y0,y1,r0,r1)>1 OR y0>r0 OR y1>r1''').fetchone()[0]
    actual=db.execute('''SELECT arm,count(*),sum(y),sum(reached::INT),
      fsum(weight),fsum(weight*weight),fsum(weight*y),fsum(weight*reached::INT),sum(weight),
      count(*) FILTER(WHERE arm IS NULL OR arm NOT IN (0,1)
        OR NOT coalesce(isfinite(weight),FALSE) OR weight<=0 OR weight>=1
        OR y IS NULL OR reached IS NULL OR y NOT IN (0,1) OR reached NOT IN (0,1) OR y>reached)
      FROM d GROUP BY arm ORDER BY arm''').fetchall()
    reference=db.execute('''SELECT count(*),sum(n0),sum(n1),fsum(h),
      fsum(h*n1::DOUBLE/(n0+n1)),fsum(h*n0::DOUBLE/(n0+n1)),
      fsum(h*y0),fsum(h*y1),fsum(h*r0),fsum(h*r1)
      FROM (SELECT *,n0::DOUBLE*n1::DOUBLE/(n0+n1) h FROM cells)''').fetchone()
    errors=[]
    if invalid_cells or not reference[0]:errors.append('Invalid or empty matching cells')
    if len(actual)!=2 or [r[0] for r in actual]!=[0,1]:errors.append('Expected exactly two non-null arms')
    arms=[];groups=[]
    for r in actual:
        arm,n,ny,nr,sw,sw2,sy,sr,naive,bad=r
        if arm not in (0,1):continue
        expected=[reference[3],reference[4+arm],reference[6+arm],reference[8+arm]]
        observed=[sw,sw2,sy,sr]
        if bad:errors.append('Invalid selected rows in arm '+str(arm))
        if n!=reference[1+arm]:errors.append('Row count differs from cells in arm '+str(arm))
        comparisons=[]
        for label,got,want in zip(('weight_sum','squared_weight_sum','weighted_grants','weighted_reach'),observed,expected):
            finite=got is not None and want is not None and math.isfinite(got) and math.isfinite(want)
            passed=bool(finite and math.isclose(got,want,rel_tol=RTOL,abs_tol=ATOL))
            comparisons.append(dict(moment=label,observed=got,cell_formula=want,passed=passed))
            if not passed:errors.append(label+' differs from cell formula in arm '+str(arm))
        arms.append(dict(arm=arm,rows=n,expected_rows=reference[1+arm],naive_weight_sum=naive,
                         compensated_weight_sum=sw,moments=comparisons))
        if sw is not None and math.isfinite(sw) and sw>0:
            groups.append([arm,n,0,ny,nr,sw,sw2,sy/sw if sy is not None else None,sr/sw if sr is not None else None])
    gap=None;naive_gap=None
    if len(groups)==2:
        gap=abs(groups[0][5]-groups[1][5])/max(groups[0][5],groups[1][5])
        naive_gap=abs(actual[0][8]-actual[1][8])/max(groups[0][5],groups[1][5])
        if not math.isclose(groups[0][5],groups[1][5],rel_tol=RTOL,abs_tol=ATOL):
            errors.append('Compensated overlap weights are not balanced across arms')
    else:errors.append('Missing positive finite arm weight totals')
    audit=dict(status='FAILED' if errors else 'PASSED',summation='DuckDB fsum (compensated)',
      relative_tolerance=RTOL,absolute_tolerance=ATOL,weights_rescaled=False,
      reference='h_c=n0_c*n1_c/(n0_c+n1_c); exact integer arm counts; original cell outcome means',
      strata=reference[0],invalid_cells=invalid_cells,arms=arms,
      naive_relative_arm_gap=naive_gap,compensated_relative_arm_gap=gap,failures=errors)
    if audit_path is not None:save(audit_path,audit)
    require(not errors,'Overlap reconciliation failed: '+'; '.join(errors)+'; see aggregate ORDINARY_WEIGHT_AUDIT report')
    return groups,audit
