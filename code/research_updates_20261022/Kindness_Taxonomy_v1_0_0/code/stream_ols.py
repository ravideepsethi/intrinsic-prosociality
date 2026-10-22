"""Streaming one-way FE LPM; account-cluster inference on target contrasts."""
from common import *

def fit(c,query,columns,target_names,group='chooser',outcome='y'):
    c.execute('CREATE OR REPLACE TEMP VIEW stream_source AS '+query)
    invalid=' OR '.join(f'{s} IS NULL OR NOT isfinite({s})' for s in columns+[outcome])
    if c.execute(f'SELECT count(*) FROM stream_source WHERE {invalid}').fetchone()[0]:raise RuntimeError('Nonfinite streaming model rows')
    c.execute('CREATE OR REPLACE TEMP TABLE stream_means AS SELECT '+group+','+','.join(f'avg({s}) m_{s}' for s in columns+[outcome])+',count(*) n FROM stream_source GROUP BY '+group)
    sql='SELECT s.'+group+','+','.join(f's.{s}-m.m_{s} {s}' for s in columns+[outcome])+' FROM stream_source s JOIN stream_means m USING('+group+')'
    P=len(columns);G=np.zeros((P,P));xy=np.zeros(P);N=0
    for batch in c.execute(sql).to_arrow_reader(100000):
        d=arrays(pa.Table.from_batches([batch]));x=np.column_stack([d[s] for s in columns]);y=d[outcome];G+=x.T@x;xy+=x.T@y;N+=len(y)
    sd=np.sqrt(np.diag(G)/max(1,N));use=sd>1e-12;dropped=[s for s,u in zip(columns,use) if not u]
    info=dict(rows=N,dropped_constant_controls=dropped,targets=target_names,covariance='chooser-cluster CR1',fixed_effects=group)
    if any(t in dropped for t in target_names):return dict(info,status='TARGET_NO_WITHIN_VARIATION'),[]
    inds=np.flatnonzero(use);names=[columns[j] for j in inds];qg=G[np.ix_(inds,inds)]/np.outer(sd[use],sd[use]);cond=np.linalg.cond(qg)
    info['standardized_gram_condition']=float(cond)
    if not np.isfinite(cond) or cond>1e10:return dict(info,status='RANK_FAILURE'),[]
    inv=np.linalg.inv(qg)/np.outer(sd[use],sd[use]);beta=inv@xy[use];targets=[names.index(t) for t in target_names]
    groups=c.execute('SELECT '+group+' FROM stream_means ORDER BY '+group).fetchnumpy()[group];score=np.zeros((len(groups),len(targets)))
    for batch in c.execute(sql).to_arrow_reader(100000):
        d=arrays(pa.Table.from_batches([batch]));x=np.column_stack([d[s] for s in names]);res=d[outcome]-x@beta;h=(x@inv[:,targets])*res[:,None];ix=np.searchsorted(groups,d[group])
        for j in range(len(targets)):np.add.at(score[:,j],ix,h[:,j])
    rank=len(groups)+len(names);V=score.T@score
    if len(groups)>1 and N>rank:V*=len(groups)/(len(groups)-1)*(N-1)/(N-rank)
    else:return dict(info,status='NO_RESIDUAL_DF'),[]
    rows=[]
    for k,j in enumerate(targets):rows.append(dict(term=names[j],units='percentage points',**interval(100*beta[j],100*np.sqrt(V[k,k]))))
    info.update(status='ESTIMATED',accounts=len(groups),target_covariance_pp2=10000*V);return info,rows
