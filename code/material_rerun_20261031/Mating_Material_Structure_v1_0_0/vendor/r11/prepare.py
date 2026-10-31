"""Read-only certified inputs; private, chooser-complete reusable projections."""
from common import *
from design import MONTHS,SPEEDS,STAGES,POSITIONS

def project_month(t):
    src=Path(t['source']);out=Path(t['output']);begin=time.monotonic()
    key=fingerprint([t['key'],t['month'],t['expected_sha256'],stamp(src)])
    if valid(out,key):return dict(month=t['month'],reused=True,seconds=0,**load(str(out)+'.ok.json')['counts'])
    require(sha(src)==t['expected_sha256'],'Source checksum mismatch: '+t['month'])
    c=dbopen(out.parent/'spill'/t['month'],1,t['memory'])
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+parq([src]))
        bad=c.execute(f'''SELECT count(*) FROM src WHERE
          month IS DISTINCT FROM {qs(t['month'])} OR chooser_user_id IS NULL OR outcome_kind_draw IS NULL
          OR outcome_kind_draw NOT IN (0,1) OR engine_eval_cp_disconnected IS NULL OR NOT isfinite(engine_eval_cp_disconnected)
          OR engine_eval_cp_disconnected<>floor(engine_eval_cp_disconnected)
          OR ply_count IS NULL OR ply_count<0 OR ply_count<>floor(ply_count)
          OR NOT coalesce(sf100k_nodes_requested=100000,false)
          OR NOT coalesce(sf100k_fen_turn_matches_disconnected_color,false)
          OR NOT coalesce(disconnected_color=sf100k_disconnected_color_for_perspective,false)
          OR NOT coalesce(side_to_move_after_last=disconnected_color,false)
          OR NOT coalesce(api_status='timeout' AND five_second_rule_passed AND api_rated AND api_variant='standard',false)
          OR api_speed IS NULL OR api_speed NOT IN ('ultraBullet','ultrabullet','bullet','blitz','rapid','classical')''').fetchone()[0]
        require(bad==0,f'{t["month"]}: {bad} source rows violate the certified field meanings')
        speed="CASE lower(api_speed) WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 END"
        query=f'''SELECT chooser_user_id::BIGINT chooser,outcome_kind_draw::TINYINT y,
          engine_eval_cp_disconnected::DOUBLE board,ply_count::INTEGER ply,
          CASE WHEN engine_eval_cp_disconnected>=300 THEN 4 WHEN engine_eval_cp_disconnected>=101 THEN 3
            WHEN engine_eval_cp_disconnected>=-100 THEN 2 WHEN engine_eval_cp_disconnected>=-299 THEN 1 ELSE 0 END::TINYINT "position",
          CASE WHEN ply_count<=4 THEN 0 WHEN ply_count<=6 THEN 1 WHEN ply_count<=8 THEN 2 WHEN ply_count<=10 THEN 3
            WHEN ply_count<=20 THEN 4 WHEN ply_count<=40 THEN 5 WHEN ply_count<=80 THEN 6 ELSE 7 END::TINYINT stage,
          (disconnected_elo-chooser_elo)::DOUBLE gap,chooser_clock_last_obs_s::DOUBLE clock_c,
          disconnected_clock_last_obs_s::DOUBLE clock_d,chooser_win_premium_v2::DOUBLE premium,
          chooser_pre_rd_v2::DOUBLE rd_c,disconnected_pre_rd_v2::DOUBLE rd_d,
          {MONTHS.index(t['month'])}::TINYINT month_code,({speed})::TINYINT speed_code FROM src'''
        out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix('.partial.parquet')
        c.execute(f'COPY ({query}) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)')
        n,g=c.execute('SELECT count(*),sum(y)::BIGINT FROM '+parq([tmp])).fetchone()
        require(n==t['rows'],'Projection changed the row count');os.replace(tmp,out)
        counts=dict(n=n,grants=g);certify(out,key,dict(counts=counts))
        return dict(month=t['month'],seconds=time.monotonic()-begin,reused=False,**counts)
    finally:c.close()

def raw_summaries(paths,run,workers,memory):
    c=dbopen(run/'PRIVATE/spill_raw',workers,memory)
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parq(paths))
        n,g,people,competitive,kg=c.execute('SELECT count(*),sum(y)::BIGINT,count(DISTINCT chooser),count(*) FILTER(WHERE "position">=2),sum(y) FILTER(WHERE "position">=2)::BIGINT FROM p').fetchone()
        require((n,g,people,competitive,kg)==(41534331,570091,3224173,15207423,419463),'Certified full-sample census differs')
        board=c.execute('SELECT "position",stage,count(*) opportunities,sum(y)::BIGINT grants,100.*avg(y) grant_rate_pct FROM p GROUP BY ALL ORDER BY ALL').fetchdf()
        board['position']=board.position.map(dict(enumerate(POSITIONS)));board['stage']=board.stage.map(dict(enumerate(STAGES)))
        table(run/'report/board_by_stage',board)
        expected=load(ROOT/'authority/EXPECTED_BOARD_STAGE.json')
        observed={(r.position,r.stage):(int(r.opportunities),int(r.grants)) for r in board.itertuples()}
        require(observed=={(r['position'],r['stage']):(r['opportunities'],r['grants']) for r in expected},'Forty-cell Figure 2 accounting differs')
        sp=c.execute('SELECT speed_code,stage,count(*) opportunities,sum(y)::BIGINT grants FROM p GROUP BY ALL ORDER BY ALL').fetchdf()
        full=pd.MultiIndex.from_product([range(5),range(8)],names=['speed_code','stage'])
        sp=sp.set_index(['speed_code','stage']).reindex(full,fill_value=0).reset_index()
        sp['share_of_stage_pct']=100*sp.opportunities/sp.groupby('stage').opportunities.transform('sum')
        sp['grant_rate_pct']=np.where(sp.opportunities>0,100*sp.grants/sp.opportunities,np.nan)
        sp['speed']=sp.speed_code.map(dict(enumerate(SPEEDS)));sp['stage']=sp.stage.map(dict(enumerate(STAGES)))
        table(run/'report/speed_by_stage_composition',sp.drop(columns='speed_code'))
        table(run/'report/position_stage_speed_support',c.execute('SELECT "position",stage,speed_code,count(*) opportunities,sum(y)::BIGINT grants FROM p GROUP BY ALL ORDER BY ALL').fetchdf())
        missing=c.execute('''SELECT count(*) FILTER(WHERE clock_c IS NULL OR NOT isfinite(clock_c) OR clock_c<0) clock_c_invalid,
          count(*) FILTER(WHERE clock_d IS NULL OR NOT isfinite(clock_d) OR clock_d<0) clock_d_invalid,
          count(*) FILTER(WHERE premium IS NULL OR NOT isfinite(premium) OR premium<=0) premium_invalid,
          count(*) FILTER(WHERE rd_c IS NULL OR NOT isfinite(rd_c) OR rd_c<=0) rd_c_invalid,
          count(*) FILTER(WHERE rd_d IS NULL OR NOT isfinite(rd_d) OR rd_d<=0) rd_d_invalid,
          count(*) FILTER(WHERE gap IS NULL OR NOT isfinite(gap)) gap_invalid FROM p''').fetchdf()
        table(run/'report/missingness',missing)
        support=gap_support(c)
        require(sum(r['opportunities'] for r in support if r['category_kind'] in ['segment','missing'])==n,'Gap segment counts do not conserve sample')
        table(run/'report/gap_region_support',support)
        return dict(opportunities=n,grants=g,choosers=people,competitive=competitive,competitive_grants=kg,author_accounts_retained=True)
    finally:c.close()

def partition(paths,run,shards,workers,memory,key):
    root=run/'PRIVATE/by_chooser';receipt=run/'PRIVATE/PARTITIONS.json'
    if receipt.exists():
        r=load(receipt);require(r['key']==key,'Partition key changed')
        for f in r['files']:require(sha(root/f['relative'])==f['sha256'],'Partition checksum changed')
        return r
    tmp=run/'PRIVATE/by_chooser.partial'
    if tmp.exists():tmp.rename(tmp.with_name('by_chooser.interrupted.'+str(time.time_ns())))
    c=dbopen(run/'PRIVATE/spill_partition',workers,memory)
    try:c.execute(f'''COPY (SELECT *,((chooser%{shards}+{shards})%{shards})::INTEGER bucket FROM {parq(paths)}) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 122880)''')
    finally:c.close()
    files=[dict(relative=str(p.relative_to(tmp)),sha256=sha(p),rows=pq.ParquetFile(p).metadata.num_rows) for p in sorted(tmp.glob('bucket=*/*.parquet'))]
    require(sum(f['rows'] for f in files)==41534331,'Partition row conservation failed')
    tmp.rename(root);r=dict(key=key,files=files,shards=shards);dump(receipt,r);return r

def reuse_r10(root,auth,shards):
    """Read-only reuse, bound to the exact tested R10 producer and certified source hashes."""
    root=Path(root);approved=load(ROOT/'authority/R10_REUSE_AUTHORITY.json');cfg=load(root/'PRIVATE/RUN_CONFIG.json')
    oldkey=cfg['key'];require(fingerprint(cfg['configuration'])==oldkey,'R10 configuration fingerprint changed')
    require(root.name==approved['run_id']==oldkey[:12],'R10 reuse run identity differs')
    require(cfg['configuration']['code']==approved['code'],'R10 producer code differs from the authenticated version')
    require(cfg['configuration']['sample_fingerprint']==load(ROOT/'authority/SAMPLE_AUTHORITY.json')['sample_fingerprint'],'R10 source fingerprint differs')
    require(cfg['configuration']['shards']==shards,'R10 shard count differs')
    paths=[]
    for r in auth['month_records']:
        p=root/'PRIVATE/projected'/f'{r["month"]}.parquet'
        expected=fingerprint([oldkey,r['month'],r['expected_sha256'],stamp(r['path'])])
        require(valid(p,expected),'R10 projection source binding/checksum differs: '+r['month']);paths.append(p)
    receipt=load(root/'PRIVATE/PARTITIONS.json');require(receipt['key']==oldkey and receipt['shards']==shards,'R10 partition binding differs')
    bybucket={};total=0;base=(root/'PRIVATE/by_chooser').resolve()
    for f in receipt['files']:
        p=(base/f['relative']).resolve();require(p.is_relative_to(base),'R10 partition path escapes its root')
        require(sha(p)==f['sha256'],'R10 partition checksum mismatch')
        actual=pq.ParquetFile(p).metadata.num_rows;require(actual==f['rows'],'R10 partition row count differs');total+=actual
        b=int(Path(f['relative']).parts[0].split('=')[1]);require(0<=b<shards,'R10 bucket outside range');bybucket.setdefault(b,[]).append(p)
    require(total==41534331 and len(receipt['files'])==len({f['relative'] for f in receipt['files']}),'R10 partition coverage differs')
    return paths,bybucket,dict(source='verified R10 projections and chooser partitions',run_id=oldkey[:12],files=len(receipt['files']),rows=total)


def gap_support(c):
    support=[]
    segments=[('below_-300','gap < -300'),('-300_to_-100','gap >= -300 AND gap < -100'),('-100_to_0','gap >= -100 AND gap < 0'),('0_to_100','gap >= 0 AND gap < 100'),('100_to_300','gap >= 100 AND gap < 300'),('above_300','gap >= 300')]
    categories=[('segment',name,cond) for name,cond in segments]+[('tail','below_-600','gap < -600'),('tail','above_600','gap > 600'),('missing','missing','gap IS NULL OR NOT isfinite(gap)')]
    for region,condition in [('noncompetitive','"position" < 2'),('competitive','"position" >= 2')]:
        expressions=[f'count(*) FILTER(WHERE ({cond})'+(')' if kind=='missing' else ' AND isfinite(gap))') for kind,name,cond in categories]
        counts=c.execute('SELECT '+','.join(expressions)+' FROM p WHERE '+condition).fetchone()
        for (kind,name,cond),count in zip(categories,counts):support.append(dict(region=region,category_kind=kind,gap_category=name,raw_rating_gap_rule=cond,opportunities=int(count),tail_overlap='tails overlap outer segments' if kind=='tail' else ''))
    return support
