"""Project old raw scores to an auditable, narrow A2 Parquet; no new engine calls."""
from common import *
import gzip,chess
from lineage import receipt

MATE_LABELS=['finite','to_positive_mate','to_negative_mate','from_positive_mate',
             'from_negative_mate','positive_mate_both','negative_mate_both','missing']
PREFIXES=['own','net2','net4']
def score_kind(s):
    if s is None:return None
    if s.get('mate') is not None and s.get('status') in ['SCORED','SHORT']:
        # An exact mate may terminate search before the requested node budget.
        # Mate zero is terminal/ambiguous in this representation, not a CP observation.
        return 'positive' if s['mate']>0 else 'negative' if s['mate']<0 else None
    if s.get('status')=='SCORED' and s.get('mate') is None and s.get('cp') is not None and s.get('nodes',0)>=100000:return 'finite'
    return None
def change(a,b):
    x,y=score_kind(a),score_kind(b)
    if x is None or y is None:return (np.nan,'missing')
    if x==y=='finite':return (float(np.clip(a['cp']-b['cp'],-1000,1000))/100.,'finite')
    if x==y:return (0.,x+'_mate_both')
    if y!='finite':return (0.,'to_'+y+'_mate')
    return (0.,'from_'+x+'_mate')
def material(fen,color):
    b=chess.Board(fen);own=color=='white'
    return sum(v*(len(b.pieces(k,own))-len(b.pieces(k,not own)))
               for k,v in [(chess.PAWN,1),(chess.KNIGHT,3),(chess.BISHOP,3),(chess.ROOK,5),(chess.QUEEN,9)])
def one_game(g,rows):
    out=dict(game_id=g['game_id'],replay_status=g['status'],trajectory_ok=False,
             material_swing4=np.nan,recomputed_final_cp=np.nan,recomputed_final_mate=np.nan)
    for p in PREFIXES:out.update({p+'_loss100':np.nan,p+'_kind':'missing'})
    if g['status']!='VERIFIED':return out
    by={s['ply']:s for s in rows};n=g['n'];expected={p['ply']:p['fen'] for p in g['positions']}
    require(len(by)==len(rows) and set(by)==set(expected),'Duplicate/missing raw score positions')
    for k,s in by.items():require(s['fen']==expected[k] and s['color']==g['color'],'Raw score orientation/FEN mismatch')
    out['trajectory_ok']=all(score_kind(s) is not None for s in by.values())
    for p,(a,b) in {'own':(n-2,n-1),'net2':(n-2,n),'net4':(n-4,n)}.items():
        v,kind=change(by.get(a),by.get(b));out[p+'_loss100']=v;out[p+'_kind']=kind
    if n-4 in expected:
        # Positive swing means the rival gained material, unlike positive CP loss.
        out['material_swing4']=material(expected[n],g['color'])-material(expected[n-4],g['color'])
    if score_kind(by.get(n))=='finite':out['recomputed_final_cp']=by[n]['cp']
    if score_kind(by.get(n)) in ['positive','negative']:out['recomputed_final_mate']=by[n]['mate']
    return out
def convert_unit(job):
    unit,out,key=job;out=Path(out)
    if valid(out,key):return str(out)
    require(receipt(unit['replay'],unit['key']) and receipt(unit['scores'],unit['key']),'Raw unit not authenticated')
    games=load(unit['replay'])
    with gzip.open(unit['scores'],'rt') as f:raw=json.load(f)
    by={g['game_id']:[] for g in games}
    for s in raw:
        require(s['game_id'] in by,'Unexpected score game');by[s['game_id']].append(s)
    d=pd.DataFrame([one_game(g,by[g['game_id']]) for g in games])
    out.parent.mkdir(parents=True,exist_ok=True);tmp=Path(str(out)+'.partial')
    d.to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,out);certify(out,key)
    return str(out)

def prepare_targets(path):
    columns=['game_id','chooser','y','board','engine_eval_is_mate','ply_count','rating','gap100','premium10',
             'crd100','drd100','month','speed','log_cc','log_dc','cc_missing','dc_missing','time_control','game_ms']
    d=pq.ParquetFile(path).read(columns=columns).to_pandas()
    from a1_design import MONTHS,SPEEDS
    for src,dst,mult in [('ply_count','ply',1),('gap100','gap',100),('premium10','premium',10),('crd100','rd_c',100),('drd100','rd_d',100)]:d[dst]=d[src]*mult
    d['mate']=d.engine_eval_is_mate.astype(bool);d['cp']=d.board.where(~d.mate,np.nan)
    require(d.board.notna().all() and set(d.y.unique())<={0,1},'Invalid canonical outcome/evaluation')
    d['month_code']=d.month.map({x:i for i,x in enumerate(MONTHS)})
    d['speed_code']=d.speed.map({x:i for i,x in enumerate(SPEEDS)})
    require(d.month_code.notna().all() and d.speed_code.notna().all(),'Unknown month/speed')
    d['stage']=np.select([d.ply<2,d.ply==2,d.ply<=4,d.ply<=6,d.ply<=8,d.ply<=10,d.ply<=20,d.ply<=40,d.ply<=80],range(9),default=9)
    for side,src,miss in [('c','log_cc','cc_missing'),('d','log_dc','dc_missing')]:
        # Source PGN clocks are coarser than 1e-8 seconds; remove log/exp roundoff at cutoffs.
        d['clock_'+side]=np.expm1(d[src]).round(8).where(d[miss]==0,np.nan)
    # Source logs were log(1+seconds). Treat zero denominators as missing, never infinity.
    d['clock_ratio']=d.clock_d.div(d.clock_c.where(d.clock_c>0))
    base=pd.to_numeric(d.time_control.str.extract(r'^(\d+)\+\d+$',expand=False),errors='coerce')
    d['clock_fraction']=d.clock_d.div(base.where(base>0))
    d['time_trouble']=(d.clock_fraction<.1).astype(float).where(d.clock_fraction.notna(),np.nan)
    d['log_rival_clock']=np.log1p(d.clock_d)
    return d
