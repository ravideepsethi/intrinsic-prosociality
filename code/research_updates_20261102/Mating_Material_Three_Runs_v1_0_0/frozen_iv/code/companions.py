"""First-stage figure, later grant kinds, and the original August badge outcome."""
from bootstrap import *
import models

def bins(a,run,conf,source,scores):
    import certified_model5 as cert
    import model_kernel as m
    src,sc=models.sample(a,run,conf,source,scores,'bins_primary','q.uniform_keep')
    def compute(tmp):
        job=m.job_for(run,conf,'bins_primary',src,sc)
        v,groups,actors,targets,meta,events=m.build_buffer(job,tmp)
        res,rank,diag=m.project(v,groups,len(targets),tmp);del v,groups;gc.collect()
        z=np.array(res[:,0]);d=np.array(res[:,1]);fit=cert.first_stage(z,d,actors)
        reference=next(r for r in read(run/'PRIVATE/models/uniform_unspaced/result.json')['estimates'] if r['term']=='first_stage')
        gate=cert.reproduction_gate(fit,reference)
        rr=[cert.bin_summary(k+1,ix,z,d,actors) for k,ix in enumerate(cert.equal_count_bins(z,actors['row_id']))]
        save(tmp/'result.json',dict(bins=rr,fit=fit,gate=gate,monotonicity=cert.monotonicity(rr)))
        del res
        for p in ('design.dat','residual.dat'):(tmp/p).unlink(missing_ok=True)
        return dict(rows=rows(src),bins=20)
    out,_=stage(run/'PRIVATE/first_stage_bins',conf,compute,[src,sc,run/'PRIVATE/models/uniform_unspaced/result.json'])
    r=read(out/'result.json');c.csv_out(run/'report/FIRST_STAGE_BINS.csv',r['bins']);save(run/'report/FIRST_STAGE_MONOTONICITY.json',r['monotonicity'])
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    for ax,rr,title in [(axes[0],r['bins'],'All bins'),(axes[1],r['bins'][:-1],'Top bin omitted')]:
        x=np.array([v['mean_score_reference_sd'] for v in rr]);y=np.array([v['mean_residual_receipt_pp'] for v in rr])
        e=np.array([v['ci_high_pp'] for v in rr])-y
        ax.errorbar(x,y,yerr=e,fmt='o',markersize=4,capsize=2,color='#205c83')
        ax.plot(x,r['fit']['slope']*x,color='#555555',linewidth=1)
        ax.set(xlabel='Residual opponent score / 0.0498',ylabel='Residual receipt (percentage points)',title=title);ax.spines[['top','right']].set_visible(False)
    fig.savefig(run/'report/fig5_iv_bins_material.pdf');fig.savefig(run/'report/fig5_iv_bins_material.png',dpi=160);plt.close(fig)

def receipt_kind(a,run,conf,auth,b,source,scores):
    import position_frames as pf,position_stats as ps
    src,sc=models.sample(a,run,conf,source,scores,'receipt_kind_primary','q.uniform_keep')
    rr=run/'receipt_kind';(rr/'report').mkdir(parents=True,exist_ok=True)
    # Frozen scientific code, corrected authenticated panel binding.
    import copy
    bound=copy.deepcopy(b);bound['bound']['binding']['source']['panels']=auth['material']['records']
    index=pf.build_index(a,rr,conf,bound)
    frame=pf.attach_outcomes(a,rr,conf,src,index,'competitive',primary=True)
    frame=pf.exposure_details(a,rr,conf,frame,index,'competitive')
    out,_=ps.fit(a,rr,conf,frame,sc,'competitive',primary=False)
    actual={r['term']:r for r in read(out/'result.json')['estimates']}
    baseline={r['term']:r for r in read(run/'PRIVATE/models/uniform_unspaced/result.json')['estimates']}
    for name,old in [('first_stage','first_stage'),('iv_grant_comp','iv_y')]:
        for value in ('coefficient','standard_error'):
            require(np.isclose(actual[name][value],baseline[old][value],rtol=2e-7,atol=2e-7),'Material receipt-kind baseline replay failed')
    ps.matched(a,rr,conf,frame,'competitive')
    save(rr/'report/MATERIAL_REPLAY.json',dict(passed=True,source_rows=rows(src),first_choice_identity_verified=True))
    publish_reports(rr,run/'report/receipt_kind')

def patron(a,run,conf,source,scores):
    # Reuse the original acquisition probabilities and August snapshot.
    # Reclassifying grants does not retroactively change who was sampled.
    sys.path.insert(0,str(ROOT/'vendor/patron/code'))
    import common5 as p,link_badge,fit_badge
    from types import SimpleNamespace
    src,sc=models.sample(a,run,conf,source,scores,'patron_primary','q.uniform_keep')
    rr=run/'patron';(rr/'report').mkdir(parents=True,exist_ok=True)
    baseline=run/'PRIVATE/models/uniform_unspaced/result.json'
    ref=next(r for r in read(baseline)['estimates'] if r['term']=='iv_y')
    require(rows(src)==ref['n'],'Patron input is not the freshly fitted primary material frame')
    p.cert.N=ref['n'];p.cert.PEOPLE=ref['recipients'];p.cert.ROW_HASH=ref['row_set_sha256']
    save(rr/'PRIVATE/BINDING.json',dict(source=str(src),scores=str(sc),baseline=str(baseline)))
    aa=SimpleNamespace(**vars(a));aa.run=rr;aa.conf=conf
    fit_badge.baseline(aa);link_badge.prepare(aa);fit_badge.primary(aa);fit_badge.sensitivities(aa)
    save(rr/'report/MATERIAL_SOURCE.json',dict(material_parent=MATERIAL,rows=ref['n'],row_set_sha256=ref['row_set_sha256'],snapshot='August 2026',original_acquisition_weights_preserved=True,api_requests=0))
    publish_reports(rr,run/'report/receipt_patron')

def publish_reports(source,destination):
    import shutil
    destination.mkdir(parents=True,exist_ok=True)
    for f in (source/'report').rglob('*'):
        if f.is_file() and 'PRIVATE' not in f.name:
            out=destination/f.relative_to(source/'report');out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
