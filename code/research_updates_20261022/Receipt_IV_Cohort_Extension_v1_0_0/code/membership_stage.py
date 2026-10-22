"""Write new membership records and a normalized, known-membership choice spine."""
import shutil
from common import *
from cohort_logic import membership_sql

def build(source_root,source_result,adj_root,opportunities,old,work,auth,code,threads,memory_mb,inputs):
    key=digest(dict(code=code,inputs=inputs,source_result=source_result))
    def produce(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+scan(Path(source_root)/'source_by_game_PRIVATE.parquet'))
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(Path(adj_root)/'new_adjacency_PRIVATE.parquet'))
            c.execute('CREATE VIEW b AS SELECT * FROM '+scan(Path(adj_root)/'old_bridge_membership_PRIVATE.parquet'))
            bad=c.execute("SELECT count(*) FROM s JOIN b USING(game_id) WHERE s.source_status='recovered' AND s.source IS DISTINCT FROM b.source").fetchone()[0]
            if bad:raise RuntimeError('Recovered labels disagree with the pinned original November source layer')
            known_bridge=c.execute("SELECT count(*) FROM s JOIN b USING(game_id) WHERE s.source_status='recovered'").fetchone()[0]
            flow=[];manifest=[];unresolved=0
            for month,p in sorted(opportunities.items()):
                if month=='2023-11':continue
                c.execute('CREATE OR REPLACE VIEW o AS SELECT * FROM '+scan(p))
                root=tmp/'membership'/('month='+month);dest=root/'membership_PRIVATE.parquet'
                q=f'''SELECT o.game_id,o.month,s.source,s.source_status,s.source_provenance,
                    a.previous_classification_status,a.mutual_previous_same_pair,
                    {membership_sql()} pool_nonadjacent_eligible,
                    NULL::BOOLEAN final_iv_eligible FROM o LEFT JOIN s USING(game_id) LEFT JOIN a USING(game_id)'''
                n=copy(c,q,dest);expected=pq.ParquetFile(p).metadata.num_rows
                if n!=expected:raise RuntimeError('Membership join changed opportunity count')
                c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+scan(dest))
                if c.execute('SELECT count(DISTINCT game_id) FROM m').fetchone()[0]!=n:raise RuntimeError('Duplicate membership game')
                unresolved+=c.execute('SELECT count(*) FROM m WHERE pool_nonadjacent_eligible IS NULL').fetchone()[0]
                counts=c.execute('''SELECT count(*),count(*) FILTER(WHERE pool_nonadjacent_eligible),
                    count(*) FILTER(WHERE pool_nonadjacent_eligible IS FALSE),count(*) FILTER(WHERE pool_nonadjacent_eligible IS NULL),
                    count(*) FILTER(WHERE source_status<>'recovered') FROM m''').fetchone()
                flow.append(dict(month=month,all_source_rows=counts[0],known_main_rows=counts[1],excluded_rows=counts[2],
                    unresolved_membership_rows=counts[3],unresolved_source_rows=counts[4],historical_membership_reused=False))
                root=tmp/'known_main'/('month='+month);out=root/'choices_PRIVATE.parquet'
                q='''SELECT o.game_id,o.month,o.chooser_user_id,o.disconnected_user_id,o.utc_ms,o.anchor_ms,o.archive_ordinal,
                    o.color,o.speed,o.rating chooser_rating,o.opp_rating recipient_rating,o.cp,o.ply,o.grant::BOOLEAN kind_draw,
                    (o.grant=1 OR o.timeout_chooser_win) arm_eligible,o.cp>=-100 fair_competitive,
                    o.tournament_like_event,o.tc_base_s,o.tc_inc_s,NULL::DOUBLE chooser_rd,NULL::DOUBLE recipient_rd,
                    FALSE authenticated_rating_states_attached FROM o JOIN m USING(game_id) WHERE m.pool_nonadjacent_eligible'''
                copy(c,q,out);manifest.append(dict(month=month,path=str(out.relative_to(tmp)),rows=pq.ParquetFile(out).metadata.num_rows,origin='added_month_known_membership'))
            for rec in old['panels']:
                p=rec['path'];month=rec['month'];h=scan(p);out=tmp/'known_main'/('month='+month)/'choices_PRIVATE.parquet'
                q=f'''SELECT game_id,month,chooser_user_id,disconnected_user_id,utc_ms,api_last_move_at_ms anchor_ms,archive_ordinal,
                    lower(chooser_color) color,api_speed speed,chooser_elo chooser_rating,disconnected_elo recipient_rating,
                    engine_eval_cp_disconnected AS cp,ply_count AS ply,
                    kind_draw,(kind_draw OR timeout_chooser_win) arm_eligible,fair_competitive,tournament_like_event,
                    tc_base_s,tc_inc_s,chooser_pre_rd_v2 chooser_rd,disconnected_pre_rd_v2 recipient_rd,
                    TRUE authenticated_rating_states_attached FROM {h}'''
                n=copy(c,q,out)
                if n!=rec['rows']:raise RuntimeError('Original main choice spine lost rows')
                manifest.append(dict(month=month,path=str(out.relative_to(tmp)),rows=n,origin='pinned_original_main'))
                flow.append(dict(month=month,all_source_rows=None,known_main_rows=n,excluded_rows=None,unresolved_membership_rows=0,
                    unresolved_source_rows=0,historical_membership_reused=True))
            manifest.sort(key=lambda x:x['month']);flow.sort(key=lambda x:x['month'])
            all_paths=[tmp/r['path'] for r in manifest]
            dup=c.execute('SELECT count(*) FROM (SELECT game_id FROM '+scan(all_paths)+' GROUP BY 1 HAVING count(*)>1)').fetchone()[0]
            if dup:raise RuntimeError('Game identity overlaps across main months')
            copy(c,"SELECT * FROM "+scan(list((tmp/'membership').rglob('*.parquet')))+" WHERE pool_nonadjacent_eligible IS NULL",tmp/'unresolved_membership_PRIVATE.parquet')
            write_json(tmp/'MAIN_INPUT_MANIFEST_PRIVATE.json',dict(months=manifest,old_main_rows=41534331,
                final_iv_eligible_n=None,source_scan_issues=source_result['scan_issues'],unresolved_new_membership=unresolved,
                known_membership_spine_only=True))
            return dict(flow=flow,source_bridge=dict(compared_rows=known_bridge,total_rows=2015809,different_rows=0,
                status='RECOVERED_LABELS_AGREE' if known_bridge else 'NO_LOCAL_SOURCE_BRIDGE_COVERAGE'),
                known_main_rows=sum(x['rows'] for x in manifest),unresolved_new_membership=unresolved,
                source_scan_issues=source_result['scan_issues'],full_source_coverage=not any(r['unresolved_source_rows'] for r in flow),
                final_iv_eligible_n=None,new_rd_attachment='Not attached by this package; retained target states remain available separately')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(Path(work)/'membership'/key,key,inputs,produce,auth)
