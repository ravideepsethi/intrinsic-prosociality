#!/usr/bin/env python3
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[key]='1'
import csv, tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import stats
from common import dump, read, certify, valid, connection, write_csv, report_zip
from estimator import fit, matrix
import run_followup

def fixture():
    rng=np.random.default_rng(78413)
    g=42; n=1260
    chooser=np.repeat(np.arange(g),n//g)
    recipient=rng.integers(0,95,n)
    recipient_group=recipient%5
    same=(chooser%5==recipient_group).astype(int)
    x=rng.normal(size=n)
    month=rng.integers(0,4,n).astype(str)
    probability=np.clip(.15+.16*same+.04*x+.03*(recipient_group==1),.01,.9)
    y=rng.binomial(1,probability)
    y[chooser<8]=0  # Never-granters must remain in the model.
    return dict(chooser=chooser,recipient=recipient,y=y,same=same,recipient_group=recipient_group.astype(str),month=month,x=x)

def dense_reference(d,cats,nums,switchers=False):
    d={k:np.asarray(v) for k,v in d.items()}
    _,groups=np.unique(d['chooser'],return_inverse=True)
    count=np.bincount(groups); sx=np.bincount(groups,weights=d['same'])
    keep=count[groups]>1
    if switchers:keep&=((sx>0)&(sx<count))[groups]
    d={k:v[keep] for k,v in d.items()}
    _,groups=np.unique(d['chooser'],return_inverse=True);g=len(np.unique(groups));n=len(groups)
    X,_,_=matrix(d,cats,nums)
    full=np.column_stack((np.eye(g)[groups],X.toarray()))
    beta=np.linalg.lstsq(full,d['y'],rcond=1e-12)[0]
    rank=np.linalg.matrix_rank(full)
    inv=np.linalg.pinv(full,rcond=1e-12)
    residual=d['y']-full@beta
    influence=inv[g]*residual
    def vc(c):
        _,codes=np.unique(c,axis=0,return_inverse=True)
        s=np.bincount(codes,weights=influence);G=len(s)
        return (s@s)*G/(G-1)*(n-1)/(n-rank)
    a=vc(d['chooser']);b=vc(d['recipient']);c=vc(np.column_stack((d['chooser'],d['recipient'])))
    return beta[g],a,b,a+b-c,rank

def main():
    checks=[]
    d=fixture();cats=['recipient_group','month'];nums=['x']
    for label,cat,num,switchers in [('full',cats,nums,False),('chooser_only',[],[],False),('switchers_only',cats,nums,True)]:
        r=fit(d,cat,num,switchers);ref=dense_reference(d,cat,num,switchers)
        assert abs(r['coefficient_pp']/100-ref[0])<1e-10
        for key,v in [('chooser',ref[1]),('recipient',ref[2]),('two_way',ref[3])]:
            assert abs(r['variance_components'][key]-v)<1e-12,(key,r,ref)
        assert r['full_model_rank']==ref[4]
        assert r['simple_within_weight_never_grant_share']>0
        checks.append(label+': coefficient, rank and three clustered variances match dense dummy-variable OLS')
    # Within-chooser-only formula provides an independent analytical reference.
    sums=[];weights=[]
    for c in np.unique(d['chooser']):
        mask=d['chooser']==c;s=d['same'][mask];y=d['y'][mask];ns=s.sum();nd=len(s)-ns
        if ns and nd:
            weights.append(ns*nd/(ns+nd));sums.append(y[s==1].mean()-y[s==0].mean())
    assert abs(fit(d,[],[])['coefficient_pp']/100-np.average(sums,weights=weights))<1e-12
    checks.append('Chooser-only coefficient matches the analytic within-chooser weighted difference')
    e={k:np.append(v,v[0]) for k,v in d.items()};e['chooser'][-1]=99999
    r=fit(e,cats,nums);assert r['dropped_singleton_rows']==1
    assert abs(r['coefficient_pp']-fit(d,cats,nums)['coefficient_pp'])<1e-10
    checks.append('Singleton exclusion preserves estimates and reports the dropped observation')
    invariant=dict(d,same=np.ones(len(d['same']),dtype=int))
    assert fit(invariant,cats,nums)['status']=='TARGET_NOT_IDENTIFIED'
    aliased=dict(d,alias=d['same'].copy())
    assert fit(aliased,cats,nums+['alias'])['status']=='TARGET_NOT_IDENTIFIED'
    checks.append('No within variation and exact control aliasing are reported as unidentified')
    bad=dict(d,x=d['x'].copy());bad['x'][0]=np.nan
    try:fit(bad,cats,nums);raise AssertionError('Accepted missing control')
    except RuntimeError:pass
    checks.append('Missing numeric controls fail explicitly')
    # Join, label and reconciliation fixtures exercise both profile roles.
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);rep=root/'first_pass_report';rep.mkdir();out=root/'out';(out/'report').mkdir(parents=True)
        db=connection('256MB',1,root/'model_spill')
        sql_data=dict(d,chooser_country=(d['chooser']%5).astype(str),recipient_country=d['recipient_group'])
        db.register('test_rows',pa.table(sql_data));db.execute('CREATE VIEW pairs AS SELECT * FROM test_rows')
        spec=dict(model='test_model',chooser_code='chooser_country',recipient_code='recipient_country',cats=cats,nums=nums,where='true',switchers_only=False)
        estimated=run_followup.estimate(db,out,spec,'integration')
        resumed=run_followup.estimate(db,out,spec,'integration')
        assert estimated==resumed
        run_followup.summarize(out,[estimated]);report_zip(out)
        assert read(out/'report/MODEL_SUMMARY.json')[0]['status']=='ESTIMATED'
        import zipfile
        with zipfile.ZipFile(out/'COUNTRY_PROFILE_FOLLOWUP_REPORT_v100.zip') as z:
            assert z.testzip() is None and all('/PRIVATE/' not in n for n in z.namelist())
        db.close()
        checks.append('SQL-to-estimator integration, model resume and public report export succeed without private records')
        prof=[dict(username='a',returned=True,disabled=False,flag_conflict=False,flag_code='US',flag_class='iso_country_or_territory',iso_code='US',parent_code='US',tos_mark=False,profile_source='august'),
              dict(username='b',returned=True,disabled=False,flag_conflict=False,flag_code='GB-ENG',flag_class='subnational_or_regional',iso_code=None,parent_code='GB',tos_mark=False,profile_source='august'),
              dict(username='c',returned=True,disabled=False,flag_conflict=False,flag_code='US',flag_class='iso_country_or_territory',iso_code='US',parent_code='US',tos_mark=True,profile_source='august'),
              dict(username='d',returned=True,disabled=False,flag_conflict=False,flag_code='AQ',flag_class='geographic_exception',iso_code=None,parent_code='AQ',tos_mark=False,profile_source='august'),
              dict(username='e',returned=True,disabled=True,flag_conflict=False,flag_code=None,flag_class='missing',iso_code=None,parent_code=None,tos_mark=None,profile_source='august')]
        profile=root/'profiles.parquet';pq.write_table(pa.Table.from_pylist(prof),profile)
        source=[]
        for i,(a,b) in enumerate([(0,2),(2,0),(0,1),(1,0),(0,3),(3,0),(0,4),(4,0)]):
            source.append(dict(chooser=a,recipient=b,chooser_name=prof[a]['username'],recipient_name=prof[b]['username'],y=i%2,state='competitive',month='2024-01'))
        panel=root/'2024-01.parquet';pq.write_table(pa.Table.from_pylist(source),panel)
        def support(kind):
            counts={}
            key={'iso':'iso_code','exact':'flag_code','parent':'parent_code'}[kind]
            same={'iso':'same_iso','exact':'same_exact_flag','parent':'same_parent_mapping'}[kind]
            diff={'iso':'different_iso','exact':'different_exact_flag','parent':'different_parent_mapping'}[kind]
            for x in source:
                a,b=prof[x['chooser']],prof[x['recipient']]
                if not a[key] or not b[key]:continue
                label=same if a[key]==b[key] else diff
                v=counts.setdefault(label,[0,0,set()]);v[0]+=1;v[1]+=x['y'];v[2].add(x['chooser'])
            return [{kind+'_pair':k,'state':'competitive','opportunities':v[0],'grants':v[1],'choosers':len(v[2])} for k,v in counts.items()]
        for kind in ['iso','exact','parent']:
            write_csv(rep/f'04_{kind}_pair_support_rates.csv',support(kind))
        original_root=run_followup.ROOT;run_followup.ROOT=root
        try:
            db=connection('256MB',1,root/'spill')
            run_followup.prepare_pairs(db,[panel],profile,out,'test')
            assert db.execute('SELECT count(*) FROM pairs').fetchone()[0]==6
            assert db.execute("SELECT count(*) FROM pairs WHERE raw_chooser_parent='AQ' AND chooser_parent IS NULL").fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM pairs WHERE recipient_mark').fetchone()[0]==1
            checks.append('Both-player joins reconcile with independently counted support; geographic exceptions remain excluded from cleaned parent mapping')
            db.close()
            db=connection('256MB',1,root/'spill')
            run_followup.prepare_pairs(db,[panel],profile,out,'test')
            db.close();checks.append('Projection resumes from a verified monthly checkpoint')
            part=out/'PRIVATE/pairs/2024-01.parquet'
            with part.open('ab') as f:f.write(b'corrupt')
            try:valid(part,'test');raise AssertionError('Accepted corrupt file')
            except RuntimeError:pass
            checks.append('Checkpoint corruption is rejected')
        finally:run_followup.ROOT=original_root
    dump(Path(__file__).parent/'TEST_REPORT.json',dict(status='PASSED',checks=checks,production_models_run=False))
    print('\n'.join(checks));print('TESTS_OK',len(checks))

if __name__=='__main__':main()
