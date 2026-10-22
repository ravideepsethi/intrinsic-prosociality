"""Audit the frozen receipt cohort without silently redefining its controls."""
from common import *

def receipt_audit(c,month):
    c.execute('''CREATE OR REPLACE TEMP TABLE receipt_join AS
      SELECT iv.*,p.* FROM iv LEFT JOIN panel p ON game_id=panel_gid''')
    # Core exposure definition is audit_logic.exposure_sql from the pinned
    # original producer: received=kind_draw; arm=kind_draw OR timeout_chooser_win.
    # A recorded claimed win did not additionally require the material flag.
    predicates={
      'invalid_received_flag':'received IS NULL OR received NOT IN (0,1)',
      'missing_panel_game':'panel_gid IS NULL',
      'recipient_id_mismatch':'panel_gid IS NOT NULL AND recipient_id IS DISTINCT FROM panel_recipient',
      'opponent_id_mismatch':'panel_gid IS NOT NULL AND opponent_id IS DISTINCT FROM panel_chooser',
      'competitive_flag_mismatch':'panel_gid IS NOT NULL AND panel_fair IS DISTINCT FROM TRUE',
      'received_flag_mismatch':'panel_gid IS NOT NULL AND received IS DISTINCT FROM panel_kind',
      'recorded_arm_missing':'panel_gid IS NOT NULL AND (panel_kind OR panel_claim) IS DISTINCT FROM TRUE',
      'anchor_mismatch':'panel_gid IS NOT NULL AND anchor_ms IS DISTINCT FROM panel_anchor',
      'start_mismatch':'panel_gid IS NOT NULL AND archive_start_ms IS DISTINCT FROM panel_start',
      'grant_material_inconsistent':'panel_kind AND (panel_material IS DISTINCT FROM TRUE OR panel_no_material IS DISTINCT FROM FALSE)',
      'claim_marked_as_no_material_draw':'panel_claim AND panel_no_material',
      'both_recorded_arms':'panel_kind AND panel_claim',
    }
    fields=['count(*) AS "rows"']+[f'count(*) FILTER(WHERE {v}) AS {k}' for k,v in predicates.items()]
    fields += [
      'count(*) FILTER(WHERE panel_claim AND panel_material IS DISTINCT FROM TRUE) AS claims_without_material_flag',
      'count(*) FILTER(WHERE panel_no_material) AS explicit_no_material_rows',
      'count(*) FILTER(WHERE received=1) AS received_rows',
      'count(*) FILTER(WHERE received=0) AS nonreceived_rows',
      'min(anchor_ms-panel_anchor) min_anchor_difference_ms',
      'max(anchor_ms-panel_anchor) max_anchor_difference_ms',
      'min(archive_start_ms-panel_start) min_start_difference_ms',
      'max(archive_start_ms-panel_start) max_start_difference_ms']
    result=records(c,'SELECT '+','.join(fields)+' FROM receipt_join')[0]
    invalid=' OR '.join('('+v+')' for v in predicates.values())
    nbad=c.execute('SELECT count(*) FROM receipt_join WHERE '+invalid).fetchone()[0]
    result.update(month=month,distinct_invalid_rows=nbad,
       status='VERIFIED' if not nbad else 'BLOCKED',
       rows_removed=0,treatment_relabelled=False,
       contract='Frozen received flag and recorded grant/claim arms; no new material requirement on recorded claimed wins')
    patterns=records(c,'''SELECT panel_gid IS NOT NULL panel_matched,received,panel_kind,panel_claim,panel_material,panel_no_material,
       recipient_id IS NOT DISTINCT FROM panel_recipient recipient_matches,
       opponent_id IS NOT DISTINCT FROM panel_chooser opponent_matches,
       anchor_ms IS NOT DISTINCT FROM panel_anchor anchor_matches,
       archive_start_ms IS NOT DISTINCT FROM panel_start start_matches,
       count(*) AS "rows" FROM receipt_join GROUP BY ALL ORDER BY ALL''')
    return result,patterns,invalid
