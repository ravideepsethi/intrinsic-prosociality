"""Apply the source overlay once and prepare exposure and query spines."""
import shutil
from common import *
from contracts import snap
import logic

NORMALIZED='''o.game_id,o.month,o.chooser_user_id,o.disconnected_user_id,o.utc_ms,o.anchor_ms,o.archive_ordinal,
    lower(o.color) color,lower(o.speed) speed,o.rating chooser_rating,o.opp_rating recipient_rating,o.cp,o.ply,
    o.grant::BOOLEAN kind_draw,(o.grant=1 OR o.timeout_chooser_win) arm_eligible,o.cp>=-100 fair_competitive,
    o.tournament_like_event,o.tc_base_s,o.tc_inc_s,NULL::DOUBLE chooser_rd,NULL::DOUBLE recipient_rd,
    FALSE authenticated_rating_states_attached'''

def month_job(job):
    m=job['month'];inp=job['inputs'];key=digest(dict(code=job['code'],month=m,inputs=inp))
    def build(tmp):
        c=connection(tmp/'spill',job['threads'],job['memory_mb'])
        try:
            base=scan(job['choice']);c.execute('CREATE VIEW b AS SELECT * FROM '+base)
            if job.get('membership'):
                c.execute('CREATE VIEW m0 AS SELECT * FROM '+scan(job['membership']))
                c.execute('CREATE VIEW o AS SELECT * FROM '+scan(job['opportunity']))
                if job.get('delta'):
                    c.execute('CREATE VIEW d AS SELECT * FROM '+scan(job['delta']))
                    if c.execute("SELECT count(*) FROM m0 JOIN d USING(game_id,month) WHERE m0.source_status<>'missing' OR m0.source IS NOT NULL").fetchone()[0]:
                        raise RuntimeError('Overlay would replace previously known membership')
                    n,nd=c.execute('SELECT count(*),count(DISTINCT game_id) FROM d').fetchone()
                    if n!=nd or c.execute('SELECT count(*) FROM d ANTI JOIN m0 USING(game_id,month)').fetchone()[0]:raise RuntimeError('Invalid source delta keys')
                    c.execute('CREATE VIEW m AS SELECT m0.* FROM m0 ANTI JOIN d USING(game_id,month) UNION ALL BY NAME SELECT * FROM d')
                else:c.execute('CREATE VIEW m AS SELECT * FROM m0')
                if c.execute('SELECT count(*)-count(DISTINCT game_id) FROM m').fetchone()[0]:raise RuntimeError('Duplicate merged membership')
                copy(c,'SELECT '+NORMALIZED+' FROM o JOIN m USING(game_id,month) WHERE pool_nonadjacent_eligible',tmp/'choices_PRIVATE.parquet')
                copy(c,'SELECT '+NORMALIZED+' FROM o JOIN m USING(game_id,month) WHERE pool_nonadjacent_eligible IS NULL',tmp/'unknown_choices_PRIVATE.parquet')
                # All already-known choices, including February\'s 987, are preserved.
                if c.execute('SELECT count(*) FROM b ANTI JOIN '+scan(tmp/'choices_PRIVATE.parquet')+' USING(game_id)').fetchone()[0]:
                    raise RuntimeError('Previously known main choices disappeared')
                counts=c.execute('SELECT count(*),count(*) FILTER(WHERE pool_nonadjacent_eligible),count(*) FILTER(WHERE pool_nonadjacent_eligible IS FALSE),count(*) FILTER(WHERE pool_nonadjacent_eligible IS NULL) FROM m').fetchone()
                main=scan(tmp/'choices_PRIVATE.parquet');unknown=scan(tmp/'unknown_choices_PRIVATE.parquet')
            else:
                # Retain original bytes rather than copy 24 months of identical rows.
                main=base;unknown='(SELECT * FROM b WHERE FALSE)';counts=(None,pq.ParquetFile(job['choice']).metadata.num_rows,None,0)
            choices=f'''SELECT game_id gid,chooser_user_id::BIGINT j,disconnected_user_id::BIGINT i,
                anchor_ms::BIGINT t,utc_ms::BIGINT AS "start",archive_ordinal::BIGINT ord,kind_draw::BOOLEAN y,
                lower(color) color,TRUE known,(chooser_user_id%16)::INTEGER bucket FROM {main} WHERE fair_competitive
                UNION ALL SELECT game_id,chooser_user_id::BIGINT,disconnected_user_id::BIGINT,
                anchor_ms::BIGINT,utc_ms::BIGINT,archive_ordinal::BIGINT,kind_draw::BOOLEAN,lower(color),FALSE,
                (chooser_user_id%16)::INTEGER FROM {unknown} WHERE fair_competitive'''
            c.execute('COPY ('+choices+') TO '+lit(tmp/'outcomes')+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
            return dict(month=m,all_source_rows=counts[0],main_rows=counts[1],excluded_rows=counts[2],unknown_rows=counts[3],
                original_choice_path=job['choice'] if not job.get('membership') else None)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,d=stage(Path(job['work'])/'months'/m/key,key,inp,build,job['auth'])
    return dict(root=str(root),result=d['result'])

def prepare(inputs,products,root,code,threads,memory_mb,auth,expected_main_rows=55467033):
    pp=[Path(p['root'])/'choices_PRIVATE.parquet' if p['result']['original_choice_path'] is None else Path(p['result']['original_choice_path']) for p in products]
    snaps=[snap(Path(p['root'])/'_DONE.json') for p in products]+[r for r in inputs['snapshots'] if str(r['path']) in inputs['scores']]
    key=digest(dict(code=code,inputs=snaps,account_policy=inputs['account_policy'],expected_main_rows=expected_main_rows))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            c.execute('CREATE VIEW main AS SELECT * FROM '+scan(pp))
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM main').fetchone()
            if n!=expected_main_rows or n!=u:raise RuntimeError('Known-main opportunity count or uniqueness changed')
            bad=c.execute('''SELECT count(*) FROM main WHERE fair_competitive AND NOT tournament_like_event AND
                (chooser_user_id IS NULL OR disconnected_user_id IS NULL OR chooser_user_id<0 OR disconnected_user_id<0
                OR chooser_user_id>=4294967296 OR disconnected_user_id>=4294967296 OR chooser_user_id=disconnected_user_id
                OR anchor_ms IS NULL OR utc_ms IS NULL OR anchor_ms<utc_ms OR kind_draw IS NULL OR arm_eligible IS NULL
                OR archive_ordinal IS NULL OR color NOT IN ('white','black'))''').fetchone()[0]
            if bad:raise RuntimeError('Invalid timing, identities or choice labels')
            # First-recipient ranking precedes the grant/claim and real-time cuts.
            q='''WITH e AS (SELECT game_id,month,disconnected_user_id::BIGINT recipient_id,chooser_user_id::BIGINT opponent_id,
                utc_ms::BIGINT archive_start_ms,anchor_ms::BIGINT anchor_ms,archive_ordinal::BIGINT archive_ordinal,
                kind_draw received,arm_eligible,lower(speed) speed,lower(color) index_chooser_color,
                tc_base_s,tc_inc_s,recipient_rating,chooser_rating opponent_rating,recipient_rd,chooser_rd opponent_rd,
                authenticated_rating_states_attached,cp,ply FROM main WHERE fair_competitive AND NOT tournament_like_event),
                r AS (SELECT *,row_number() OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,archive_ordinal,game_id)=1 first_recipient,
                row_number() OVER(ORDER BY recipient_id,archive_start_ms,archive_ordinal,game_id)-1 row_id FROM e)
                SELECT *,least(recipient_id,opponent_id)::UBIGINT*4294967296+greatest(recipient_id,opponent_id)::UBIGINT pair_key
                FROM r WHERE arm_eligible AND tc_base_s>0 AND speed IN ('ultrabullet','bullet','blitz','rapid','classical')'''
            copy(c,q,tmp/'candidates_PRIVATE.parquet');c.execute('CREATE VIEW q AS SELECT * FROM '+scan(tmp/'candidates_PRIVATE.parquet'))
            c.execute('CREATE VIEW s AS SELECT * FROM '+scan(inputs['scores']))
            bad=c.execute('''SELECT count(*) FROM q LEFT JOIN s USING(game_id) WHERE s.game_id IS NULL
                OR q.recipient_id IS DISTINCT FROM s.recipient_id OR q.opponent_id IS DISTINCT FROM s.chooser_user_id
                OR q.archive_start_ms IS DISTINCT FROM s.archive_start_ms OR q.anchor_ms IS DISTINCT FROM s.anchor_ms
                OR q.archive_ordinal IS DISTINCT FROM s.archive_ordinal OR q.month IS DISTINCT FROM s.month''').fetchone()[0]
            if bad:raise RuntimeError('An exposure is missing or inconsistent with its precomputed score')
            fields=','.join('s.'+n+'_'+str(lag)+'d' for lag in (7,30) for n in ('n','raw','adjusted','expected','counterparts','pair_removed'))
            n=copy(c,'SELECT q.*,'+fields+',row_number() OVER(ORDER BY q.row_id)-1 volume_row FROM q JOIN s USING(game_id) ORDER BY q.row_id',tmp/'targets_PRIVATE.parquet')
            if n!=pq.ParquetFile(tmp/'candidates_PRIVATE.parquet').metadata.num_rows:raise RuntimeError('Score join multiplied rows')
            (tmp/'candidates_PRIVATE.parquet').unlink()
            t=c.execute('SELECT recipient_id,archive_start_ms FROM '+scan(tmp/'targets_PRIVATE.parquet')+' ORDER BY row_id').to_arrow_table()
            keys,order,people=logic.volume_plan(arr(t,'recipient_id'),arr(t,'archive_start_ms'))
            for name,a in [('keys',keys),('order',order),('people',people)]:np.save(tmp/('volume_'+name+'.npy'),a,allow_pickle=False)
            del t,keys,order,people
            keys=arr(c.execute('SELECT DISTINCT pair_key FROM '+scan(tmp/'targets_PRIVATE.parquet')+' ORDER BY pair_key').to_arrow_table(),'pair_key').astype(np.uint64)
            np.save(tmp/'pair_keys.npy',keys,allow_pickle=False)
            if inputs['old_cache']:
                old=np.load(inputs['old_cache']['keys'],mmap_mode='r',allow_pickle=False)
                if np.any(old[1:]<=old[:-1]):raise RuntimeError('Old pair keys are not unique and sorted')
                unknown=keys[logic.num.lookup(old,keys)<0]
            else:unknown=keys
            np.save(tmp/'new_pair_keys.npy',unknown,allow_pickle=False)
            write_json(tmp/'query_metadata.json',dict(rows=n,pairs=len(keys),pairs_outside_old_cache=len(unknown),
                minimum_start=int(c.execute('SELECT min(archive_start_ms) FROM '+scan(tmp/'targets_PRIVATE.parquet')).fetchone()[0]),
                maximum_start=int(c.execute('SELECT max(archive_start_ms) FROM '+scan(tmp/'targets_PRIVATE.parquet')).fetchone()[0])))
            return dict(rows=n,pairs=len(keys),pairs_outside_old_cache=len(unknown),known_main_rows=expected_main_rows)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(root/'prepared'/key,key,snaps,build,auth)[0]
