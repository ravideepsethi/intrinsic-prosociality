"""Unchanged A2 mathematics, isolated from other legacy module names.

Only MATE_LABELS and prepare_targets are loaded from features.py: its other
functions acquire/parse chess-engine output, which this cached-only run never uses.
"""
from util import *
import ast,importlib.util,sys,types
from functools import lru_cache

ALIASES=('common','a1_design','features','design','estimate')

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def extract(path,names,namespace):
    tree=ast.parse(Path(path).read_text(),filename=str(path));nodes=[]
    for node in tree.body:
        ids=[node.name] if isinstance(node,(ast.FunctionDef,ast.ClassDef)) else [t.id for t in node.targets if isinstance(t,ast.Name)] if isinstance(node,ast.Assign) else []
        if set(ids)&set(names):nodes.append(node)
    require(len(nodes)==len(names),'Frozen producer functions/constants missing')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)

@lru_cache(maxsize=1)
def producers():
    folder=ROOT/'vendor/a2';saved={n:sys.modules.get(n) for n in ALIASES}
    try:
        common=load(folder/'common.py','mm_a2_common');sys.modules['common']=common
        a1=load(folder/'a1_design.py','mm_a2_a1');sys.modules['a1_design']=a1
        features=types.ModuleType('mm_a2_features');features.__dict__.update(common.__dict__)
        extract(folder/'features.py',['MATE_LABELS','prepare_targets'],features.__dict__)
        sys.modules['features']=features
        design=load(folder/'design.py','mm_a2_design');sys.modules['design']=design
        estimate=load(folder/'estimate.py','mm_a2_estimate');sys.modules['estimate']=estimate
        report=load(folder/'report.py','mm_a2_report')
        helpers=dict(common.__dict__);extract(folder/'analysis_runner.py',['coverage'],helpers)
        return dict(common=common,a1_design=a1,features=features,design=design,estimate=estimate,report=report,coverage=helpers['coverage'])
    finally:
        for name,m in saved.items():
            if m is None:sys.modules.pop(name,None)
            else:sys.modules[name]=m

def prepare_targets(path):
    p=producers();old=sys.modules.get('a1_design');sys.modules['a1_design']=p['a1_design']
    try:return p['features'].prepare_targets(path)
    finally:
        if old is None:sys.modules.pop('a1_design',None)
        else:sys.modules['a1_design']=old
