from remaining_common import *
import argparse

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',required=True);p.add_argument('--variant',choices=['included','excluded'],required=True)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();a.parent=parent_root(a.project);a.auths={v:read(a.run/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in ('included','excluded')}
    auth=a.auths[a.variant];out=a.run/'PRIVATE/results'/a.variant/a.stage
    for sub in ('PRIVATE','report'):(out/sub).mkdir(parents=True,exist_ok=True)
    modules={'state_persistence':'state_persistence','responsibility':'responsibility_remaining','patron_remaining':'patron_remaining','first_repeat':'first_repeat_remaining','c6':'c6_remaining','temporal':'temporal_remaining','tenure':'tenure_remaining','arena':'arena_remaining'}
    m=__import__(modules[a.stage]);result=m.run_stage(a,auth,out)
    receipt=dict(stage=a.stage,variant=a.variant,sample_fingerprint=auth['fingerprint'],result=result,code_sha256=sha(m.__file__))
    write(a.run/'PRIVATE/stage_receipts'/a.variant/(a.stage+'.json'),receipt)

if __name__=='__main__':main()
