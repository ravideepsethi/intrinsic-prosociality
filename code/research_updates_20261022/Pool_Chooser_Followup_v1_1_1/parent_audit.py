"""Authenticate and import an existing v1.0.0 run, without changing it."""
import bootstrap_path
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from io_utils import digest,json_read,json_write,csv_write,require,binding
from model import Model,predict

PKG=Path(__file__).resolve().parent


def manifest(root,name):
    root=Path(root);out={}
    require((root/name).is_file(),'Missing '+str(root/name))
    for line in (root/name).read_text().splitlines():
        h,n=line.split('  ',1);p=(root/n).resolve()
        require(p.is_relative_to(root.resolve()),'Invalid manifest path')
        require(p.is_file() and digest(p)==h,'Checksum mismatch: '+str(p));out[n]=h
    return out


def inspect_parent(root,allow_fixture=False):
    root=Path(root).resolve();private=root/'PRIVATE';design=private/'design'
    config=json_read(private/'CONFIG.json')['config']
    archived=manifest(PKG/'base','PACKAGE_MANIFEST.sha256')
    require(config['code']==archived,'Parent was not produced by the bundled v1.0.0 code')
    require(config['version']=='1.0.0','Unsupported parent version')
    is_fixture=config['sample_fingerprint']=='SYNTHETIC'
    require(not is_fixture or allow_fixture,'Synthetic parent requires --allow-fixture')
    expected=json_read(PKG/'base/authority/SAMPLE_AUTHORITY.json')['sample_fingerprint']
    require(is_fixture or config['sample_fingerprint']==expected,'Unrecognized certified sample fingerprint')
    ready=json_read(design/'READY.json')
    require(ready['identity']==binding(config),'Parent configuration and design identities differ')
    require(set(ready['files'])=={'DESIGN.json','development.npz','evaluation.npz'},'Unexpected design cache inventory')
    for n,h in ready['files'].items():require(digest(design/n)==h,'Parent cache checksum failed: '+n)
    report_hashes=manifest(root/'report','REPORT_MANIFEST.sha256')
    fits=json_read(private/'core'/'SELECTED_FITS.json')
    require(all(n in fits for n in ['level','desert','cost','both']),'Missing primary selected fits')
    require(all(r['success'] for r in fits.values()),'Unconverged selected parent model')
    # Bind the private parameter vectors to the public scores before reusing them.
    ev=dict(np.load(design/'evaluation.npz',allow_pickle=False));meta=json_read(design/'DESIGN.json')
    public=pd.read_csv(root/'report'/'scores.csv');checks=[]
    for name,r in fits.items():
        tab=public[(public.model==name)&(public.group=='all')]
        require(len(tab)==1,'Missing original score for '+name)
        score=float(predict(r,ev,meta)[1][ev['period']==2].mean())
        err=abs(score-float(tab.iloc[0].mean_log_score))
        require(err<1e-10,'Imported fit does not reproduce archived score: '+name)
        checks.append(dict(model=name,recomputed_mean_log_score=score,absolute_difference=err))
    return dict(root=str(root),config=config,ready=ready,fits=fits,
      design_sha256=ready['files'],selected_fits_sha256=digest(private/'core'/'SELECTED_FITS.json'),
      report_manifest_sha256=digest(root/'report'/'REPORT_MANIFEST.sha256'),
      synthetic=is_fixture,score_checks=checks)


def copy_checked(source,dest):
    source,dest=Path(source),Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():require(digest(source)==digest(dest),'Imported cache has changed: '+str(dest))
    else:
        tmp=dest.with_name(dest.name+'.partial');shutil.copyfile(source,tmp);tmp.replace(dest)


def import_suite(parent,private,suite):
    source=Path(parent['root'])/'PRIVATE'/'design';dest=private/'design';dest.mkdir(parents=True,exist_ok=True)
    for n in parent['ready']['files']:copy_checked(source/n,dest/n)
    json_write(dest/'FOLLOWUP.json',dict(suite=suite,parent_identity=parent['ready']['identity']))
    if suite in ['original','repair']:
        target=private/'core'/('IMPORTED_FITS.json' if suite=='repair' else 'SELECTED_FITS.json')
        if target.exists():require(json_read(target)==parent['fits'],'Original selected fit cache changed')
        else:json_write(target,parent['fits'])


def audit_boundaries(parent,report):
    root=Path(parent['root']);meta=json_read(root/'PRIVATE/design/DESIGN.json')
    rows=[];selected=[];attempt_count=0;final_count=0;final_hits=0
    for path in sorted((root/'PRIVATE/core').glob('*.json')):
        if path.name=='SELECTED_FITS.json':continue
        record=json_read(path);r=record.get('result')
        if not isinstance(r,dict) or 'parameters' not in r:continue
        attempt_count+=1
        if path.name.startswith('full_'):
            final_count+=1;final_hits+=bool(r['numerical_bounds'])
        model=Model(r['spec'],r['J'],meta,r['bound']);v=np.asarray(r['parameters']);dec=model.decode(v)
        for name in r['numerical_bounds']:
            idx=model.names.index(name);key=name.split(':')[0];k=int(name.split(':')[1])
            rows.append(dict(file=path.name,phase='full_year' if path.name.startswith('full_') else 'validation',
              model=r['spec']['name'],J=r['J'],parameter=name,raw_value=float(v[idx]),
              raw_lower=model.bounds[idx][0],raw_upper=model.bounds[idx][1],
              index_offset=dec['index_offset'],reported_theta=float(dec['theta'][k]) if key=='theta' else None,
              success=r['success']))
    for name,r in parent['fits'].items():
        model=Model(r['spec'],r['J'],meta,r['bound']);v=np.asarray(r['parameters']);d=model.decode(v)
        for k in range(r['J']):selected.append(dict(model=name,type=k,
          raw_alpha=float(model.get(v,'alpha')[k]),reported_alpha=float(d['alpha'][k]),
          raw_theta=None if d['raw_theta'] is None else float(d['raw_theta'][k]),
          reported_theta=None if d['theta'] is None else float(d['theta'][k]),index_offset=d['index_offset'],
          premium_per_rating_point=float(d['B'][k,0]/10),loss_per_rating_point=float(d['B'][k,1]/10),
          selected_numerical_bounds=';'.join(r['numerical_bounds'])))
    csv_write(report/'original_raw_boundary_flags.csv',rows)
    csv_write(report/'original_raw_and_reported_parameters.csv',selected)
    csv_write(report/'parent_score_reproduction.csv',parent['score_checks'])
    json_write(report/'BOUNDARY_AUDIT.json',dict(attempts=attempt_count,full_year_attempts=final_count,
      full_year_attempts_with_numerical_hits=final_hits,
      selected_with_numerical_hits=[n for n,r in parent['fits'].items() if r['numerical_bounds']],
      transformation='Reported theta = raw_theta * (1 - f0); reported alpha = raw_alpha + raw_theta * f0.',
      warning='Zero slopes/costs and zero loss angle are admissible economic boundaries. Numerical upper caps are different and are reported separately.'))
