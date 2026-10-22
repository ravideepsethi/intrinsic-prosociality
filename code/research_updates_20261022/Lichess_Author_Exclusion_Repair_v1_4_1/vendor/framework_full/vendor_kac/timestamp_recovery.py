"""Recover one affected pre-buffer timestamp from a verified public game export.

Source Parquets are read only. Game/account identifiers and the public response
are retained privately, never in the exported report.
"""
from util import *
import urllib.request,urllib.error,ssl

def validate_game(obj,row,expected_names):
    require(obj.get('id')==row['game_id'],'RECOVERY_GAME_ID_MISMATCH')
    require(obj.get('rated') is True and obj.get('variant')=='standard' and obj.get('speed')=='bullet',
        'RECOVERY_GAME_CLASS_MISMATCH')
    stamp=obj.get('createdAt');last=obj.get('lastMoveAt')
    require(isinstance(stamp,int) and not isinstance(stamp,bool) and isinstance(last,int) and last>=stamp,
        'RECOVERY_INVALID_API_TIME')
    lo=int(pd.Timestamp('2023-06-01',tz='UTC').timestamp()*1000)
    hi=int(pd.Timestamp('2023-07-01',tz='UTC').timestamp()*1000)
    require(lo<=stamp<hi,'RECOVERY_TIME_OUTSIDE_AUTHENTICATED_ARCHIVE_MONTH')
    require(obj.get('status') not in (None,'created','started','aborted','noStart'),'RECOVERY_UNFINISHED_GAME')
    winner=obj.get('winner');code=2 if winner=='white' else 0 if winner=='black' else 1
    require(code==int(row['result_code']),'RECOVERY_RESULT_MISMATCH')
    require(bool(expected_names),'RECOVERY_NO_ANALYSIS_CHOOSER_IDENTITY')
    for color in ('white','black'):
        player=obj.get('players',{}).get(color,{})
        require(player.get('rating')==int(row[color+'_elo']),'RECOVERY_RATING_MISMATCH')
        uid=int(row[color+'_id'])
        if uid in expected_names:
            name=player.get('user',{}).get('id','')
            require(isinstance(name,str) and name.lower()==expected_names[uid],
                'RECOVERY_CHOOSER_IDENTITY_MISMATCH')
    # Original chronology parses second-resolution PGN start times.
    return stamp//1000*1000

def fetch_game(gid,folder):
    require(re.fullmatch(r'[A-Za-z0-9]{8}',gid) is not None,'RECOVERY_INVALID_GAME_KEY')
    path=folder/'public_game.json';receipt=folder/'public_game_receipt.json'
    if path.is_file() and receipt.is_file():
        meta=load(receipt)
        require(meta['requested_game']==gid and sha(path)==meta['sha256'],'RECOVERY_RESPONSE_CACHE_DAMAGED')
        return load(path)
    url='https://lichess.org/api/games/export/_ids?moves=false&clocks=false&evals=false&opening=false&literate=false&pgnInJson=false'
    req=urllib.request.Request(url,data=gid.encode('ascii'),method='POST',headers={
        'Accept':'application/x-ndjson','Content-Type':'text/plain',
        'User-Agent':'Lichess-Kindness-Timestamp-Verification/1.0.2'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=60,context=ssl.create_default_context()) as response:
                payload=response.read(2*1024**2+1)
            require(len(payload)<=2*1024**2,'RECOVERY_RESPONSE_TOO_LARGE')
            objects=[json.loads(line) for line in payload.decode().splitlines() if line.strip()]
            require(len(objects)==1 and objects[0].get('id')==gid,'RECOVERY_GAME_UNAVAILABLE_OR_WRONG')
            js(path,objects[0]);js(receipt,dict(requested_game=gid,sha256=sha(path),
                queried_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),endpoint='public game export'))
            return objects[0]
        except urllib.error.HTTPError as e:
            if e.code==429 and attempt<2:
                log('Single-game export rate limited; waiting 60 seconds before retry');time.sleep(60);continue
            raise RuntimeError('RECOVERY_HTTP_'+str(e.code)) from None
        except (urllib.error.URLError,TimeoutError):
            raise RuntimeError('RECOVERY_NETWORK_OR_TLS_UNAVAILABLE') from None
    raise RuntimeError('RECOVERY_RETRY_LIMIT')

def recover(cat,run,key,audit):
    if audit['status'].startswith('PASS_'):return audit
    root=Path(run)/'PRIVATE/timestamp_recovery';root.mkdir(parents=True,exist_ok=True)
    report=dict(status='BLOCKED',source_rows_unchanged=True,analysis_accounts_excluded=0,
        method='one verified public game createdAt; milliseconds floored to original second precision')
    js(Path(run)/'report/TIMESTAMP_AUDIT_RAW.json',audit)
    try:
        bad=[r for r in audit['suspicious_files'] if r.get('affected_choosers',0)]
        require(len(bad)==1 and bad[0]['month']=='2023-06' and bad[0]['speed']=='bullet' and
            bad[0]['invalid_needed_chooser_rows']==1 and bad[0]['affected_choosers']==1,
            'RECOVERY_SCOPE_DIFFERS_FROM_REVIEWED_SINGLE_ROW')
        source=next(r for r in cat['chronology'] if r['month']=='2023-06' and r['speed']=='bullet')
        require(snapshot(source['path'])==source['stat'],'RECOVERY_SOURCE_CHANGED')
        c=db(root/'spill',1.5,1)
        try:
            c.execute('CREATE VIEW needed AS SELECT * FROM '+scan(Path(run)/'PRIVATE/needed.parquet'))
            row=c.execute('''SELECT game_id,utc_ms,white_id,black_id,white_elo,black_elo,result_code
                FROM '''+scan(source['path'])+''' WHERE (utc_ms IS NULL OR utc_ms<=0) AND
                (white_id IN(SELECT chooser FROM needed) OR black_id IN(SELECT chooser FROM needed))''').fetchdf()
            require(len(row)==1,'RECOVERY_AFFECTED_ROW_COUNT_CHANGED')
            row=row.iloc[0].to_dict()
            ids=[int(row['white_id']),int(row['black_id'])]
            names={}
            # Resolve the affected chooser through certified panel identities,
            # reading only ID/name columns; no global account/profile query.
            for month in cat['main']['month_records']:
                nameset=pq.ParquetFile(month['path']).schema_arrow.names
                col=next((s for s in ('chooser_username_norm','chooser_username') if s in nameset),None)
                require(col is not None,'RECOVERY_CERTIFIED_USERNAME_COLUMN_MISSING')
                found=c.execute(f'SELECT DISTINCT chooser_user_id,lower(trim({col})) FROM '+scan(month['path'])+
                    ' WHERE chooser_user_id IN ('+','.join(map(str,ids))+')').fetchall()
                for uid,name in found:
                    require(isinstance(name,str) and name and (int(uid) not in names or names[int(uid)]==name),
                        'RECOVERY_CHOOSER_NAME_AMBIGUOUS')
                    names[int(uid)]=name
                if names:break
            require(bool(names),'RECOVERY_CHOOSER_NAME_UNAVAILABLE')
        finally:c.close();shutil.rmtree(root/'spill',ignore_errors=True)
        obj=fetch_game(row['game_id'],root)
        stamp=validate_game(obj,row,names)
        overlay=pd.DataFrame([dict(game_id=row['game_id'],white_id=int(row['white_id']),black_id=int(row['black_id']),utc_ms=stamp)])
        out=root/'overlay.parquet';tmp=out.with_suffix('.partial.parquet');overlay.to_parquet(tmp,index=False);os.replace(tmp,out)
        auth=checked(source['path']);require(auth['stat']==source['stat'],'RECOVERY_SOURCE_CHANGED_DURING_CHECK')
        js(root/'overlay_receipt.json',dict(key=key,overlay_sha256=sha(out),source=auth,
            response_sha256=sha(root/'public_game.json'),validated_game_id=True,validated_chooser_identity=True,
            validated_ratings=True,validated_result=True,validated_archive_month=True))
        report.update(status='VERIFIED_SINGLE_ROW_OVERLAY',repaired_rows=1,affected_choosers=1,
            source_sha256=auth['sha256'],response_sha256=sha(root/'public_game.json'),
            timestamp_precision='one second',recovered_month='2023-06')
        audit=dict(audit,original_status=audit['status'],status='PASS_VERIFIED_TIMESTAMP_OVERLAY',
            unresolved_analysis_chooser_rows=0,recovered_rows=1)
    except Exception as e:
        # Detailed source records remain private. Export only a diagnostic code.
        report['reason']=str(e) if isinstance(e,RuntimeError) and str(e).startswith('RECOVERY_') else type(e).__name__
        log('Timestamp recovery blocked: '+report['reason']+'. Hour models continue.')
    js(Path(run)/'report/TIMESTAMP_RECOVERY.json',report)
    js(Path(run)/'report/TIMESTAMP_AUDIT.json',audit)
    return audit

def overlay_path(run,source_path,key):
    root=Path(run)/'PRIVATE/timestamp_recovery';receipt=root/'overlay_receipt.json'
    if not receipt.is_file():return None
    r=load(receipt)
    if r['source']['path']!=str(source_path):return None
    require(r['key']==key and snapshot(source_path)==r['source']['stat'],'RECOVERY_OVERLAY_IDENTITY_CHANGED')
    path=root/'overlay.parquet'
    require(sha(path)==r['overlay_sha256'] and sha(root/'public_game.json')==r['response_sha256'],
        'RECOVERY_OVERLAY_OR_RESPONSE_DAMAGED')
    return path
