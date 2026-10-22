"""Exact August Patron reproduction, separate flag exclusions, stored match groups."""
from fw_common import *
import r8_patron as rp

def drop_flags(d,rule):
    flag=(d.tos_violation.eq(True).fillna(False) if rule=='tos' else d.disabled.eq(True).fillna(False) if rule=='disabled' else rp.flags(d))
    removed=d.loc[(d.is_kind_role==1)&flag,'matched_kind_chooser_id']
    return d.loc[~flag&~d.matched_kind_chooser_id.isin(removed)].copy()

def flag_rows(frame):
    rows=[]
    for scope,mask in [('state_min4',(frame.fair_opps>=4)&(frame.clearly_worse_opps>=4)),('main',frame.group_ever_kind_fair.astype(bool))]:
        f=frame.loc[mask];groups=rp.four_groups(f) if scope=='state_min4' else np.where(f.is_kind_role==1,'competitive_granter','never_granter_control')
        for g in np.unique(groups):
            d=f.loc[groups==g];ret=d.returned.astype(bool);flags=rp.flags(d);N=len(d);nr=int(ret.sum())
            analysis=ret&(d.group_kind_returned.astype(bool) if scope=='main' else True);na=int(analysis.sum())
            r=dict(scope=scope,group=g,accounts=na,acquisition_cohort_accounts=N,returned_profiles=nr,unavailable_queried=int((d.august_planned.astype(bool)&~ret).sum()),not_queried=int((~d.august_planned.astype(bool)).sum()))
            for term,z in [('disabled',d.disabled.eq(True).fillna(False)),('tos',d.tos_violation.eq(True).fillna(False)),('either',flags)]:
                r[term+'_n']=int((z&analysis).sum());r[term+'_share_analysis']=float((z&analysis).sum()/na) if na else None
            for label,z in [('all',analysis),('unflagged',analysis&~flags),('flagged',analysis&flags)]:
                r['patron_rate_'+label]=float(d.loc[z,'patron'].astype(float).mean()) if z.any() else None
            r['unavailable_share_queried']=float((d.august_planned.astype(bool)&~ret).sum()/d.august_planned.sum()) if d.august_planned.sum() else None
            rows.append(r)
    return rows

def run(a,run,key):
    work=run/'A';report=work/'report';report.mkdir(parents=True,exist_ok=True);ak=digest([key,'A']);project=a.project_root
    if completed(work/'final',ak):return load(work/'final/status.json')
    original_root=project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b1_patron'/rp.CORE_CONF[:12]
    require(hashlib.sha256(rp.core.auth.canonical_json(load(original_root/'CONFIGURATION.json')).encode()).hexdigest()==rp.CORE_CONF,'Patron core config differs')
    with heartbeat('A authenticate Patron design'):rp.core.prior.read_checkpoint(original_root/'design',rp.CORE_CONF)
    original=original_root/'design/chooser_design_features_private.parquet';snapshot=rp.core.prior.authenticate_snapshot(project)
    previous,_=rp.core.authenticate_wave3a(project);acquisition=previous/'matching/acquisition_users_private.parquet'
    c=conn(work/'spill',max(2,a.memory_gb-3),1)
    try:
        f=rp.core.load_frames(c,original,snapshot);rp.baseline(f,work/'baseline',digest([ak,'baseline']));del f
        authfolder=work/'author_clean';ck=digest([ak,'author_clean'])
        if completed(authfolder,ck):design=authfolder/'author_clean_design.parquet'
        else:
            sample=rp.core.auth.authenticate_sample(project/u.MAIN_REL,hash_workers=min(a.workers,3))
            sources=[x['path'] for x in sample['month_records']]
            design,census=rp.rebuild_authors(c,sources,acquisition,snapshot,original,authfolder)
            certify(authfolder,ck,[original,acquisition,snapshot]+sources,census)
        f=rp.core.load_frames(c,design,snapshot)
        # Full snapshot flags supply B's exclusion, independent of granting history.
        s=frame(snapshot,['username_norm','tos_violation','disabled','returned']);fl=s.loc[s.returned.astype(bool)&rp.flags(s),'username_norm'].str.strip().str.lower().tolist()
        save(work/'flagged_chooser_names_PRIVATE.json',sorted(set(fl)));del s
    finally:c.close()
    table(report,'tabA1_flags_by_group',flag_rows(f));d,groups,_=rp.features(f);del f
    collector=rp.core.models.ModelCollector();raw=[]
    for rule in ('none','tos','disabled','either'):
        z=d if rule=='none' else drop_flags(d,rule)
        main,state=rp.models(z,groups,rule,collector)
        raw.append(dict(rule=rule,**rp.core.models.raw_row(main,rule,'is_kind_role','PanelA_raw')))
        gr=rp.four_groups(state)
        for name in np.unique(gr):
            w=state.loc[gr==name];raw.append(dict(rule=rule,group=name,accounts=len(w),patrons=int(w.patron.sum()),rate_pp=float(w.patron_pp.mean())))
    co=pd.concat(collector.coefficients,ignore_index=True)
    table(report,'tabA2_patron_excluding_flags',co);table(report,'tabA2_joint_contrasts',collector.contrasts);table(report,'tabA2_raw_rates',raw)
    status=dict(status='ESTIMATED_A1_A2',completed=['A1 flags and availability','A2 all three exclusions with retained focal groups and HC1/cell CR1'],A3='Separate authenticated AFE recipient-model stage',
       profile_snapshot='Original August 2026 snapshot; no refresh',group_policy='Drop a stored matched group when its focal account is removed; no replacement controls.')
    save(work/'final/status.json',status);certify(work/'final',ak,[original,snapshot,acquisition,design],outputs=list(report.glob('*'))+[work/'flagged_chooser_names_PRIVATE.json']);return status
