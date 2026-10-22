"""Streamed exact within-unit WLS, clustered by chooser, with estimability checks."""
from __future__ import annotations
import csv
import json
import time
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import stats

BOARD = ['clearly_worse','modestly_worse','roughly_equal','better','clearly_better']
PLY = ['0_4','5_6','7_8','9_10','11_20','21_40','41_80','81_plus']
CLOCK = ['log_cclock','log_dclock','cclock_missing','dclock_missing']
CONTINUOUS = ['gap','premium','crd','drd','cvol','dvol','rating']
KNOTS = {
 'gap': np.array([-400,-200,-100,0,100,200,400])/100.,
 'premium': np.log1p([1,3,10,30,100]),
 'crd': np.log1p([50,100,200]), 'drd': np.log1p([50,100,200]),
 'cvol': [], 'dvol': [], 'rating': [0.]}


def log(s):
    print(time.strftime('[%Y-%m-%d %H:%M:%S] ')+s,flush=True)


def csv_write(path, rows, fields=None):
    rows=list(rows)
    pq.write_table(pa.Table.from_pylist(rows),Path(path).with_suffix('.parquet'),compression='zstd')
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]))
        w.writeheader();w.writerows(rows)


def symmetric_parquet(path,values,terms,value_name):
    """Lossless upper triangle; reconstruct the lower triangle by symmetry."""
    i,j=np.triu_indices(len(terms));labels=np.asarray(terms)
    pq.write_table(pa.table({'term_i':labels[i],'term_j':labels[j],value_name:values[i,j]}),path,compression='zstd')


def json_write(path, obj):
    Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')


def blocks(path, batch_size=65536):
    tail=None;last=None
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size,use_threads=False):
        current=pa.Table.from_batches([batch])
        if tail is not None: current=pa.concat_tables([tail,current])
        ids=current['chooser'].to_numpy()
        if np.any(ids[1:]<ids[:-1]) or (last is not None and ids[0]<=last):
            raise ValueError('Cache must be sorted by chooser and clusters must not recur')
        cut=int(np.searchsorted(ids,ids[-1],side='left'))
        tail=current.slice(cut)
        if cut:
            out=current.slice(0,cut)
            yield {n:out[n].to_numpy() for n in out.column_names}
            last=ids[cut-1]
    if tail is not None and len(tail):
        yield {n:tail[n].to_numpy() for n in tail.column_names}


def layout(meta):
    names=[];parts={}
    def add(key, terms):
        parts[key]=list(range(len(names),len(names)+len(terms)))
        names.extend(terms)
    add('cells',[f'cell_b{b}_p{p}' for b in range(5) for p in range(8) if b*8+p!=0])
    add('calendar',[f'calendar_{i}' for i in range(1,len(meta['calendar']))])
    add('clocks',CLOCK)
    continuous=[]
    for c in CONTINUOUS:
        continuous += [c+'_linear']+[c+f'_hinge_{j}' for j in range(len(KNOTS[c]))]
    add('economic',continuous)
    add('early',[f'early_ply_{p}' for p in meta['early_levels']])
    add('additive',[f'board_{i}' for i in range(1,5)]+[f'ply_{i}' for i in range(1,8)])
    add('patron',[f'patron_cell_b{b}_p{p}' for b in range(5) for p in range(8) if b*8+p!=0])
    return names,parts


def matrix(d,meta):
    cell=d['board']*8+d['ply']
    n=len(cell)
    x=[cell==i for i in range(1,40)]
    x += [d['calendar']==i for i in range(1,len(meta['calendar']))]
    x += [d[c] for c in CLOCK]
    values={'gap':d['gap']/100.,'premium':np.log1p(d['premium']),
            'crd':np.log1p(d['crd']),'drd':np.log1p(d['drd']),
            'cvol':np.log(d['cvol']),'dvol':np.log(d['dvol']),
            'rating':(d['rating']-1500.)/1000.}
    for name in CONTINUOUS:
        v=values[name];x.append(v)
        x.extend(np.maximum(v-k,0) for k in KNOTS[name])
    x += [d['exact_ply']==i for i in meta['early_levels']]
    x += [d['board']==i for i in range(1,5)]+[d['ply']==i for i in range(1,8)]
    x += [(cell==i)&(d['patron']==1) for i in range(1,40)]
    X=np.empty((n,len(x)),dtype=np.float64)
    for j,a in enumerate(x):X[:,j]=a
    if not np.isfinite(X).all():raise ValueError('Nonfinite design')
    return X


def starts_counts(ids):
    starts=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1]
    return starts,np.diff(np.r_[starts,len(ids)])


def transformed(d,X,fe='chooser',weight='opportunity'):
    # All rows of each chooser arrive together, even when FE units are smaller.
    if fe=='chooser_speed':
        order=np.lexsort((d['speed'],d['chooser']))
        d={k:v[order] for k,v in d.items()};X=X[order]
    elif fe!='chooser':raise ValueError(fe)
    cs,cn=starts_counts(d['chooser'])
    if fe=='chooser_speed':
        boundary=(d['chooser'][1:]!=d['chooser'][:-1]) | (d['speed'][1:]!=d['speed'][:-1])
        us=np.r_[0,np.flatnonzero(boundary)+1];un=np.diff(np.r_[us,len(X)])
    else:us,un=cs,cn
    Z=np.ascontiguousarray(np.column_stack([d['y'],X]),dtype=np.float64)
    Z-=np.repeat(np.add.reduceat(Z,us,axis=0)/un[:,None],un,axis=0)
    if weight=='inverse_count':w=np.repeat(1./cn,cn)
    elif weight=='opportunity':w=np.ones(len(X))
    else:raise ValueError(weight)
    stats_={'rows':len(X),'choosers':len(cn),'fe_units':len(un),
      'singleton_choosers':int((cn==1).sum()),'singleton_fe_units':int((un==1).sum()),
      'rows_in_nonsingleton_fe_units':int(un[un>1].sum()),
      'zero_grant_choosers':int((np.add.reduceat(d['y'],cs)==0).sum()),
      'grants':int(d['y'].sum()),'patron_choosers':int((d['patron'][cs]==1).sum())}
    return Z,w,cs,stats_


def solve(S,b):
    diag=np.diag(S).copy()
    if np.min(diag)<-1e-8:raise ValueError('Negative Gram diagonal')
    active=diag>1e-12
    scale=np.zeros(len(b));scale[active]=1/np.sqrt(diag[active])
    H=scale[:,None]*((S+S.T)/2)*scale[None,:]
    eig,V=np.linalg.eigh(H)
    maximum=float(eig.max(initial=0))
    if eig.min(initial=0)<-max(1e-8,maximum*1e-8):raise ValueError('Gram not PSD')
    keep=eig>max(maximum*1e-10,1e-12)
    if not keep.any():raise ValueError('No within-unit identifying variation')
    basis=V[:,keep]
    bread=((basis/eig[keep])@basis.T)*scale[:,None]*scale[None,:]
    beta=bread@b
    err=float(np.max(np.abs(S@beta-b))/max(1.,np.max(np.abs(b))))
    if err>1e-7:raise ValueError(f'Normal-equation residual {err}')
    return dict(beta=beta,bread=bread,basis=basis,scale=scale,active=active,
                rank=int(keep.sum()),condition=float(maximum/eig[keep][0]),normal_error=err)


def estimable(f,C):
    C=np.atleast_2d(C);cs=C*f['scale']
    residual=cs-(cs@f['basis'])@f['basis'].T
    rel=np.linalg.norm(residual,axis=1)/np.maximum(np.linalg.norm(cs,axis=1),1e-30)
    ok=(rel<1e-6)&(np.linalg.norm(C[:,~f['active']],axis=1)<1e-12)
    ok[np.linalg.norm(C,axis=1)==0]=True
    return ok,rel


def model_specs(parts):
    def ids(*keys):return np.array(sum([parts[k] for k in keys],[]),dtype=int)
    full=ids('cells','calendar','clocks','economic')
    return {
      'states':[
        ('A_additive',ids('additive','calendar','clocks','economic')),
        ('S1_state_stage',ids('cells','calendar')),
        ('S2_plus_clocks',ids('cells','calendar','clocks')),
        ('S3_full',full),
        ('S4_exact_early_ply',ids('cells','calendar','clocks','economic','early'))],
      'exact_ply_recovery':[('S4_exact_early_ply',ids('cells','calendar','clocks','economic','early'))],
      'weighting':[('W_inverse_account_count',full)],
      'speed_fe':[('R_chooser_speed_FE',full)],
      'patron':[('P_patron_state_stage',ids('cells','calendar','clocks','economic','patron'))]}


def selected(d,group):
    if group=='patron':
        mask=d['patron']>=0
        return {k:v[mask] for k,v in d.items()}
    return d


def fit_group(cache,meta,out,group,batch_size=65536):
    out=Path(out);out.mkdir(exist_ok=True,parents=True)
    names,parts=layout(meta);specs=model_specs(parts)[group]
    union=np.unique(np.concatenate([i for _,i in specs]))
    local={int(v):i for i,v in enumerate(union)}
    specs=[(name,np.array([local[int(j)] for j in ix])) for name,ix in specs]
    names=[names[j] for j in union]
    S=np.zeros((len(union)+1,len(union)+1));counts={};variation=np.zeros(len(union),dtype=np.int64)
    fe='chooser_speed' if group=='speed_fe' else 'chooser'
    weight='inverse_count' if group=='weighting' else 'opportunity'
    last=time.monotonic()
    for original in blocks(cache,batch_size):
        d=selected(original,group)
        if not len(d['y']):continue
        X=matrix(d,meta)[:,union]
        Z,w,cs,c=transformed(d,X,fe,weight)
        Q=Z*np.sqrt(w)[:,None];S+=Q.T@Q
        for k,v in c.items():counts[k]=counts.get(k,0)+v
        ss=np.add.reduceat(Z[:,1:]**2,cs,axis=0)
        variation+=(ss>1e-14).sum(axis=0)
        if time.monotonic()-last>25:
            log(f'{group} moments: {counts["rows"]:,} rows');last=time.monotonic()
    if counts.get('choosers',0)<2:raise ValueError(f'{group}: insufficient chooser support')
    np.savez_compressed(out/'moments.npz',S=S,terms=np.array(names),variation=variation,
                        counts=np.array(json.dumps(counts)))
    fits=[]
    for name,ix in specs:
        fit=solve(S[np.ix_(ix+1,ix+1)],S[ix+1,0])
        fit.update(name=name,ix=ix,terms=[names[j] for j in ix],
                   meat=np.zeros((len(ix),len(ix))),sse=0.,score_sum=np.zeros(len(ix)))
        fits.append(fit)
    done=0
    for original in blocks(cache,batch_size):
        d=selected(original,group)
        if not len(d['y']):continue
        X=matrix(d,meta)[:,union]
        Z,w,cs,c=transformed(d,X,fe,weight)
        for f in fits:
            x=Z[:,f['ix']+1];e=Z[:,0]-x@f['beta']
            score=np.add.reduceat(x*(w*e)[:,None],cs,axis=0)
            f['meat']+=score.T@score;f['score_sum']+=score.sum(axis=0)
            f['sse']+=float(np.sum(w*e**2))
        done+=len(Z)
        if time.monotonic()-last>25:
            log(f'{group} clustered scores: {done:,} rows');last=time.monotonic()
    for f in fits:
        f['cov']=counts['choosers']/(counts['choosers']-1)*f['bread']@f['meat']@f['bread']
        f['cov']=(f['cov']+f['cov'].T)/2
        f['within_r2']=None if S[0,0]<=0 else float(1-f['sse']/S[0,0])
        f['score_error']=float(np.max(np.abs(f['score_sum']))/max(1.,np.max(np.abs(S[1:,0]))))
        if f['score_error']>1e-7:raise ValueError('Cluster-score conservation failed')
        f['counts']=counts;f['fe']=fe;f['weight']=weight
        np.savez_compressed(out/(f['name']+'_covariance.npz'),cov_pp2=f['cov']*10000,
                            beta_pp=f['beta']*100,terms=np.array(f['terms']))
    csv_write(out/'within_variation_support.csv',[dict(term=t,choosers=int(n)) for t,n in zip(names,variation)])
    return fits


def cell_vector(f,b,p,patron=False):
    v=np.zeros(len(f['terms']))
    # Additive summary uses separate board and stage coefficients.
    if f['name']=='A_additive':
        if b:v[f['terms'].index(f'board_{b}')]=1
        if p:v[f['terms'].index(f'ply_{p}')]=1
    elif b*8+p:
        term=('patron_' if patron else '')+f'cell_b{b}_p{p}'
        v[f['terms'].index(term)]=1
    return v


def contrast_definitions(f,meta):
    result=[]
    def append(label,C,family):result.append(dict(label=label,C=C,family=family))
    for kind in ([False,True] if f['name'].startswith('P_') else [False]):
        prefix='patron_minus_nonpatron_' if kind else ('nonpatron_' if f['name'].startswith('P_') else '')
        comp=[]
        for p in range(8):
            base=cell_vector(f,0,p,kind)
            for b in range(1,5):
                append(prefix+BOARD[b]+'_vs_losing_at_'+PLY[p],cell_vector(f,b,p,kind)-base,prefix+'board_by_stage')
            c=sum(meta['competitive_weights'][b-2]*cell_vector(f,b,p,kind) for b in range(2,5))-base
            comp.append(c)
            append(prefix+'competitive_vs_losing_at_'+PLY[p],c,prefix+'competitive_by_stage')
            append(prefix+'equal_vs_better_at_'+PLY[p],cell_vector(f,2,p,kind)-cell_vector(f,3,p,kind),prefix+'equal_vs_better')
        append(prefix+'competitive_vs_losing_standardized',sum(meta['stage_weights'][p]*comp[p] for p in range(8)),prefix+'standardized')
        for b in range(5):
            for p in range(1,8):
                append(prefix+BOARD[b]+'_'+PLY[p]+'_vs_0_4',cell_vector(f,b,p,kind)-cell_vector(f,b,0,kind),prefix+'stage_within_board')
    return result


def summarize_contrast(f,C):
    ok,err=estimable(f,C)
    if not ok[0]:return dict(estimable=False,estimate_pp=None,se_pp=None,ci_low_pp=None,ci_high_pp=None,p_value=None,projection_error=float(err[0]))
    b=float(C@f['beta']*100);var=float(C@f['cov']@C*10000)
    if var < -1e-8:raise ValueError('Negative contrast variance')
    se=float(np.sqrt(max(var,0)))
    crit=float(stats.t.ppf(.975,f['counts']['choosers']-1))
    p=float(2*stats.t.sf(abs(b/se),f['counts']['choosers']-1)) if se>0 else None
    return dict(estimable=True,estimate_pp=b,se_pp=se,ci_low_pp=b-crit*se,ci_high_pp=b+crit*se,p_value=p,projection_error=float(err[0]))


def joint_test(f,label,C):
    C=np.atleast_2d(C);ok,_=estimable(f,C)
    if not np.all(ok):return dict(model=f['name'],test=label,estimable=False,df=None,wald=None,p_value=None)
    e=C@f['beta'];V=C@f['cov']@C.T
    eig,U=np.linalg.eigh((V+V.T)/2);keep=eig>max(eig.max(initial=0)*1e-10,1e-18)
    rank=int(keep.sum())
    if not rank:return dict(model=f['name'],test=label,estimable=False,df=0,wald=None,p_value=None)
    # Zero covariance directions must not conceal a nonzero null violation.
    if np.linalg.norm(e-U[:,keep]@(U[:,keep].T@e))>1e-6*max(1e-12,np.linalg.norm(e)):
        return dict(model=f['name'],test=label,estimable=False,df=rank,wald=None,p_value=None)
    w=float(np.sum((U[:,keep].T@e)**2/eig[keep]))
    return dict(model=f['name'],test=label,estimable=True,df=rank,wald=w,p_value=float(stats.chi2.sf(w,rank)))


def export(fits,meta,out):
    out=Path(out);coefs=[];contrasts=[];tests=[];receipts=[]
    for f in fits:
        for i,t in enumerate(f['terms']):
            C=np.eye(len(f['terms']))[i]
            coefs.append(dict(model=f['name'],term=t,**summarize_contrast(f,C)))
        defs=contrast_definitions(f,meta)
        for d in defs:contrasts.append(dict(model=f['name'],contrast=d['label'],family=d['family'],**summarize_contrast(f,d['C'])))
        base_prefix='nonpatron_' if f['name'].startswith('P_') else ''
        board=np.array([d['C'] for d in defs if d['family']==base_prefix+'board_by_stage'])
        stage=np.array([d['C'] for d in defs if d['family']==base_prefix+'stage_within_board'])
        tests += [joint_test(f,'all_board_differences',board),joint_test(f,'all_stage_differences',stage)]
        if f['name']!='A_additive':
            interaction=[]
            for b in range(1,5):
                for p in range(1,8):
                    interaction.append(cell_vector(f,b,p)-cell_vector(f,0,p)-cell_vector(f,b,0)+cell_vector(f,0,0))
            tests.append(joint_test(f,'board_by_stage_nonadditivity',np.array(interaction)))
        if f['name'].startswith('P_'):
            C=np.array([d['C'] for d in defs if d['family']=='patron_minus_nonpatron_board_by_stage'])
            tests.append(joint_test(f,'patron_differential_board_selectivity',C))
        receipts.append(dict(model=f['name'],**f['counts'],fe=f['fe'],weights=f['weight'],rank=f['rank'],columns=len(f['terms']),
            condition=f['condition'],normal_equation_error=f['normal_error'],score_error=f['score_error'],within_r2=f['within_r2']))
    csv_write(out/'coefficients.csv',coefs);csv_write(out/'contrasts.csv',contrasts)
    csv_write(out/'joint_tests.csv',tests);csv_write(out/'model_receipts.csv',receipts)
    primary=['competitive_vs_losing_standardized','competitive_vs_losing_at_11_20','competitive_vs_losing_at_21_40',
             'competitive_vs_losing_at_41_80','roughly_equal_11_20_vs_0_4','roughly_equal_21_40_vs_0_4','roughly_equal_41_80_vs_0_4']
    if any(f['name'].startswith('P_') for f in fits):primary=['patron_minus_nonpatron_'+x for x in primary]
    labels=['Competitive vs. losing: standardized', 'Competitive vs. losing: plies 11--20',
            'Competitive vs. losing: plies 21--40','Competitive vs. losing: plies 41--80',
            'Equal: plies 11--20 vs. 0--4','Equal: plies 21--40 vs. 0--4','Equal: plies 41--80 vs. 0--4']
    columns=[f['name'].split('_')[0] for f in fits]
    table=['| Contrast | '+' | '.join(columns)+' |','|---|'+'---:|'*len(fits)]
    tex=[r'\begin{tabular}{l'+'r'*len(fits)+'}',r'\toprule','Contrast & '+' & '.join(columns)+r' \\',r'\midrule']
    for label in primary:
        values=[]
        for f in fits:
            r=next(r for r in contrasts if r['model']==f['name'] and r['contrast']==label)
            values.append(f"{r['estimate_pp']:.3f} ({r['se_pp']:.3f})" if r['estimable'] else 'Not identified')
        display=labels[primary.index(label)]
        table.append('| '+display+' | '+' | '.join(values)+' |')
        tex.append(display+' & '+' & '.join(values)+r' \\')
    tex += [r'\bottomrule',r'\end{tabular}']
    (out/'TABLE.md').write_text('\n'.join(table)+'\n\nDifferences and chooser-clustered SEs in percentage points. Pointwise intervals. Unidentified contrasts remain blank in CSV.\n'+
        ('Patron table: differences in within-chooser contrasts between Patrons and non-Patrons in the selected August profile sample.\n' if any(f['name'].startswith('P_') for f in fits) else '')+
        '\n'+ '\n'.join(f"{c}: {f['name']}" for c,f in zip(columns,fits))+'\n')
    (out/'TABLE.tex').write_text('\n'.join(tex)+'\n')
    return receipts
