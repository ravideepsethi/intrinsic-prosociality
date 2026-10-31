"""Authenticate and reuse the exact completed feasibility cache."""
from common import *
from design import SPEEDS

def authenticate(project, explicit=None, expected=None):
    expected=expected or read(ROOT/'authority/FEASIBILITY_STATUS.json')
    key=expected['configuration_sha256']
    root=Path(explicit) if explicit else Path(project)/'derived/replication/countdown_feasibility_v100_PRIVATE'/key[:12]
    require(root.is_dir(),'Completed feasibility cache not found: '+str(root))
    final=read(root/'PRIVATE/FINAL.json');config=read(root/'PRIVATE/CONFIG.json')
    require(final['key']==key==config['key'],'Wrong feasibility run')
    require(final['status']['status']=='COMPLETE' and final['status']['rows']==expected['rows'],'Incomplete or wrong feasibility sample')
    a=read(root/'report/input_authority.json')
    if expected.get('input_identity'):
        expected_identity=expected['input_identity']
    else:expected_identity=read(ROOT/'authority/FEASIBILITY_INPUT.json')['input_identity']
    require(a['input_identity']==config['input_identity']==expected_identity,'Wrong author-excluded input identity')
    for f in final['report_files']:verify(f)
    binding=read(root/'PRIVATE/INPUT_BINDING.json')
    require(binding['identity']==expected_identity and [r['month'] for r in binding['rows']]==MONTHS,'Invalid monthly input binding')
    files=[];counts=[]
    for r in binding['rows']:
        done=read(root/'PRIVATE/months'/r['month']/'DONE.json')
        require(done['key']==digest([key,r['month'],r['expected_sha256']]),'Wrong monthly feature definition')
        require(done['source_sha256']==r['expected_sha256'],'Monthly source identity differs')
        require(stamp(r['path'])==done['source_stamp'],'Upstream source changed since feasibility: '+r['month'])
        p=verify(done['output']);require(p.parent==(root/'PRIVATE/months'/r['month']).resolve(),'Feature checkpoint points outside expected month')
        require(pq.ParquetFile(p).metadata.num_rows==r['rows']==done['counts']['rows'],'Monthly row count differs')
        files.append(dict(**record(p),verified_stamp=stamp(p)));counts.append(done['counts']['rows'])
    require(sum(counts)==expected['rows'],'Wrong total input count')
    return dict(key=key,input_identity=expected_identity,root=str(root.resolve()),files=files,
                rows=sum(counts),input_manifest_sha256=binding['manifest_sha256'])

def prepare(binding, run, memory, threads):
    out=Path(run)/'PRIVATE/prepared';out.mkdir(parents=True,exist_ok=True)
    receipt=out/'DONE.json';key=digest([binding['key'],SPEC_KEY])
    if receipt.exists():
        saved=read(receipt);require(saved['key']==key,'Prepared cache key differs')
        for r in saved['files']:verify(r)
        return saved
    c=db(out/'spill',max(.5,min(5.,memory*.5)),min(4,threads))
    try:
        c.execute('CREATE VIEW f AS SELECT * FROM '+scan([r['path'] for r in binding['files']]))
        c.execute("CREATE VIEW selected AS SELECT * FROM f WHERE region='finite_lost' AND NOT mate AND deficit BETWEEN 0 AND 8")
        bad=c.execute("""SELECT count(*) FROM selected WHERE chooser IS NULL OR chooser<0 OR y NOT IN (0,1)
            OR NOT isfinite(cp) OR cp>=-100 OR eval10 IS DISTINCT FROM (10*floor(cp/10))::INTEGER
            OR clock_c IS NULL OR clock_d IS NULL OR clock_c<0 OR clock_d<0
            OR NOT isfinite(clock_c) OR NOT isfinite(clock_d) OR NOT isfinite(rating) OR NOT isfinite(rating_gap)
            OR rating IS NULL OR rating_gap IS NULL OR stage IS NULL""").fetchone()[0]
        require(bad==0,'Invalid model fields in cached sample')
        files=[];rows=[]
        for speed in SPEEDS:
            p=out/(speed+'.parquet')
            n=copy(c,f"""SELECT chooser,y,deficit,cp,eval10,clock_c,clock_d,rating,rating_gap,position_date,long_clock_cut,
                strftime(position_date,'%Y-%m') cal_month,
                date_diff('day',DATE '2023-11-01',position_date)::INTEGER date_code,
                CASE stage WHEN 'ply_0_10' THEN 0 WHEN 'ply_11_20' THEN 1 WHEN 'ply_21_40' THEN 2
                    WHEN 'ply_41_80' THEN 3 WHEN 'ply_81_plus' THEN 4 ELSE NULL END::TINYINT stage_code
                FROM selected WHERE speed={q(speed)} ORDER BY chooser,position_date""",p)
            files.append(dict(**record(p),speed=speed,rows=n));rows.append(dict(speed=speed,selected_rows=n))
        require(sum(r['rows'] for r in files)==c.execute('SELECT count(*) FROM selected').fetchone()[0],'Unsupported speed or lost prepared rows')
        table(Path(run)/'report/prepared_sample.csv',rows)
        saved=dict(key=key,files=files);write(receipt,saved);return saved
    finally:c.close()

SPEC_KEY='finite_lost_def0to8_numeric_by_speed_v1'
