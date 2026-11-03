"""Production equivalence check: R11 pooled-gap column 3 equals R10 column 3."""
from common import *
from design import POSITIONS,STAGES,REGIONS,GAP_NAMES
import zipfile,io

def compare_archived_r10(run):
    path=ROOT/'evidence/R10_REPORT_6bb9fb7c3d51_075.zip'
    require(sha(path)==load(ROOT/'authority/R10_REUSE_AUTHORITY.json')['report_sha256'],'Archived R10 report checksum differs')
    with zipfile.ZipFile(path) as archive:
        old=np.load(io.BytesIO(archive.read('report/covariance_column3.npz')),allow_pickle=False)
        old_names=old['names'].tolist();old_values=np.r_[old['beta'],old['moment_means']];old_cov=old['covariance']
    with np.load(run/'report/covariance_column3.npz',allow_pickle=False) as new:
        new_names=new['names'].tolist();new_values=np.r_[new['beta'],new['moment_means']];new_cov=new['covariance']
    def value(names,values,cov,weights):
        j=np.zeros(len(names))
        for name,w in weights.items():j[names.index(name)]=w
        return float(j@values),float(np.sqrt(max(0,j@cov@j)))
    terms=[]
    for name in ['position_'+p for p in POSITIONS[1:]]+GAP_NAMES[:-1]+['log1p_clock_c','log1p_clock_d','log_premium','log_premium_sq','log_rd_c','log_rd_c_sq','log_rd_d','log_rd_d_sq']:
        terms.append((name,{name:1},{name:1}))
    for region in REGIONS:
        for stage in STAGES[1:]:
            name='stage_'+stage;old_weights={name:1}
            if region=='competitive':old_weights[name+':competitive']=1
            terms.append((name+':'+region,old_weights,{name+':'+region:1}))
    rows=[]
    for name,old_weights,new_weights in terms:
        a,sa=value(old_names,old_values,old_cov,old_weights);b,sb=value(new_names,new_values,new_cov,new_weights)
        ok=bool(np.isclose(a,b,rtol=1e-5,atol=1e-6) and np.isclose(sa,sb,rtol=1e-5,atol=1e-7))
        rows.append(dict(term=name,r10_estimate=a,r11_estimate=b,estimate_difference=b-a,r10_se=sa,r11_se=sb,se_difference=sb-sa,passed=ok))
    table(run/'report/pooled_gap_R10_comparison',rows)
    result=dict(status='MATCH' if all(r['passed'] for r in rows) else 'MISMATCH',terms_checked=len(rows),
      max_abs_estimate_difference=max(abs(r['estimate_difference']) for r in rows),max_abs_se_difference=max(abs(r['se_difference']) for r in rows),
      estimate_tolerance='absolute 1e-6 + relative 1e-5',se_tolerance='absolute 1e-7 + relative 1e-5',r10_report_sha256=sha(path))
    dump(run/'report/POOLED_GAP_R10_CHECK.json',result)
    require(result['status']=='MATCH','Pooled-gap model does not reproduce archived R10 column 3; regression completion withheld')
    log('R10 pooled-gap equivalence gate passed: '+str(result['terms_checked'])+' estimates and clustered SEs')
    return result
