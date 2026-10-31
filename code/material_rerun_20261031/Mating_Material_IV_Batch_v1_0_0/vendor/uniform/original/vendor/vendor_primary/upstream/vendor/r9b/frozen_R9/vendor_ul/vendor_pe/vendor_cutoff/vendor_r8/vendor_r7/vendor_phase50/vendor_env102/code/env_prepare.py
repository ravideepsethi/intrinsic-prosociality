from env_common import *

def entry_prepare(binding,root,conf,memory):
    entry=Path(binding['entry']);parent=Path(binding['parent'])
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            src=parent/'secondary_prepared/new_phase25.parquet'
            checked_stage_files(src.parent,binding['parent_config_sha256'],['new_phase25.parquet','scale.json'])
            q=arrays(io.read(src,['comp_adjusted_7d']))['comp_adjusted_7d']
            edges=np.quantile(q,[.2,.4,.6,.8,.95,.99]).tolist()
            frozen=io.load(ENTRY/'evidence/secondary_scale.json')['upper_5pct_raw_competitive_cutoff']
            if not np.isclose(edges[4],frozen,rtol=0,atol=1e-12):raise RuntimeError('Frozen ordinary q95 changed')
            edges[4]=frozen
            io.js(tmp/'bins.json',dict(edges=edges,probabilities=[.2,.4,.6,.8,.95,.99],source='frozen new_phase25 ordinary competitive-supported sample; no entry outcomes used',upper_bound_ties_retained=True))
            for cohort in COHORTS:
                full=parent/'split'/('entry_'+cohort+'.parquet');small=entry/'prepared'/(cohort+'.parquet')
                extra=['game_id','anchor_ms','status','matched_main','previous_frame']
                checked_columns(full,extra)
                c.execute('CREATE OR REPLACE VIEW a AS SELECT * FROM '+io.parq([full]))
                c.execute('CREATE OR REPLACE VIEW b AS SELECT * FROM '+io.parq([small]))
                n=pq.ParquetFile(small).metadata.num_rows
                if c.execute('SELECT count(*) FROM a FULL JOIN b USING(row_id) WHERE a.row_id IS NULL OR b.row_id IS NULL').fetchone()[0]:raise RuntimeError('Entry row sets differ')
                for key in ('recipient_id','opponent_id','archive_start_ms'):
                    if c.execute('SELECT count(*) FROM a JOIN b USING(row_id) WHERE a.'+key+' IS DISTINCT FROM b.'+key).fetchone()[0]:raise RuntimeError('Entry key changed: '+key)
                # Recipient role was independently verified against i/j in the pinned parent.
                invalid='recipient_disconnect_main AND NOT matched_main OR matched_main AND NOT active_timeout'
                if c.execute('SELECT count(*) FROM a WHERE '+invalid).fetchone()[0]:raise RuntimeError('Impossible recorded main-panel role')
                roles='(a.matched_main AND NOT a.recipient_disconnect_main) AS opponent_disconnect_main,(a.active_timeout AND NOT a.matched_main) AS timeout_role_unclassified'
                fields='b.*,'+','.join('a.'+k for k in extra)+','+roles
                sql='SELECT '+fields+' FROM a JOIN b USING(row_id) ORDER BY row_id'
                if io.copy(c,sql,tmp/(cohort+'.parquet'))!=n:raise RuntimeError('Role join changed row count')
            return dict(role_authority='25% certified main-panel i/j role join; no role inferred from timeout subtraction alone')
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[entry/'prepared'/(s+'.parquet') for s in COHORTS]+[parent/'split'/('entry_'+s+'.parquet') for s in COHORTS])

def prepare_iv(binding,root,conf):
    src=Path(binding['source']['spaced'])
    def build(tmp):
        cols=list(dict.fromkeys([k for k in MODEL_COLUMNS if k not in ENTRY_COLUMNS]+['received','y','reached','game_id','anchor_ms']))
        q=io.read(src,cols).sort_by('row_id');a=arrays(q);design.row_digest(a['row_id'])
        if np.any(a['anchor_ms']+90*DAY>=core.PANEL_END):raise RuntimeError('Incomplete frozen receipt follow-up')
        if np.any(a['anchor_ms']<a['archive_start_ms']):raise RuntimeError('Invalid anchor')
        for k in ('received','y','reached'):
            if not np.isin(a[k],[0,1]).all():raise RuntimeError('Nonbinary original IV field '+k)
        # Preserve frozen spacing and all factual activity; author exclusions follow reconstruction.
        a['previous_frame']=np.ones(len(q),bool)
        a['expected_n7']=a['n_7d'].copy()
        io.table(tmp/'original.parquet',pa.table(a))
        for s in range(16):
            use=num.user_hash(a['opponent_id'])%np.uint64(16)==s
            io.table(tmp/f'score_{s:02}.parquet',pa.table(selected(a,use)))
            io.table(tmp/f'outcome_{s:02}.parquet',pa.table(selected(a,a['recipient_id']%16==s)))
        return dict(original_rows=len(q))
    return stable_stage(root,conf,build,[src])

def iv_features_job(job):
    threads_one()
    def build(tmp):
        q=arrays(io.read(job['queries']));out={'row_id':q['row_id']}
        idx=fast.ScoreIndex(job['index']);entire=idx.h
        models={key:np.load(Path(job['reference'])/(key+'.npy'),mmap_mode='r',allow_pickle=False) for key in ('original','clean')}
        for tag in ('','comp_'):
            for key in SCORE_COLS:out[tag+key]=np.zeros(len(q['row_id']),np.int64) if key.startswith(('n_','counterparts_')) else np.full(len(q['row_id']),np.nan)
        for m in np.unique(q['month_code']):
            ix=np.flatnonzero(q['month_code']==m);args=(q['opponent_id'][ix],q['recipient_id'][ix],int(m))
            idx.h=entire;old=idx.score(*args,models['original'][0,int(m)],[])
            for key in SCORE_COLS:
                if not np.allclose(old[key],q[key][ix],equal_nan=True,atol=2e-11,rtol=1e-10):raise RuntimeError('Original IV score does not reproduce: '+key)
            for tag,mask in [('',np.ones(len(entire['cell']),bool)),('comp_',entire['cell']//100>=2)]:
                idx.h={k:v[mask] for k,v in entire.items()};new=idx.score(*args,models['clean'][0,int(m)],job['authors'])
                for key in SCORE_COLS:out[tag+key][ix]=new[key]
        io.table(tmp/'scores.parquet',pa.table(out));return dict(rows=len(q['row_id']),original_scores_reproduced=True)
    return stage(job,build,[job['queries'],Path(job['reference'])/'original.npy',Path(job['reference'])/'clean.npy'])

def assemble_iv(original,scores,outcomes,ids,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([original]))
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scores))
            c.execute('CREATE VIEW o AS SELECT * FROM '+io.parq(outcomes))
            n=pq.ParquetFile(original).metadata.num_rows
            if c.execute('SELECT count(*),count(DISTINCT q.row_id) FROM q JOIN s USING(row_id) JOIN o USING(row_id)').fetchone()!=(n,n):raise RuntimeError('IV feature join changed rows')
            for key in COUNT_COLUMNS+['y','reached']:
                if c.execute('SELECT count(*) FROM q JOIN o USING(row_id) WHERE q.'+key+' IS DISTINCT FROM o.original_'+key).fetchone()[0]:raise RuntimeError('Original IV history/outcome differs: '+key)
            keep='q.recipient_id NOT IN ('+','.join(map(str,ids))+') AND q.opponent_id NOT IN ('+','.join(map(str,ids))+') AND s.n_7d>=5 AND isfinite(s.adjusted_7d) AND isfinite(s.expected_7d)'
            oldcols=list(dict.fromkeys(SCORE_COLS+COUNT_COLUMNS+['y','reached']))
            fields='q.* EXCLUDE('+','.join(oldcols)+'),s.* EXCLUDE(row_id),'+','.join('o.'+v for v in COUNT_COLUMNS+['y','reached','outcome_opponent','outcome_gid','outcome_t','outcome_start'])
            rows=io.copy(c,'SELECT '+fields+' FROM q JOIN s USING(row_id) JOIN o USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'receipt_iv.parquet')
            io.js(tmp/'reproduction.json',dict(original_rows=n,original_histories_and_outcomes_reproduced=True,rows=rows,excluded=n-rows,original_spacing_preserved=True,future_choices_author_clean=True))
            return dict(rows=rows)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[original]+scores+outcomes)
