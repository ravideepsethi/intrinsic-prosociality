"""Outcome-independent analysis choices, frozen before this run's results."""
import numpy as np

SAMPLES = {
    'all': dict(label='All competitive positions', rd=None, k=None),
    'rd75': dict(label='Both pregame RD ≤ 75', rd=75, k=None),
    'rd60': dict(label='Both pregame RD ≤ 60', rd=60, k=None),
    'rd100': dict(label='Both pregame RD ≤ 100', rd=100, k=None),
    'rd75_k11_12': dict(label='Both RD ≤ 75; 11 ≤ K ≤ 12', rd=75, k=[11,12]),
}
INTERACT_SAMPLES = ('rd75', 'rd75_k11_12')
LOCAL_SAMPLES = INTERACT_SAMPLES
BANDWIDTHS = {'gap': [25.,50.,100.], 'payoff': [.5,1.,2.], 'normalized': [.025,.05,.1]}
PRIMARY_LOCAL = ('rd75_k11_12','normalized',.05)
SUPPORT = dict(min_n=500, min_choosers=50, min_months=6)

def select(frame, sample):
    spec=SAMPLES[sample]; keep=np.ones(len(frame['y']),dtype=bool)
    if spec['rd'] is not None: keep &= (frame['crd']<=spec['rd']) & (frame['drd']<=spec['rd'])
    if spec['k'] is not None: keep &= (frame['K']>=spec['k'][0]) & (frame['K']<=spec['k'][1])
    return {k:v[keep] for k,v in frame.items()}

def add_normalized(frame):
    frame=dict(frame);frame['normalized']=frame['payoff']/frame['K'];return frame

def local_key(axis, bandwidth): return axis+'_'+format(bandwidth,'.6g').replace('.','p')

def local_definitions():
    return [(local_key(a,h),a,h) for a,hs in BANDWIDTHS.items() for h in hs]
