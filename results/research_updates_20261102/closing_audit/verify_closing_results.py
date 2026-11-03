"""Verify this closing delivery; optionally verify the original package archives.

    python verify_closing_results.py
    python verify_closing_results.py --packages-dir /path/containing/package/zips

Standard library only. No private data, model fits, figures, network, or edits.
"""
from pathlib import Path
import argparse,csv,hashlib,json,math

ROOT=Path(__file__).resolve().parent
def rows(name):return list(csv.DictReader((ROOT/name).open()))
def require(condition,message):
    if not condition:raise RuntimeError(message)
def close(x,y):return math.isclose(float(x),float(y),rel_tol=1e-11,abs_tol=1e-11)
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def verify(packages_dir=None):
    audit=rows('NULL_SENTINEL_AUDIT.csv')
    require(sum(r['status']=='affected' for r in audit)==1,'Unexpected affected-output inventory')
    require(all(r['reestimated_this_audit']=='False' for r in audit),'Unexpected re-estimation in audit')
    reconciliation=rows('RECONCILIATION.csv')[0]
    require((int(reconciliation['old_N']),int(reconciliation['new_N']))==(314639,625066),'Wrong censor N')
    require(int(reconciliation['new_N'])-int(reconciliation['old_N'])==int(reconciliation['restored_N']),'Censor row accounting fails')
    require(close(reconciliation['new_estimate_pp'],1.121583658124428),'Wrong censor estimate')
    cr=rows('CLAIM_ERROR_BY_RD.csv')
    require(sum(int(r['eligible_claims']) for r in cr)==40943232,'Claim eligibility mismatch')
    require(sum(int(r['paired_claims']) for r in cr)==40707278,'Claim paired denominator mismatch')
    pooled=next(r for r in rows('evidence/corrected_rating/RATING_VALIDATION.csv') if r['group']=='claim__action_payoff')
    for field in ['mean_absolute_error','mean_signed_error_predicted_minus_recorded']:
        weighted=math.fsum(int(r['paired_claims'])*float(r[field]) for r in cr)/40707278
        require(close(weighted,pooled[field]),'Claim bins do not reproduce corrected '+field)
    cost=rows('evidence/cost/validation_pooled.csv')
    high=next(r for r in cost if r['arm']=='chooser_claimed_win' and r['group']=='own_RD_gt110' and r['variant']=='old_unregulated')
    require(sum(int(r['eligible_claims']) for r in cr[1:])==int(high['rows']),'High-RD eligible claims changed')
    require(sum(int(r['paired_claims']) for r in cr[1:])==int(high['observed']),'High-RD paired claims changed')
    raw=rows('evidence/post_panel/reconstruction_cells.csv')
    for r in rows('POST_CHANGE_VALIDATION.csv'):
        labels=['45 <= RD < 45.01 (floor)','45.01 <= RD < 60','60 <= RD < 100','100 <= RD < 200','RD >= 200']
        k=labels.index(r['rd_bin']);a=[x for x in raw if x['phase']==r['phase'] and int(x['rd_bin'])==k]
        n=sum(int(float(x['n'])) for x in a)
        require(n==int(r['player_updates']),'Post-panel denominator mismatch')
        for source,target in [('sum_abs_error','mean_absolute_error'),('sum_error','mean_signed_error_predicted_minus_recorded')]:
            require(close(math.fsum(float(x[source]) for x in a)/n,r[target]),'Post-panel statistic mismatch')
    for r in rows('EVIDENCE_FILE_HASHES.csv'):
        p=ROOT/r['file'];require(sha(p)==r['sha256'] and p.stat().st_size==int(r['bytes']),'Evidence bytes differ: '+r['file'])
    files=packages=0
    if (ROOT/'checksums.txt').exists():
        for line in (ROOT/'checksums.txt').read_text().splitlines():
            if not line or line.startswith('#'):continue
            expected,name=line.split('  ',1)
            if name.startswith('packages/'):
                if packages_dir is None:continue
                p=Path(packages_dir)/name.removeprefix('packages/');packages+=1
            else:p=ROOT/name;files+=1
            require(p.is_file() and sha(p)==expected,'Checksum mismatch or missing file: '+str(p))
    return dict(status='PASS',audit_rows=len(audit),claim_bins=len(cr),payload_checksums_verified=files,
                external_archives_verified=packages,
                external_archive_note='Pass --packages-dir to verify your archive copies.' if packages_dir is None else 'All named archive checksums matched.',
                private_model_runs=0)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--packages-dir',type=Path);args=parser.parse_args()
    print(json.dumps(verify(args.packages_dir),indent=2))
