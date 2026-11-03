"""Reuse completed records; stream wide payloads after narrow key operations."""
from common_retained import *
import stream_frames,features,fast_features
from types import SimpleNamespace

def act_features(a,run,conf,auth):
    src=Path(auth['paths']['spaced'])
    def build(tmp):
        d=sql(tmp)
        try:
            view(d,'q',src);view(d,'p',[r['path'] for r in auth['panels']])
            copy(d,'''SELECT q.row_id,engine_eval_cp_disconnected::DOUBLE board_cp,
              (recipient_id=disconnected_user_id AND opponent_id=chooser_user_id AND received IS NOT DISTINCT FROM kind_draw) identity_ok,
              chooser_win_premium_v2::DOUBLE giver_cost,chooser_draw_payoff_v2::DOUBLE giver_draw,chooser_win_payoff_v2::DOUBLE giver_win,
              CASE disconnected_color WHEN 'white' THEN white_win_premium_v2 WHEN 'black' THEN black_win_premium_v2 END::DOUBLE recipient_benefit,
              CASE disconnected_color WHEN 'white' THEN white_draw_ratingdiff_v2 WHEN 'black' THEN black_draw_ratingdiff_v2 END::DOUBLE recipient_draw,
              CASE disconnected_color WHEN 'white' THEN white_win_ratingdiff_v2 WHEN 'black' THEN black_win_ratingdiff_v2 END::DOUBLE recipient_win
              FROM q JOIN p USING(game_id) ORDER BY row_id''',tmp/'features.parquet')
            require(rows(tmp/'features.parquet')==rows(src),'Act join is incomplete or duplicated')
            view(d,'f',tmp/'features.parquet')
            c.ensure(d,'SELECT count(*) FROM f WHERE NOT coalesce(identity_ok,FALSE)','Act identity/arm disagreement')
            c.ensure(d,'''SELECT count(*) FROM f WHERE NOT coalesce(giver_cost>0 AND recipient_benefit>0
              AND abs(giver_win-giver_draw-giver_cost)<1e-7 AND abs(recipient_win-recipient_draw-recipient_benefit)<1e-7,FALSE)''','Act payoff identities failed')
            return dict(rows=rows(src))
        finally:d.close()
    out,_=stage(run/'PRIVATE/act_features',conf,build,[src]+[r['path'] for r in auth['panels']]);return out/'features.parquet'

def prospective_keep(events,person,start):
    ei=np.asarray(events['recipient_id'],np.int64);et=np.asarray(events['anchor_ms'],np.int64)
    order=np.lexsort((et,ei));ei=ei[order];et=et[order]
    keys=fast_features.moments(ei,et);at=np.searchsorted(keys,fast_features.moments(person,start),side='left')-1
    previous=np.full(len(start),-1,np.int64)
    if len(ei):
        ok=(at>=0)&(ei[np.clip(at,0,len(ei)-1)]==person);previous[ok]=et[at[ok]]
    return (previous<0)|(start>previous+90*DAY)

def spaced_frames(a,run,conf,auth):
    """Pre-game risk uses all pre-calendar-cut selected exposures, never future ones."""
    bound=read(a.parent/'PRIVATE/MATERIAL_BOUND.json');raw=Path(bound['raw']);flags=a.parent/'PRIVATE/selection90/flags.parquet'
    for p in (raw,flags):stage_record(p,PARENT_CONF)
    source=Path(auth['paths']['frame']);scores=Path(auth['paths']['frame_scores'])
    def build(tmp):
        require(np.array_equal(col(raw,'row_id'),col(flags,'row_id')),'Full spacing stream not aligned')
        selected=col(flags,'spaced90_n5').astype(bool)
        events={k:col(raw,k)[selected] for k in ('recipient_id','anchor_ms')}
        start=col(source,'archive_start_ms');person=col(source,'recipient_id')
        keep=prospective_keep(events,person,start)&(start-97*DAY>=int(c.phase_inputs.core.STARTS[0]))
        # F already uses pre-game start+90-day calendar eligibility.
        filter_pair(source,scores,tmp,keep)
        replace={k+'_90':col(tmp/'source.parquet','legacy_'+k+'_90') for k in ('fair','kind','disconnect','receipt','claim')}
        append_columns(tmp/'source.parquet',tmp/'legacy.parquet',replace);os.replace(tmp/'legacy.parquet',tmp/'source.parquet')
        return dict(rows=int(keep.sum()),cooldown='only selected anchors strictly before index start',history='97 to 7 days before start')
    root,_=stage(run/'PRIVATE/spaced_comparison',conf,build,[source,scores,raw,flags]);src=root/'source.parquet';sc=root/'scores.parquet'
    if 'pre_games_30d' not in names(src):
        known=[Path(bound['known_features'])] if isinstance(bound.get('known_features'),str) else [Path(p) for p in bound.get('known_features',[])]
        known += [a.legacy_root/'comparisons/PRIVATE/frames90/F.parquet']
        src=features.volume(a,run/'comparison_volume',conf,bound['bound'],src,known,30)
    from balance_retained import fit_balance
    fit_balance(run,conf,src,sc,'entry_spaced_recent_balance')
    def ordinary(tmp):
        keep=col(src,'ordinary_narrow').astype(bool)&col(src,'complete90').astype(bool);filter_pair(src,sc,tmp,keep);return dict(rows=int(keep.sum()))
    out,_=stage(run/'PRIVATE/spaced_ordinary',conf,ordinary,[src,sc]);fit_balance(run,conf,out/'source.parquet',out/'scores.parquet','ordinary_spaced_recent_balance')
    save(run/'report/DIAGNOSTIC_FRAME_COUNTS.json',[
        dict(frame=label,n=rows(path),row_set_sha256=c.frozen.r.design.row_digest(col(path,'row_id')),reference_count_in_note=reference,
             reference_count_matches=rows(path)==reference,source='material-corrected existing comparison frame, spaced eligibility and gap-seven histories')
        for label,path,reference in [('entry',src,17745415),('ordinary',out/'source.parquet',11410477)]])
