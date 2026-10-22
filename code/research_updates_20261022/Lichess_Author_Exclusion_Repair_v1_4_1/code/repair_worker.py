from engine import *
import argparse

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--parent',type=Path,required=True);p.add_argument('--project',type=Path,required=True)
    p.add_argument('--variant',choices=['included','excluded'],required=True);p.add_argument('--stage',choices=['session','nonparametric','mechanism'],required=True)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11);a=p.parse_args()
    auth=load_auth(a.run,a.variant);out=a.run/'PRIVATE/results'/a.variant/a.stage
    if a.stage=='session':
        from session_bounded import finish
        result=finish(a,auth,out,a.parent)
    elif a.stage=='nonparametric':
        from nonparametric_fixed import run
        result=run(a,auth,out,a.parent)
    else:
        from mechanism_excluded import run
        (out/'report').mkdir(parents=True,exist_ok=True);result=run(a,out,a.parent)
    guard_auth(auth)
    write(a.run/'PRIVATE/stage_receipts'/a.variant/(a.stage+'.json'),{'sample_fingerprint':auth['fingerprint'],'stage':a.stage,'variant':a.variant,'result':result})

if __name__=='__main__':main()
