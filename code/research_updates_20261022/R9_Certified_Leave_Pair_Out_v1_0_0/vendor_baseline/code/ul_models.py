"""Frozen R7 numerical fits with explicit new score / common timing samples."""
from ul_common import *

def load_scored(source,scores,variant='all_time',cohort='frozen',material=None,screen='all'):
    d=r.load_fit_columns(source)
    names=['row_id','n_all_time','adjusted_all_time']
    if cohort=='timing_common':names += ['n_before','n_after','adjusted_before','adjusted_after']
    a=r.arrays(r.io.read(scores,names))
    u.require(np.array_equal(d['row_id'],a['row_id']),'Scores and model row identity/order differ')
    use=np.ones(len(d['row_id']),bool)
    if cohort=='timing_common':
        use &= (a['n_before']>=5)&(a['n_after']>=5)&np.isfinite(a['adjusted_before'])&np.isfinite(a['adjusted_after'])
    else:u.require(variant=='all_time','Timing instruments require the common timing sample')
    u.require(np.all(a['n_all_time']>=5) and np.isfinite(a['adjusted_all_time']).all(),'Unsupported unrestricted scores')
    d['adjusted_7d']=a['adjusted_'+variant]
    if screen!='all':
        u.require(material is not None and screen=='neutral','Missing or invalid material selection')
        m=r.arrays(r.io.read(material,['row_id','material_valid','material_neutral']))
        u.require(np.array_equal(d['row_id'],m['row_id']),'Material identities/order differ')
        use &= m['material_valid'].astype(bool)&m['material_neutral'].astype(bool)
    # Historical counts, expected-rate control, exposure covariates and Y stay frozen.
    return r.subset(d,use)

def fit_job(job):
    r.threads_one();u.no_network()
    deps=[job['input'],job['scores']]+([job['material']] if job.get('material') else [])
    def build(tmp):
        d=load_scored(job['input'],job['scores'],job['variant'],job['cohort'],job.get('material'),job['screen'])
        ids=d['row_id'].copy();n=len(ids)
        result,inf=models.estimate(d,job['kind'],job['sample'],job['level'],part_a=False,calibration=False,release_inputs=True)
        for table in result.values():
            for row in table:row.update(annotations(job['variant'],job['screen'],job['cohort']))
        r.io.js(tmp/'result.json',result)
        if inf is not None and job.get('influence'):
            inf['row_id']=ids
            r.io.table(tmp/'influence_PRIVATE.parquet',pa.table(inf))
        return dict(rows=n,sample=job['sample'],kind=job['kind'],control_level=job['level'],
            variant=job['variant'],screen=job['screen'],cohort=job['cohort'],influence_saved=bool(inf is not None and job.get('influence')))
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def contrast_job(job):
    r.threads_one();u.no_network()
    deps=[str(Path(folder)/name) for folder in (job['left'],job['right']) for name in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        meta=dict(annotations(),control_level=job['level'],instrument='pooled',sample='S0_minus_O50',
            units='percentage points per reference score SD',reference_score_SD=r.SD['pooled'],
            clustering='shared_account_OR_date_CR0',nominal_interim_intervals=True,
            comparison_interpretation='RF difference with shared covariance; not a corrected IV or a proof of exclusion')
        rows=models.contrast(job['left'],job['right'],meta)
        r.io.js(tmp/'result.json',rows);return dict(contrasts=len(rows))
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def make_job(source,scores,output,conf,sample,kind,level,screen='all',material=None,variant='all_time',cohort='frozen'):
    n=pq.ParquetFile(source).metadata.num_rows
    return dict(input=str(source),scores=str(scores),output=str(output),conf=conf,sample=sample,kind=kind,
        level=level,screen=screen,material=str(material) if material else None,variant=variant,cohort=cohort,
        influence=(cohort=='frozen' and screen=='all' and sample in ('S0','O50')),
        memory_gb=1.3+n*(950 if cohort=='timing_common' else 920)/1024**3)
