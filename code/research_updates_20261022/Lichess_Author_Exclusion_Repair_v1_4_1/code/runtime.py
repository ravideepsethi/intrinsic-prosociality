"""Planning ranges, updated with this machine's paired-stage measurements."""
from engine import *

# Minutes per variant. Broad planning ranges, NOT a benchmark of this package.
# Core/reference lower bounds are informed by returned September runtime receipts.
MINUTES={'inputs':(10,45),'core':(4,15),'panel_robustness':(2,8),
 'rating_gap':(5,20),'nonparametric':(10,35),'controlled_reference':(3,10),
 'merit':(15,60),'r11':(10,40),'session':(10,45),'patron':(5,25),
 'receipt':(15,60),'activity':(1,5),'current_audit':(22,132)}

def estimate(jobs,statuses,inputs=True,audit=True):
    low,high=MINUTES['inputs'] if inputs else (0,0)
    if audit:
        a,b=MINUTES['current_audit'];low+=a;high+=b
    methods=[]
    for variant,stage in jobs:
        if statuses.get(variant+'/'+stage,{}).get('status')=='COMPLETE':continue
        other=statuses.get(('included' if variant=='excluded' else 'excluded')+'/'+stage,{})
        if stage=='session' and variant=='included':
            a,b=5,30;methods.append('reuse completed session models; authenticate/bind histories')
        elif other.get('status')=='COMPLETE' and other.get('seconds',0)>0:
            measured=other['seconds']/60;a,b=measured*.7,measured*1.6
            methods.append('paired measurement')
        else:a,b=MINUTES[stage];methods.append('provisional range')
        low+=a;high+=b
    return {'low_minutes':low,'high_minutes':high,'basis':sorted(set(methods)),
            'provisional':True,'includes_unimplemented_families':False,
            'assumptions':'Existing local caches, healthy external SSD, up to 10 workers, 11 GiB planning budget; no competing heavy job. Lower worker/memory settings can take longer.'}

def announce(jobs,statuses,run,inputs=False,audit=False):
    e=estimate(jobs,statuses,inputs,audit);now=time.time()
    e.update(estimated_finish_utc_low=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now+60*e['low_minutes'])),
             estimated_finish_utc_high=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now+60*e['high_minutes'])))
    write(run/'report/RUNTIME_ESTIMATE.json',e)
    log(f"Expected remaining runtime: {e['low_minutes']/60:.1f}–{e['high_minutes']/60:.1f} hours (provisional; updates after each stage)")
    return e
