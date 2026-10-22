#!/usr/bin/env python3
from engine import *
from compare import export_tables,compare_all
import argparse,fcntl,subprocess,traceback,zipfile,platform
import uuid
from runtime import announce,estimate

STAGES=['core','panel_robustness','rating_gap','nonparametric','controlled_reference','merit','r11','session','patron','receipt','activity']
LABELS={'core':'Main descriptives, board/price results, prior kindness, year/random-half persistence',
 'panel_robustness':'Panel-only robustness','rating_gap':'Rating-gap analysis','nonparametric':'Nonparametric rating gradients',
 'controlled_reference':'Controlled reference-price model and figure','merit':'Continuous board merit and material',
 'r11':'Three-column region/gap models and stage composition','session':'Session position, accumulated play, both history-count scenarios',
 'patron':'Primary Patron ladder, diagnostic states, dose, price and date sensitivity',
 'receipt':'Matched receipt, subsequent choices, reentry, donor propensities, overlap weights and exact-hour sensitivity',
 'activity':'Equal-account state rates, fixed activity groups, standardization, ratios and joint uncertainty'}
# An explicit paper-wide ledger. No legacy result is silently cleared because
# its direct focal hit count is zero or its parent main panel was filtered.
OPEN_FAMILIES={
 'iv_current':'Current all-time Score A primary and R9 lineage audited separately; no new author-included IV counterfactual is fitted.',
 'patron_remaining':'Opportunity-level recipient Patron, 100 rematches and remaining Wave3B2 sensitivities require their original roster-specific adapters.',
 'mechanisms_responsibility':'A2 responsibility/trajectory, material mechanisms, frozen sampled subsets and prediction baselines need source-specific refits.',
 'reputation_stakes_color':'Completed one-in-five reputation and stakes are audited for existing exclusions; one-in-fifty first-repeat and color/mechanism need separate source-specific treatment.',
 'state_persistence':'Completed Framework F raw/adjusted persistence is audited; later threshold-1 transitions and speed-adjusted regressions still require their exact producer.',
 'temporal_dynamics':'B1 randomization, B2/C-series dynamics and incident-adjusted temporal concentration require full source-specific reruns.',
 'paper_reconciliation':'Every retained manuscript/supplement table and figure must map to a completed author-excluded result; remove obsolete retention notes after review.'}

def package(run,destination,percent):
    destination.mkdir(parents=True,exist_ok=True);name=f'AUTHOR_EXCLUSION_REPORT_{run.name}_{percent:03d}.zip';p=destination/name;t=p.with_suffix('.zip.partial')
    manifest=[dict(file=str(f.relative_to(run/'report')),sha256=sha(f),bytes=f.stat().st_size) for f in sorted((run/'report').rglob('*')) if f.is_file() and f.name!='REPORT_HASHES.json']
    write(run/'report/REPORT_HASHES.json',manifest)
    with zipfile.ZipFile(t,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted((run/'report').rglob('*')):
            if f.is_file():z.write(f,'report/'+str(f.relative_to(run/'report')))
    os.replace(t,p);p.with_suffix('.zip.sha256').write_text(sha(p)+'  '+name+'\n');log(f'CHECKPOINT {percent}% of this package: {p}');return p

def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    if not p.exists():return
    for line in p.read_text().splitlines():
        h,name=line.split('  ',1);f=(ROOT/name).resolve()
        require(f.is_relative_to(ROOT) and f.is_file() and sha(f)==h,'Package checksum failed: '+name)

def preflight(args):
    require(sys.version_info>=(3,10),'Python >=3.10 required')
    require(args.project.is_dir(),'Project volume unavailable: '+str(args.project))
    require(1<=args.workers<=10 and 4<=args.memory_gb<=32,'Use 1..10 workers, memory >=4 GiB')
    require(args.shards>=32,'Use >=32 chooser partitions')
    import scipy,matplotlib,zstandard,chess
    module('dependency_authority',ROOT/'vendor/wave1/runner/common.py').verify_runtime_dependencies()
    versions=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,matplotlib=matplotlib.__version__,zstandard=zstandard.__version__,chess=chess.__version__)
    require(shutil.disk_usage(args.project).free>=40*2**30,'At least 40 GiB free working space required; actual paired-run needs depend on existing caches')
    return versions

def coverage(run,statuses):
    rows=[{'family':s,'description':LABELS[s],'included':statuses.get('included/'+s,{}).get('status','NOT_RUN'),'excluded':statuses.get('excluded/'+s,{}).get('status','NOT_RUN')} for s in STAGES]
    rows += [dict(family=k,description=v,included='NOT_IN_THIS_RUNNER',excluded='REQUIRES_ADAPTER_OR_AUDIT') for k,v in OPEN_FAMILIES.items()]
    for family in ('reputation','stakes','iv_current','framework','mechanism'):
        p=run/'report/current_audits'/(family+'.json')
        refitted=family=='mechanism' and statuses.get('excluded/mechanism',{}).get('status')=='COMPLETE'
        rows.append(dict(family='audit_'+family,description='Regular equal/losing models and RD110 sensitivity refitted' if refitted else 'Verification of existing completed author-excluded results',included='PINNED_PRIOR_BASELINE' if refitted else 'NO_NEW_COUNTERFACTUAL',excluded=read(p)['status'] if p.exists() else 'NOT_AUDITED'))
    table(run/'report/analysis_coverage',rows)
    write(run/'report/CLAIM_STATUS.json',{'all_analyses_excluded':False,'no_substantive_difference_established':False,'reason':'Paper-wide coverage remains incomplete. See analysis_coverage.csv; do not publish a blanket exclusion or invariance statement from this packet alone.'})

def current_audits(args,run):
    statuses={}
    for family in ('reputation','stakes','iv_current','framework','mechanism','local_inventory'):
        path=run/'report/current_audits'/(family+'.json');path.unlink(missing_ok=True)
        cmd=[sys.executable,str(ROOT/'code/audit_current.py'),'--family',family,'--project',str(args.project),'--run',str(run),'--workers',str(args.workers),'--memory-gb',str(args.memory_gb)]
        log('Begin current-result audit: '+family+'; expected 5–30 minutes for a data audit, under 2 minutes for the source inventory')
        logfile=run/'PRIVATE/logs'/('audit_'+family+'.log');logfile.parent.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        with logfile.open('w') as f:
            child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            with heartbeat('Current-result audit '+family):
                for line in child.stdout:print(line,end='',flush=True);f.write(line);f.flush()
            rc=child.wait()
        statuses[family]={'status':read(path)['status'] if rc==0 and path.exists() else 'BLOCKED','seconds':time.monotonic()-started}
        if rc:log('Audit blocked; retained for review: '+family)
    write(run/'report/CURRENT_AUDITS.json',statuses)
    return statuses

if __name__=='__main__':
    raise SystemExit('Use RUN_AUTHOR_EXCLUSION.command or code/continuation.py; this package only continues the reviewed v100 run.')
