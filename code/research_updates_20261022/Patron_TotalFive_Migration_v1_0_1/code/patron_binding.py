"""Authenticate completed coverage audit and prepare only two projected model datasets."""
import concurrent.futures
from patron_common import *

def bind(project,coverage,authority):
    conf=authority['coverage_config'];cfg=load(coverage/'config_PRIVATE.json')
    require(cfgsha(cfg)==conf,'Wrong completed coverage configuration')
    checked(coverage/'report/REPORT_MANIFEST.json',authority['coverage_report_manifest_sha256'])
    for r in authority['coverage_report_members']:checked(coverage/'report'/r['path'],r['sha256'],r['bytes'])
    require(load(coverage/'report/summary.json')['status']=='COVERAGE_AUDIT_COMPLETE','Coverage audit is not complete')
    expected={r['role']:r for r in authority['source_records']};actual=cfg['inputs']
    require(set(actual)==set(expected),'Coverage input-role set differs')
    def verify(item):
        role,r=item;e=expected[role]
        require(r['sha256']==e['sha256'] and r['bytes']==e['bytes'],'Coverage source binding differs: '+role)
        return role,str(checked(relocate(r['path'],project),e['sha256'],e['bytes']))
    log('Authenticate all '+str(len(actual))+' existing source files; no API work')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:paths=dict(pool.map(verify,actual.items()))
    verify_stage(coverage/'accounts',conf)
    accounts=coverage/'accounts/recipient_profiles_PRIVATE.parquet'
    require(accounts.is_file(),'Verified account map missing')
    # Do not infer new identities or reconstruct different profile sampling.
    return dict(paths=paths,accounts=str(accounts),coverage=str(coverage),
                accounts_sha256=sha(accounts),coverage_config=conf)

