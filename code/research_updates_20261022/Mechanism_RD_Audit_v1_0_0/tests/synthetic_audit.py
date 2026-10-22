"""Full primary-state audit on generated rows; no production data or estimates.

Run manually. The launcher runs only the short test_audit.py suite.
"""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[k]='1'
import sys,tempfile,time,shutil,zipfile
from fixture import *
from model_utils import fit_one,FOLDS
from analysis import evaluate
from design import MODELS
import run

def main():
    start=time.monotonic()
    # Keep the generated directory for local figure inspection only if requested.
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp);project=base/'project';desktop=base/'desktop'
        source=project/'derived/replication/mechanism_separation_v100_PRIVATE';source.mkdir(parents=True)
        d=fixture(90);eligible=d[d.regular].copy()
        reference=dict(source_package_sha256='synthetic-source-package',source_result_sha256='synthetic-result',
                       states={'equal':dict(n=len(eligible),grants=int(eligible.y.sum()),accounts=eligible.chooser.nunique(),
                                            full_fits={},heldout_scores=[])})
        write(source/'RUN_IDENTITY.json',dict(package_sha256='synthetic-source-package'))
        for month,x in d.groupby('month'):
            p=source/'analysis'/(month+'.parquet');frame(x,p);done(p,'synthetic-source')
        for model in MODELS:
            log('Synthetic original fit: '+model)
            for fold in (None,0,1):
                train=eligible if fold is None else eligible[eligible.month.le(FOLDS[fold][0])]
                f=fit_one(train,model,inference=fold is None)
                assert f['status']=='ESTIMATED',(model,fold,f['status'],f.get('gradient_max'))
                suffix='' if fold is None else f'_fold{fold}'
                write(source/'models'/('regular_equal_'+model+suffix+'.json'),dict(key='synthetic',fit=f))
                if fold is None:
                    reference['states']['equal']['full_fits'][model]={k:f[k] for k in ('names','beta','n','grants','accounts')}
                else:
                    test=eligible[eligible.month.between(FOLDS[fold][1],FOLDS[fold][2])]
                    scores,_=evaluate(informative(test),f,metadata(test),fold=fold)
                    assert sum(r['informative_groups'] for r in scores)>0
                    assert sum(r['loglik'] for r in scores)<0
                    reference['states']['equal']['heldout_scores']+=scores
        before={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
        testroot=base/'synthetic_package';testroot.mkdir()
        write(testroot/'authority/reference.json',reference)
        for name in ('METHODS.md','FROZEN_PLAN.json'):shutil.copy2(ROOT/name,testroot/name)
        # Only the pinned external authority and package hash are replaced for this
        # generated fixture. The production preparation, model workers, comparison,
        # reporting, archival and restart paths all run unchanged.
        run.ROOT=testroot;run.STATES=('equal',);run.verify_package=lambda:'synthetic-audit-package'
        sys.argv=['run.py','--project-root',str(project),'--desktop',str(desktop),
                  '--workers','2','--fit-workers','2','--memory-gb','2']
        run.main()
        work=project/'derived/replication/mechanism_rd_audit_v100_PRIVATE';report=work/'public_results'
        status=read(report/'SUMMARY.json');assert status['status']=='RD_AUDIT_COMPLETE',status
        scores=pd.read_parquet(report/'heldout_scores.parquet')
        assert len(scores)==7*12*3
        assert scores.informative_groups.min()>0 and (scores.loglik<0).all()
        comparisons=read(report/'MODEL_COMPARISON_STATUS.json')
        assert len(comparisons)==3 and all(r['status']=='COMPARED' for r in comparisons)
        diag=pd.read_parquet(report/'conditional_score_diagnostics.parquet')
        assert set(diag.RD_class)=={'both_le110','own_only_gt110','opponent_only_gt110','both_gt110'}
        fitstamps={str(p):p.stat().st_mtime_ns for folder in ('fits','unrestricted') for p in (work/folder).glob('*.json')}
        run.main()
        assert fitstamps=={p:Path(p).stat().st_mtime_ns for p in fitstamps},'Completed fits reran'
        after={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
        assert before==after,'Source cache changed'
        archives=list(desktop.glob('MECHANISM_RD_AUDIT_RESULT_*.zip'));assert len(archives)==2
        for p in archives:
            assert Path(str(p)+'.sha256').read_text().split()[0]==sha(p)
            with zipfile.ZipFile(p) as z:
                assert z.testzip() is None
                assert not any('prepared/' in n or 'analysis/' in n for n in z.namelist())
                for name in z.namelist():
                    if name.endswith('_fit.json'):assert b'"switcher_ids"' not in z.read(name)
        destination=os.environ.get('RD_AUDIT_SYNTHETIC_FIGURES')
        if destination:
            Path(destination).mkdir(parents=True,exist_ok=True)
            for p in report.glob('Figure_*.png'):shutil.copy2(p,Path(destination)/p.name)
        print('SYNTHETIC_AUDIT_OK',dict(rows=len(d),eligible=len(eligible),models=7,
            validation_model_month_cells=len(scores),source_unchanged=True,restart_reused=True,
            elapsed_seconds=round(time.monotonic()-start,2)),flush=True)

if __name__=='__main__':main()
