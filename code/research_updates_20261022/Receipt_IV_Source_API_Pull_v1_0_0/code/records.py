"""Match API facts to frozen targets; keep mismatches explicit."""
import json
from common import pa

SOURCES={'pool','lobby','friend','ai','api','tournament','arena','swiss','simul',
         'position','import','importlive','relay','hook'}
SCHEMA=pa.schema([
    ('game_id',pa.string()),('month',pa.string()),('record_status',pa.string()),
    ('source',pa.string()),('api_status',pa.string()),('api_created_at_ms',pa.int64()),
    ('api_last_move_at_ms',pa.int64()),('api_winner',pa.string()),('winner_field_present',pa.bool_()),
    ('api_rated',pa.bool_()),('api_variant',pa.string()),('api_speed',pa.string()),('api_perf',pa.string()),
    ('white_user_id',pa.string()),('black_user_id',pa.string()),
    ('white_rating',pa.int64()),('black_rating',pa.int64()),
    ('white_rating_diff',pa.int64()),('black_rating_diff',pa.int64()),
    ('white_provisional',pa.bool_()),('black_provisional',pa.bool_()),
    ('clock_initial_s',pa.int64()),('clock_increment_s',pa.int64()),('clock_total_time_s',pa.int64()),
    ('clocks_centiseconds',pa.list_(pa.int64())),('clocks_count',pa.int64()),
    ('arena_id',pa.string()),('swiss_id',pa.string()),
    ('source_validation_errors',pa.list_(pa.string())),('metadata_notes',pa.list_(pa.string())),
    ('expected_winner',pa.string()),('expected_start_ms',pa.int64()),('native_attempt',pa.string())])

def integer(x):return x if type(x) is int and -(2**63)<=x<2**63 else None
def string(x):return x if isinstance(x,str) else None
def mapping(x):return x if isinstance(x,dict) else {}
def boolean(x):return x if type(x) is bool else None

def normalize(obj,target,attempt):
    if not isinstance(obj,dict) or obj.get('id')!=target['game_id']:
        raise RuntimeError('Unexpected game ID or JSON record shape')
    created=integer(obj.get('createdAt'));last=integer(obj.get('lastMoveAt'))
    source=string(obj.get('source'));winner=obj.get('winner');errors=[];notes=[]
    if created is None:errors.append('missing_or_invalid_createdAt')
    elif target['api_created_at_ms'] is not None:
        if created!=target['api_created_at_ms']:errors.append('createdAt_mismatch')
    elif created//1000!=target['utc_ms']//1000:errors.append('start_second_mismatch')
    if obj.get('status')!='timeout':errors.append('status_not_timeout')
    if winner!=target['expected_winner']:errors.append('winner_mismatch')
    if obj.get('rated') is not True:errors.append('not_rated')
    if obj.get('variant')!='standard':errors.append('variant_not_standard')
    players=mapping(obj.get('players'))
    if not all(isinstance(players.get(color),dict) for color in ('white','black')):
        errors.append('missing_player_structure')
    if not source:errors.append('missing_source')
    elif source not in SOURCES:errors.append('unrecognized_source')
    if last is None or created is None or last<created:notes.append('lastMoveAt_unusable')
    clocks=obj.get('clocks')
    if not isinstance(clocks,list) or not all(integer(v) is not None and v>=0 for v in clocks):
        clocks=None;notes.append('clock_history_unavailable_or_invalid')
    status=('validated_source' if not errors else
            'returned_source_missing' if errors==['missing_source'] else
            'returned_unrecognized_source' if errors==['unrecognized_source'] else
            'returned_metadata_mismatch')
    row=dict(game_id=target['game_id'],month=target['month'],record_status=status,
        source=source,api_status=string(obj.get('status')),api_created_at_ms=created,
        api_last_move_at_ms=last,api_winner=winner if winner in ('white','black') else None,
        winner_field_present='winner' in obj,api_rated=boolean(obj.get('rated')),
        api_variant=string(obj.get('variant')),api_speed=string(obj.get('speed')),
        api_perf=string(obj.get('perf')),clocks_centiseconds=clocks,
        clocks_count=len(clocks) if clocks is not None else None,
        arena_id=string(mapping(obj.get('arenaTour')).get('id')),
        swiss_id=string(mapping(obj.get('swissTour')).get('id')),
        source_validation_errors=errors,metadata_notes=notes,
        expected_winner=target['expected_winner'],expected_start_ms=target['utc_ms'],native_attempt=attempt)
    for color in ('white','black'):
        player=mapping(players.get(color));user=mapping(player.get('user'))
        row[color+'_user_id']=string(user.get('id'))
        row[color+'_rating']=integer(player.get('rating'))
        row[color+'_rating_diff']=integer(player.get('ratingDiff'))
        # Missing provisional is not silently interpreted as false.
        row[color+'_provisional']=boolean(player.get('provisional'))
        if row[color+'_user_id'] is None:notes.append(color+'_user_id_unavailable')
        if row[color+'_rating'] is None:notes.append(color+'_rating_unavailable')
    clock=mapping(obj.get('clock'))
    for out,key in (('clock_initial_s','initial'),('clock_increment_s','increment'),('clock_total_time_s','totalTime')):
        row[out]=integer(clock.get(key))
    return row

def not_returned(target):
    row={name:None for name in SCHEMA.names}
    row.update(game_id=target['game_id'],month=target['month'],record_status='not_returned_after_retries',
        source_validation_errors=['not_returned_after_retries'],metadata_notes=[],
        expected_winner=target['expected_winner'],expected_start_ms=target['utc_ms'])
    return row
