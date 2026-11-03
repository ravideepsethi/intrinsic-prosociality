"""Recent traits that are not the 90-day controls in retained spaced models."""
from closeout_common import *

def run_all(a,run,conf,auth):
    import recent_kernel as m
    for label,key,level,fe in [('spaced_recent_balance','spaced','X0_ENV_indicator',False),('spaced_noenv_recent_balance','spaced','X0',False),('repeated_FE_recent_balance','repeated','X0_ENV_indicator',True)]:
        job=m.job_for(run,conf,label,auth['paths'][key],auth['paths'][key+'_scores'],legacy=True,recent_balance=True,recipient_fe=fe)
        job.update(outcomes=[],iv=False,level=level)
        with heartbeat('Balance '+label):m.fit(job)
        m.export_models(run)
    save(run/'report/RECENT_BALANCE_DEFINITION.json',dict(traits=7,window='37 to 7 days before index start',controls='Original spaced 97-to-7-day histories and preceding-30-day volume retained',Holm_family=7,within_recipient='Repeated spaced recipients only; recipient fixed effects',primary_balance='Already completed; eight 90-day traits tested with those controls omitted'))
