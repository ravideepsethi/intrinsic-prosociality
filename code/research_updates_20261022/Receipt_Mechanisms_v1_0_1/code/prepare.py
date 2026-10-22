"""Recover outcomes/roles without new API requests, replay, or engine searches."""
from common import *
from concurrent.futures import ThreadPoolExecutor, as_completed
from receipt_check import receipt_audit

F_EXTRA=['entry_eligible','complete90','status','recipient_username','opponent_username',
         'matched_main','recipient_disconnect_main','recipient_fair_arm_main','author_game']
P_REQUIRED=['game_id','chooser_user_id','disconnected_user_id','api_last_move_at_ms','utc_ms',
    'chooser_color','disconnected_color','kind_draw','timeout_chooser_win','fair_competitive',
    'chooser_has_mating_material','timeout_draw_no_mating_material','chooser_win_premium_v2',
    'chooser_draw_payoff_v2','chooser_win_payoff_v2','chooser_pre_rd_v2','disconnected_pre_rd_v2',
    'white_win_premium_v2','black_win_premium_v2','white_draw_ratingdiff_v2','black_draw_ratingdiff_v2',
    'white_win_ratingdiff_v2','black_win_ratingdiff_v2','engine_eval_cp_disconnected','ply_count',
    'chooser_clock_last_obs_s','disconnected_clock_last_obs_s']

def validate_common(c,table,ids,all_complete=False):
    author=','.join(str(int(i)) for i in ids)
    bad=c.execute(f'''SELECT count(*) FROM {table} WHERE
        recipient_id IS NULL OR opponent_id IS NULL OR recipient_id<0 OR opponent_id<0 OR recipient_id=opponent_id
        OR recipient_id IN ({author}) OR opponent_id IN ({author})
        OR archive_start_ms IS NULL OR anchor_ms IS NULL OR anchor_ms<archive_start_ms
        OR complete90 IS DISTINCT FROM (anchor_ms+{90*DAY}<{PANEL_END})
        OR (complete90 AND (y IS NULL OR reached IS NULL OR y NOT IN (0,1) OR reached NOT IN (0,1) OR y>reached))
        OR (NOT complete90 AND (y IS NOT NULL OR reached IS NOT NULL))
        OR (reached=1 AND (outcome_opponent IS NULL OR outcome_opponent<0 OR outcome_opponent=recipient_id
          OR outcome_opponent=opponent_id OR outcome_opponent IN ({author}) OR outcome_gid IS NULL
          OR outcome_gid=game_id OR outcome_t IS NULL OR outcome_start IS NULL
          OR outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY} OR outcome_start<=anchor_ms))
        OR (complete90 AND reached=0 AND y<>0)''').fetchone()[0]
    if bad:raise RuntimeError(f'{bad} invalid identities, author exclusions, follow-up times or censoring in {table}')
    if all_complete and c.execute(f'SELECT count(*) FROM {table} WHERE NOT complete90').fetchone()[0]:
        raise RuntimeError('Incomplete original receipt cohort')
    n,u=c.execute(f'SELECT count(*),count(DISTINCT game_id) FROM {table}').fetchone()
    if n!=u:raise RuntimeError('Duplicate focal games in '+table)

def classification_sql():
    # Only the disconnected player receives a grant/claimed loss. Never infer
    # the recipient from who lost; role is authenticated against the main panel.
    return '''CASE
      WHEN status='timeout' AND panel_role='disconnected' AND panel_fair
        AND panel_kind AND panel_material AND NOT panel_no_material AND winner IS NULL THEN 'granted_draw'
      WHEN status='timeout' AND panel_role='disconnected' AND panel_fair
        AND panel_claim AND panel_material AND winner=chooser_color THEN 'claimed_loss'
      WHEN status='timeout' AND panel_role='disconnected' AND panel_no_material
        AND NOT panel_material AND winner IS NULL AND panel_fair THEN 'no_material_draw'
      WHEN status='timeout' AND panel_role='disconnected' AND panel_no_material
        AND NOT panel_material AND winner IS NULL THEN 'no_material_other_position'
      WHEN status='stalemate' AND winner IS NULL THEN 'ordinary_stalemate'
      WHEN status='draw' AND winner IS NULL THEN 'ordinary_draw_unspecified'
      WHEN status IN ('mate','resign') AND focal_color IS NOT NULL AND winner<>focal_color THEN 'ordinary_loss'
      WHEN status IN ('mate','resign') AND focal_color IS NOT NULL AND winner=focal_color THEN 'ordinary_win'
      WHEN status='timeout' AND panel_role='chooser' THEN 'timeout_chooser_role'
      WHEN status='timeout' AND panel_gid IS NULL THEN 'timeout_not_in_certified_panel'
      ELSE 'unclassified_or_other_ending' END'''

def build_metadata(binding,work,key,threads,memory):
    out=Path(work)/'focal';out.mkdir(parents=True,exist_ok=True)
    metas=binding['metadata'];start=time.monotonic()
    with ThreadPoolExecutor(max_workers=min(threads,4)) as pool:
        futures=[pool.submit(authenticate,r['path'],work,r['sha256'],r['bytes']) for r in metas]
        for i,f in enumerate(as_completed(futures),1):
            f.result()
            if i==len(metas) or i%10==0:log(f'Metadata verified {i}/{len(metas)}; elapsed {(time.monotonic()-start)/60:.1f} min')
    if checkpoint_ok(out,key):log('Reusing verified focal metadata');return out/'focal.parquet'
    c=conn(Path(work)/'spill/metadata',threads,memory)
    try:
        for r in metas:require_columns(r['path'],['game_id','status','winner','white_username','black_username','anchor_ms'])
        c.execute('CREATE VIEW f AS SELECT * FROM '+scan(binding['feature'])+' WHERE NOT previous_frame')
        c.execute('CREATE TEMP TABLE m AS SELECT game_id,status,winner,white_username,black_username,anchor_ms FROM '+
                  scan([r['path'] for r in metas])+' SEMI JOIN f USING(game_id)')
        if c.execute('SELECT count(*)-count(DISTINCT game_id) FROM m').fetchone()[0]:raise RuntimeError('Duplicate winner metadata')
        bad=c.execute('''SELECT count(*) FROM f LEFT JOIN m USING(game_id) WHERE m.game_id IS NULL
            OR f.status IS DISTINCT FROM m.status OR f.anchor_ms IS DISTINCT FROM m.anchor_ms
            OR (m.winner IS NOT NULL AND m.winner NOT IN ('white','black'))
            OR (f.status IN ('mate','resign') AND m.winner IS NULL)
            OR (f.status IN ('draw','stalemate') AND m.winner IS NOT NULL)''').fetchone()[0]
        if bad:raise RuntimeError(f'{bad} missing/conflicting terminal metadata rows; no additional quarantine permitted')
        # Use BOTH names, and preserve ambiguity when both API labels are ghost.
        white="lower(trim(f.recipient_username))=lower(trim(m.white_username)) AND lower(trim(f.opponent_username))=lower(trim(m.black_username))"
        black="lower(trim(f.recipient_username))=lower(trim(m.black_username)) AND lower(trim(f.opponent_username))=lower(trim(m.white_username))"
        orientation=f"CASE WHEN ({white}) AND NOT ({black}) THEN 'white' WHEN ({black}) AND NOT ({white}) THEN 'black' END"
        fields=','.join('f.'+x for x in BASE+F_EXTRA)
        copy(c,f'SELECT {fields},m.winner,{orientation} focal_color FROM f JOIN m USING(game_id) ORDER BY month_code,row_id',out/'focal.parquet')
        # Rejected feature queries may contain author rows only among legacy rows;
        # all new rows used here must already be clean before any model selection.
        c.execute('CREATE VIEW newf AS SELECT * FROM '+scan(out/'focal.parquet'))
        validate_common(c,'newf',binding['author_ids'].values())
        counts=records(c,'''SELECT month_code,status,entry_eligible,complete90,count(*) AS "rows",
            count(*) FILTER(WHERE focal_color IS NULL) ambiguous_orientation FROM newf GROUP BY ALL ORDER BY 1,2,3,4''')
        csvwrite(out/'feature_flow.csv',counts)
        if c.execute('SELECT count(*) FROM newf WHERE author_game').fetchone()[0]:raise RuntimeError('Author row in new focal cohort')
        finish(out,key)
    finally:c.close()
    return out/'focal.parquet'

def panel_projection():
    return '''SELECT p.game_id panel_gid,p.chooser_user_id panel_chooser,p.disconnected_user_id panel_recipient,
      p.api_last_move_at_ms panel_anchor,p.utc_ms panel_start,p.chooser_color,p.disconnected_color,
      p.kind_draw panel_kind,p.timeout_chooser_win panel_claim,p.fair_competitive panel_fair,
      p.chooser_has_mating_material panel_material,p.timeout_draw_no_mating_material panel_no_material,
      p.chooser_win_premium_v2 giver_cost,p.chooser_draw_payoff_v2 giver_draw,
      p.chooser_win_payoff_v2 giver_win,p.chooser_pre_rd_v2 giver_rd,p.disconnected_pre_rd_v2 recipient_rd,
      CASE disconnected_color WHEN 'white' THEN white_win_premium_v2 WHEN 'black' THEN black_win_premium_v2 END recipient_benefit,
      CASE disconnected_color WHEN 'white' THEN white_draw_ratingdiff_v2 WHEN 'black' THEN black_draw_ratingdiff_v2 END recipient_draw,
      CASE disconnected_color WHEN 'white' THEN white_win_ratingdiff_v2 WHEN 'black' THEN black_win_ratingdiff_v2 END recipient_win,
      engine_eval_cp_disconnected board_cp,ply_count ply,chooser_clock_last_obs_s giver_clock,
      disconnected_clock_last_obs_s recipient_clock FROM p SEMI JOIN need ON p.game_id=need.game_id'''

def month_job(job):
    binding,rec,focal,work,key,memory=job;month=rec['month'];m=MONTHS.index(month)
    out=Path(work)/'months'/month;out.mkdir(parents=True,exist_ok=True)
    authenticate(rec['path'],work,rec['sha256'],rec['size_bytes']);require_columns(rec['path'],P_REQUIRED)
    if checkpoint_ok(out,key):return str(out)
    c=conn(Path(work)/'spill'/month,1,memory)
    try:
        c.execute(f'CREATE TEMP TABLE f AS SELECT * FROM {scan(focal)} WHERE month_code={m}')
        c.execute(f'''CREATE TEMP TABLE iv AS SELECT {','.join(BASE)},received,
            (anchor_ms+{90*DAY}<{PANEL_END}) complete90 FROM {scan(binding['receipt'])} WHERE month_code={m}''')
        c.execute('CREATE TEMP TABLE need AS SELECT game_id FROM f UNION SELECT game_id FROM iv')
        c.execute('CREATE VIEW p AS SELECT * FROM '+scan(rec['path']))
        c.execute('CREATE TEMP TABLE panel AS '+panel_projection())
        if c.execute('SELECT count(*)-count(DISTINCT panel_gid) FROM panel').fetchone()[0]:raise RuntimeError('Duplicate certified panel identities')
        if c.execute('''SELECT count(*) FROM f JOIN panel ON game_id=panel_gid WHERE
            status<>'timeout' OR NOT ((recipient_id=panel_recipient AND opponent_id=panel_chooser)
              OR (recipient_id=panel_chooser AND opponent_id=panel_recipient))
            OR anchor_ms<>panel_anchor OR archive_start_ms<>panel_start''').fetchone()[0]:
            raise RuntimeError('Panel/phase role or time disagreement: '+month)
        if c.execute('''SELECT count(*) FROM f LEFT JOIN panel ON game_id=panel_gid
            WHERE matched_main IS DISTINCT FROM (panel_gid IS NOT NULL)
            OR recipient_disconnect_main IS DISTINCT FROM coalesce(recipient_id=panel_recipient,false)
            OR recipient_fair_arm_main IS DISTINCT FROM coalesce(recipient_id=panel_recipient AND panel_fair AND (panel_kind OR panel_claim),false)''').fetchone()[0]:
            raise RuntimeError('Saved main-panel role classification failed reproduction: '+month)
        c.execute('''CREATE TEMP TABLE joined AS SELECT f.*,p.*,
            CASE WHEN recipient_id=panel_recipient THEN 'disconnected' WHEN recipient_id=panel_chooser THEN 'chooser' END panel_role
            FROM f LEFT JOIN panel p ON game_id=panel_gid''')
        if c.execute('''SELECT count(*) FROM joined WHERE panel_gid IS NOT NULL AND
           ((panel_kind AND (winner IS NOT NULL OR NOT panel_material OR panel_no_material))
             OR (panel_claim AND winner IS DISTINCT FROM chooser_color)
             OR (panel_no_material AND (winner IS NOT NULL OR panel_material)))''').fetchone()[0]:
            raise RuntimeError('Contradictory grant/material/result flags: '+month)
        copy(c,'SELECT *, '+classification_sql()+' exposure_group FROM joined ORDER BY row_id',out/'comparisons.parquet')
        c.execute('CREATE VIEW classified AS SELECT * FROM '+scan(out/'comparisons.parquet'))
        coverage=records(c,'''SELECT month_code,exposure_group,entry_eligible,complete90,count(*) AS "rows",
           count(DISTINCT recipient_id) recipients,sum(y::BIGINT) kind_events,sum(reached::BIGINT) reached_events
           FROM classified GROUP BY ALL ORDER BY 1,2,3,4''')
        csvwrite(out/'coverage.csv',coverage)
        inventory=records(c,'''SELECT count(*) full_certified_panel_rows,
          count(*) FILTER(WHERE timeout_draw_no_mating_material) full_panel_no_material_rows,
          count(*) FILTER(WHERE timeout_draw_no_mating_material AND fair_competitive) full_panel_fair_no_material_rows
          FROM p''')[0]
        inventory['month']=month;write(out/'material_inventory.json',inventory)
        # Seal primary comparison files BEFORE the separate receipt/dose check.
        # A secondary diagnostic cannot erase or block valid primary comparisons.
        primary_files=['comparisons.parquet','coverage.csv','material_inventory.json']
        write(out/'PRIMARY_DONE.json',dict(key=key,files=[dict(path=x,sha256=sha(out/x),bytes=(out/x).stat().st_size) for x in primary_files]))
        receipt,patterns,invalid=receipt_audit(c,month)
        try:validate_common(c,'iv',binding['author_ids'].values(),True)
        except RuntimeError as e:receipt.update(common_validation_error=str(e),status='BLOCKED')
        write(out/'receipt_audit.json',receipt);csvwrite(out/'receipt_patterns.csv',patterns)
        if receipt['status']=='BLOCKED':
            copy(c,'SELECT * FROM receipt_join WHERE '+invalid+' LIMIT 100',out/'receipt_mismatches_PRIVATE.parquet')
            write(out/'secondary_status.json',dict(status='BLOCKED',month=month,
              reason=receipt.get('common_validation_error','Frozen receipt cohort failed recorded-arm, identity, position or timing checks'),
              distinct_invalid_rows=receipt['distinct_invalid_rows'],rows_removed=0))
            log(f'{month}: primary ready; secondary check found {receipt["distinct_invalid_rows"]:,} inconsistent rows; detailed counts saved')
            finish(out,key);return str(out)
        copy(c,'SELECT iv.*,p.* FROM iv JOIN panel p ON game_id=panel_gid ORDER BY row_id',out/'dose.parquet')
        audit=records(c,'''SELECT count(*) AS "rows",
            count(*) FILTER(WHERE NOT coalesce(isfinite(giver_cost) AND giver_cost>0 AND isfinite(giver_win)
                AND isfinite(giver_draw) AND abs(giver_win-giver_draw-giver_cost)<1e-7,false)) invalid_giver_payoff,
            count(*) FILTER(WHERE NOT coalesce(isfinite(recipient_benefit) AND recipient_benefit>0
                AND isfinite(recipient_win) AND isfinite(recipient_draw)
                AND abs(recipient_win-recipient_draw-recipient_benefit)<1e-7,false)) invalid_recipient_payoff,
            count(*) FILTER(WHERE NOT coalesce(isfinite(giver_rd) AND giver_rd>0 AND isfinite(recipient_rd) AND recipient_rd>0,false)) invalid_rd,
            max(abs(giver_win-giver_draw-giver_cost)) giver_identity_error,
            max(abs(recipient_win-recipient_draw-recipient_benefit)) recipient_identity_error
            FROM '''+scan(out/'dose.parquet'))[0]
        audit['month']=month;write(out/'payoff_audit.json',audit)
        invalid_payoff=bool(audit['invalid_giver_payoff'] or audit['invalid_recipient_payoff'] or audit['invalid_rd'])
        write(out/'secondary_status.json',dict(status='BLOCKED' if invalid_payoff else 'VERIFIED',month=month,
            reason='Invalid pregame payoff/RD fields' if invalid_payoff else None,rows_removed=0))
        finish(out,key);return str(out)
    finally:c.close()

def prepare(binding,work,key,threads,memory):
    focal=build_metadata(binding,work,key,threads,memory)
    # Retain all months in the source audit; 90-day support determines usable rows.
    jobs=[(binding,r,str(focal),str(work),key,max(1,memory/min(threads,4))) for r in binding['panels']]
    start=time.monotonic();outputs=[];failures=[]
    with ThreadPoolExecutor(max_workers=min(threads,4)) as pool:
        pending={pool.submit(month_job,j):j[1]['month'] for j in jobs}
        for i,f in enumerate(as_completed(pending),1):
            try:outputs.append(f.result())
            except Exception as e:failures.append(dict(month=pending[f],error=str(e)))
            elapsed=time.monotonic()-start
            log(f'Months prepared {i}/{len(jobs)} ({pending[f]}); estimated remaining {elapsed/i*(len(jobs)-i)/60:.1f} min')
    if failures:
        write(Path(work)/'preparation_failures.json',failures)
        first=failures[0]
        raise RuntimeError(f'{len(failures)} month preparation failures; first: {first["month"]}: {first["error"]}. See preparation_failures.json for all errors')
    (Path(work)/'preparation_failures.json').unlink(missing_ok=True)
    return sorted(outputs)
