"""Load frozen producers under private names, avoiding legacy module collisions."""
from util import *
import importlib.util,sys
from functools import lru_cache

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@lru_cache(maxsize=1)
def producers():
    saved={n:sys.modules.get(n) for n in ('common','design')}
    try:
        common=load(ROOT/'vendor/r11/common.py','structure_legacy_common')
        sys.modules['common']=common
        r11=load(ROOT/'vendor/r11/design.py','structure_r11_design');sys.modules['design']=r11
        engine=load(ROOT/'vendor/r11/estimate.py','structure_r11_engine')
        prepare=load(ROOT/'vendor/r11/prepare.py','structure_r11_prepare')
        r10=load(ROOT/'vendor/r10/design.py','structure_r10_design')
        equal=load(ROOT/'vendor/equal/statistics.py','structure_equal_statistics')
        return r11,r10,engine,prepare,equal
    finally:
        for n,m in saved.items():
            if m is None:sys.modules.pop(n,None)
            else:sys.modules[n]=m

def designs(frame):
    """Use the two original matrices verbatim; only the stated clock extension is new."""
    import numpy as np
    r11,r10,_,_,_=producers()
    x,n,ix=r11.design(frame);main=x[:,ix['column1']];main_names=[n[j] for j in ix['column1']]
    competitive=(frame.position.to_numpy()>=2).astype(float)
    clock_names=['log1p_clock_c:competitive','log1p_clock_d:competitive']
    clock=np.column_stack([main]+[main[:,main_names.index(n)]*competitive for n in ('log1p_clock_c','log1p_clock_d')])
    del x
    x,n,ix=r10.design(frame);speed=x[:,ix['column4']];speed_names=[n[j] for j in ix['column4']]
    return {'clock_pooled':(main,main_names),'clock_region':(clock,main_names+clock_names),'stage_speed':(speed,speed_names)}

def union_design(frame):
    import numpy as np
    matrices=designs(frame);names=[];columns=[];indices={}
    for model,(x,labels) in matrices.items():
        chosen=[]
        for j,label in enumerate(labels):
            if label not in names:names.append(label);columns.append(x[:,j])
            chosen.append(names.index(label))
        indices[model]=chosen
    return np.column_stack(columns),names,indices
