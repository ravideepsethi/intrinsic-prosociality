"""Rebuild badge coverage and original acquisition weights for Model 5 accounts."""
from common5 import *
import re,concurrent.futures as cf
sys.path.insert(0,str(ROOT/'vendor_badge/code'))
import badge_audit as badge
import patron_common as legacy

PROFILE_FIELDS=['identity_resolved','in_original_chooser_universe','originally_selected','profile_returned','patron','sampling_fraction','query_ms','original_ever_kind','coverage_status']

def authenticate(a):
    authority=load(ROOT/'vendor_badge/evidence/patron_authority.json')
    coverage=a.project/'derived/replication/patron_iv_coverage_v100_PRIVATE'/authority['coverage_config'][:12]
    cfg=load(coverage/'config_PRIVATE.json')
    require(legacy.cfgsha(cfg)==authority['coverage_config'],'Wrong original badge coverage configuration')
    legacy.checked(coverage/'report/REPORT_MANIFEST.json',authority['coverage_report_manifest_sha256'])
    for r in authority['coverage_report_members']:legacy.checked(coverage/'report'/r['path'],r['sha256'],r['bytes'])
    require(load(coverage/'report/summary.json')['status']=='COVERAGE_AUDIT_COMPLETE','Original badge audit incomplete')
    expected={r['role']:r for r in authority['source_records']}
    roles=['chooser','acquisition','snapshot','cell_diagnostics','plan_summary','dictionary_check']
    roles+=sorted(k for k in expected if re.fullmatch('dictionary_[0-9]{4}',k))
    def check(role):
        actual=cfg['inputs'][role];ref=expected[role]
        require((actual['sha256'],actual['bytes'])==(ref['sha256'],ref['bytes']),'Badge source identity differs: '+role)
        p=legacy.checked(legacy.relocate(actual['path'],a.project),ref['sha256'],ref['bytes']);return role,str(p)
    with cf.ThreadPoolExecutor(max_workers=2) as pool:paths=dict(pool.map(check,roles))
    save(a.run/'report/badge_input_hashes.json',[{k:expected[role][k] for k in ('role','sha256','bytes')} for role in roles])
    inp={k:paths[k] for k in ('chooser','acquisition','snapshot','cell_diagnostics','plan_summary')}
    inp['dictionary']=[paths[k] for k in roles if re.fullmatch('dictionary_[0-9]{4}',k)]
    inp['dictionary_column']=load(paths['dictionary_check'])['selected_explicit_ID_column']
    return inp,paths

def attach(con,source,accounts,out):
    con.execute('CREATE VIEW src AS SELECT *,count(*) OVER(PARTITION BY recipient_id)::BIGINT model5_exposures_per_recipient FROM '+badge.parq(source))
    con.execute('CREATE VIEW acc AS SELECT * FROM '+badge.parq(accounts))
    for view,key in [('src','row_id'),('acc','recipient_id')]:
        require(con.execute('SELECT count(*)-count(DISTINCT '+key+') FROM '+view).fetchone()[0]==0,'Duplicate '+view+' key')
    fields=','.join('acc.'+x for x in PROFILE_FIELDS)
    badge.copy(con,'SELECT src.*,'+fields+',coalesce(acc.sampling_fraction>0,FALSE) positive_support FROM src LEFT JOIN acc USING(recipient_id) ORDER BY src.row_id',out)
    con.execute('CREATE OR REPLACE VIEW linked AS SELECT * FROM '+badge.parq(out))
    require(con.execute('SELECT count(*) FROM linked').fetchone()[0]==pq.ParquetFile(source).metadata.num_rows,'Badge linkage changed frame size')
    require(con.execute('SELECT count(*) FROM linked WHERE NOT coalesce(identity_resolved,FALSE) OR (profile_returned AND (patron IS NULL OR NOT positive_support OR query_ms IS NULL OR query_ms<=archive_start_ms)) OR (NOT profile_returned AND patron IS NOT NULL)').fetchone()[0]==0,'Invalid badge identity, missingness, support or timing')

def prepare(a):
    c.frozen.u.no_network();binding=load(a.run/'PRIVATE/BINDING.json');inp,paths=authenticate(a)
    counts=load(ROOT/'vendor_badge/evidence/badge_authority.json')['counts']
    def build(tmp):
        con=badge.connect(tmp,min(a.workers,2),a.memory_gb)
        try:
            info=badge.build_accounts(con,inp,None,tmp/'accounts',counts,frame_paths=[binding['source']])
            require(info['identity_unresolved']==0,'Unresolved Model 5 recipient identities')
            accounts=tmp/'accounts/recipient_profiles_PRIVATE.parquet'
            attach(con,binding['source'],accounts,tmp/'linked.parquet')
            profile=records(con,'SELECT coverage_status,count(*) exposures,count(DISTINCT recipient_id) recipients FROM linked GROUP BY 1 ORDER BY 1')
            summary=records(con,'SELECT count(*) exposures,count(DISTINCT recipient_id) recipients,sum(profile_returned::BIGINT) observed_exposures,count(DISTINCT recipient_id) FILTER(WHERE profile_returned) observed_recipients,count(DISTINCT recipient_id) FILTER(WHERE patron) observed_unique_patrons,sum(coalesce(patron,FALSE)::BIGINT) patron_exposure_rows,count(*) FILTER(WHERE NOT positive_support) zero_support_exposures,count(DISTINCT recipient_id) FILTER(WHERE NOT positive_support) zero_support_recipients,count(*) FILTER(WHERE originally_selected AND NOT profile_returned) nonreturn_exposures FROM linked')[0]
            require((summary['exposures'],summary['recipients'])==(cert.N,cert.PEOPLE),'Wrong Model 5 badge denominator')
            timing=records(con,'SELECT min((query_ms-archive_start_ms)/86400000.) min_days,median((query_ms-archive_start_ms)/86400000.) median_days,max((query_ms-archive_start_ms)/86400000.) max_days FROM linked WHERE profile_returned')[0]
            prior=records(con,'SELECT count(*) exposures,count(DISTINCT recipient_id) recipients,count(*) FILTER(WHERE NOT positive_support) zero_support_exposures,sum(profile_returned::BIGINT) observed_exposures,count(DISTINCT recipient_id) FILTER(WHERE patron) unique_patrons FROM linked WHERE fair_90>0')[0]
            diagnostics=[]
            for name,weight in [('exposure_IPW','1.0/sampling_fraction'),('recipient_IPW','1.0/sampling_fraction/model5_exposures_per_recipient'),('observed_unweighted','1.0')]:
                row=records(con,'SELECT sum(w) sum_weights,max(w) maximum_weight,sum(w)*sum(w)/sum(w*w) kish_effective_rows,sum(w*patron)/sum(w)*100 weighted_patron_rate_pp FROM (SELECT '+weight+' w,patron::INTEGER patron FROM linked WHERE profile_returned)')[0]
                diagnostics.append(dict(model=name,**row))
            unique=records(con,'SELECT sum(w)*sum(w)/sum(w*w) kish_effective_recipients FROM (SELECT DISTINCT recipient_id,1.0/sampling_fraction w FROM linked WHERE profile_returned)')[0]
            save(tmp/'coverage_summary.json',dict(summary,**unique));table(tmp/'coverage_status',profile);save(tmp/'snapshot_lags.json',timing)
            save(tmp/'prior_chooser_support.json',prior);table(tmp/'weight_diagnostics',diagnostics)
            table(tmp/'coverage_by_month',records(con,'SELECT month_code,count(*) exposures,sum(profile_returned::BIGINT) observed_exposures,count(*) FILTER(WHERE NOT positive_support) zero_support_exposures,count(DISTINCT recipient_id) FILTER(WHERE patron) unique_patrons FROM linked GROUP BY 1 ORDER BY 1'))
            # A private candidate list is prepared for a possible SEPARATE current
            # profile wave; it is never queried automatically or mixed with August.
            badge.copy(con,"SELECT recipient_id,username_norm,coverage_status FROM "+badge.parq(accounts)+" WHERE NOT profile_returned ORDER BY recipient_id",tmp/'missing_profiles_PRIVATE.parquet')
            save(tmp/'profile_pull_assessment.json',dict(new_requests=0,missing_recipients=summary['recipients']-summary['observed_recipients'],outside_support_recipients=summary['zero_support_recipients'],current_wave_required_to_run_this_test=False,
                conclusion='Existing August profiles support this analysis on their acquisition-support population. Decide on a new common-date wave after the observed sample, interval and coverage diagnostics are known. A current pull cannot recover missing August status.',
                if_following_up='Query the full fixed Model 5 recipient roster in one new observation window, retain old August outcomes separately; never patch missing August badges with current values.'))
            return summary
        finally:con.close()
    folder,info=stage(a.run/'PRIVATE/badges',a.conf,build,[binding['source']]+list(paths.values()))
    for p in folder.iterdir():
        if p.suffix in ('.json','.csv') and p.name!='PATRON5_DONE.json':shutil.copyfile(p,a.run/'report'/p.name)
    shutil.copyfile(folder/'accounts/original_sampling_cells.csv',a.run/'report/original_sampling_cells.csv')
    shutil.copyfile(folder/'accounts/profile_checks.json',a.run/'report/profile_checks.json')
    save(a.run/'PRIVATE/BADGE_PATHS.json',dict(linked=str(folder/'linked.parquet'),scores=binding['scores'],accounts=str(folder/'accounts/recipient_profiles_PRIVATE.parquet')))
    return folder
if __name__=='__main__':
    a=parser().parse_args()
    with cert.heartbeat('Model 5 badge linkage and original sampling weights'):prepare(a)
