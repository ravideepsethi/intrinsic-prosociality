"""Index-scale scaling and authenticated historical-cue comparisons."""
from common import *
from design import controls,gap_basis
from stats import fit_conditional
from models import compare,pairwise

def index_scaling(d,report,label):
    z,zn=controls(d);gb=gap_basis(d.g);K=2*d.ki.to_numpy();star=float(np.median(K))
    X=np.column_stack([d.ki,d.kj,gb,gb*((K-star)/star)[:,None],z])
    names=['own_premium','opponent_stake']+[f'gap_{j}' for j in range(6)]+[f'gap_K_{j}' for j in range(6)]+zn
    f=fit_conditional(X,d.y.to_numpy(float),d.chooser.to_numpy(),inference=True)
    rows=[]
    if f['status']=='ESTIMATED':
        for k in np.quantile(K,[.1,.5,.9]):
            cs={}
            for name,gap in [('L',-100),('S',100)]:
                a=gap_basis([gap])[0];c=np.zeros(X.shape[1]);c[2:8]=a;c[8:14]=a*(k-star)/star;cs[name]=c
            cs['G']=cs['S']-cs['L']
            for name,c in cs.items():
                ix=abs(c)>1e-12;ok=f['identified'][ix].all()
                v=c[ix]@f['cov'][np.ix_(ix,ix)]@c[ix] if ok else np.nan
                se=np.sqrt(max(0,v)) if np.isfinite(v) else np.nan
                rows.append(dict(sample=label,K=k,K_center=star,contrast=name,index_effect=c@f['beta'] if ok else np.nan,
                    se=se,lo=c@f['beta']-1.96*se,hi=c@f['beta']+1.96*se,identified=bool(ok),
                    meaning='Conditional gap term at supported K, adjusted for own and opponent premium; no mechanism name assigned'))
    write(Path(report)/(label+'_index_scaling_status.json'),{k:v for k,v in f.items() if k not in ('beta','cov','switcher_ids')})
    table(rows,Path(report)/(label+'_index_scaling.parquet'))

def cue_data(project,work,d,report,explicit=None):
    path=Path(explicit) if explicit else Path(project)/'derived/replication/mechanism_cues_v100/manifest.json'
    if not path.exists():
        write(Path(report)/'CUE_AVAILABILITY.json',dict(status='HISTORICAL_CUES_NOT_AUTHENTICATED',
          expected_manifest=str(path),provisional='Observed game-time flag not present in certified 157-column panel',
          title='Game-time title provenance not established',patron='August 2026 snapshot is not historical exposure',
          action='Existing sources can be linked through the included cue-input contract. No current snapshot backfill or new collection was performed.'))
        return None,None
    m=read(path)
    for k,v in dict(format='MECHANISM_GAME_TIME_CUES_V1',key='game_id',role='disconnected_opponent',unknown_is_false=False).items():
        if m.get(k)!=v:raise RuntimeError('Cue contract mismatch: '+k)
    if not m.get('producer_receipt'):raise RuntimeError('Cue producer provenance required')
    r=m['producer_receipt'];rp=Path(r['path']);rp=rp if rp.is_absolute() else path.parent/rp
    auth(rp,work,r['sha256']);parts=[]
    for r in m['files']:
        p=Path(r['path']);p=p if p.is_absolute() else path.parent/p
        auth(p,work,r['sha256'],r['rows']);parts.append(p)
    c=connect(Path(work)/'tmp/cues',2,1536)
    try:
        c.register('base_keys',d[['game_id']]);cues=c.execute(f'SELECT h.* FROM {scan(parts)} h SEMI JOIN base_keys b USING(game_id)').fetchdf()
    finally:c.close()
    if cues.game_id.duplicated().any():raise RuntimeError('Duplicate game-time cue keys')
    for cue in ('provisional','title','patron'):
        if cue in cues and not cues[cue].dropna().isin([0,1]).all():raise RuntimeError('Cue must be 0/1/null: '+cue)
        if cue in cues and not m.get('semantics',{}).get(cue,{}).get('historical_at_game'):
            raise RuntimeError('Nonhistorical cue rejected: '+cue)
    joined=d.merge(cues,on='game_id',how='left',validate='one_to_one')
    write(Path(report)/'CUE_AVAILABILITY.json',dict(status='GAME_TIME_INPUTS_LOADED',manifest_sha256=sha(path),
          matched_rows=len(cues),primary_rows=len(d),semantics=m['semantics']))
    return joined,m

def run_cues(d,manifest,work,report):
    for cue in ('provisional','title','patron'):
        if cue not in d:continue
        sample=d[d[cue].notna()].copy();by=sample.groupby(cue).agg(n=('y','size'),grants=('y','sum'),choosers=('chooser','nunique'))
        table(by.reset_index(),Path(report)/('cue_'+cue+'_support.parquet'))
        if len(by)!=2 or by.n.min()<1000 or by.grants.min()<30:
            write(Path(report)/('cue_'+cue+'_status.json'),dict(status='INSUFFICIENT_COMMON_CUE_SUPPORT'));continue
        _,base=compare(sample,Path(work)/'cue_models',report,'cue_'+cue+'_matched_base',inference=False)
        _,aug=compare(sample,Path(work)/'cue_models',report,'cue_'+cue+'_augmented',inference=False,cue=cue)
        a=pd.DataFrame(base);b=pd.DataFrame(aug)
        j=a.merge(b,on=['model','month','fold'],suffixes=('_base','_cue'))
        j['score_gain']=j.loglik_cue-j.loglik_base
        table(j,Path(report)/('cue_'+cue+'_incremental_prediction.parquet'))
        if cue=='provisional':
            loc=sample[sample.opp_rd.between(90,130)].copy()
            mismatch=float((loc.provisional.astype(bool)!=(loc.opp_rd>110)).mean()) if len(loc) else None
            sem=manifest['semantics']['provisional']
            ready=bool(sem.get('historical_threshold_rd')==110 and sem.get('no_other_cutoff_rule_source')
                and sem.get('rd_threshold_calibration_reviewed') is True and len(loc)>1000 and mismatch==0)
            write(Path(report)/'provisional_threshold_status.json',dict(status='LOCAL_TEST_ELIGIBLE' if ready else 'LOCAL_THRESHOLD_NOT_VALIDATED',
               n=len(loc),flag_reconstruction_mismatch_share=mismatch,
               meaning='A reconstructed threshold is not automatically the historically displayed flag'))
            if ready:
                z,zn=controls(loc);gb=gap_basis(loc.g);flag=loc.provisional.to_numpy(float);rd=(loc.opp_rd.to_numpy()-110)/20
                X=np.column_stack([loc.ki,loc.kj,loc.rg,np.maximum(-loc.rg,0),gb,rd,rd*flag,flag,gb*flag[:,None],z])
                f=fit_conditional(X,loc.y.to_numpy(float),loc.chooser.to_numpy(),inference=True)
                write(Path(report)/'provisional_threshold_fit.json',{k:v for k,v in f.items() if k!='switcher_ids'})
