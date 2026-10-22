"""Exact chooser-FE least squares and chooser-clustered curve contrasts.

All rows of a chooser must occur in the same input block. Sparse full-design
moments are shared across six models (two axes x three specifications).
Singletons are excluded from ALL comparative curves, including raw curves.
Unidentified contrasts are marked, never normalized into an apparent result.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.stats import t as student_t
from surface_model import controls, term_names

VERSION = '1.0.0'
AXES = ('gap', 'payoff', 'normalized')
SPECS = ('chooser_controls', 'chooser_controls_k20', 'chooser_controls_k50')
MONTHS = [f'{y}-{m:02}' for y in range(2023, 2026) for m in range(1, 13)
          if '2023-11' <= f'{y}-{m:02}' <= '2025-10']
SPEEDS = ['ultrabullet', 'bullet', 'blitz', 'rapid', 'classical']
CONTEXTS = [
    ('clearly_worse', 'Opponent clearly worse (≤ −300 cp)', None, -300, True),
    ('modestly_worse', 'Opponent modestly worse (−299 to −101 cp)', -300, -100, False),
    ('roughly_equal', 'Roughly equal (−100 to +100 cp)', -100, 100, True),
    ('better', 'Opponent better (+101 to +299 cp)', 100, 300, False),
    ('clearly_better', 'Opponent clearly better (≥ +300 cp)', 300, None, True),
    ('narrow_behind', 'Opponent behind [−350, −300) cp', -350, -300, False),
    ('narrow_equal', 'Approximately equal [0, +50) cp', 0, 50, False),
    ('narrow_ahead', 'Opponent ahead [+300, +350) cp', 300, 350, False),
]


def context_mask(d, key):
    if key == 'clearly_worse': return d <= -300
    if key == 'modestly_worse': return (d > -300) & (d < -100)
    if key == 'roughly_equal': return (d >= -100) & (d <= 100)
    if key == 'better': return (d > 100) & (d < 300)
    if key == 'clearly_better': return d >= 300
    _, _, lo, hi, _ = next(x for x in CONTEXTS if x[0] == key)
    return (d >= lo) & (d < hi)


def axis_definition(axis):
    if axis == 'gap':
        edges = np.arange(-625., 626., 50.)
        # Equal-rating reference is the centered [-25,25) bin.
    elif axis == 'payoff':
        # Merge the two old cells around zero into [-0.4,+0.4).
        edges = np.round(np.arange(-6., 6.01, .4), 8)
        edges = edges[edges != 0]
    elif axis == 'normalized':
        edges = np.round(np.arange(-.5, .501, .025), 8)
        edges = edges[edges != 0]
    else:
        raise ValueError(axis)
    labels = []
    bounds = [-np.inf, *edges, np.inf]
    for j, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        labels.append(dict(bin=j, low=None if not np.isfinite(lo) else float(lo),
                           high=None if not np.isfinite(hi) else float(hi),
                           mid=None if not np.isfinite(lo+hi) else float((lo+hi)/2),
                           display=bool(np.isfinite(lo+hi)), reference=bool(lo <= 0 < hi)))
    return edges, labels


def bin_axis(x, axis):
    edges, _ = axis_definition(axis)
    out = np.searchsorted(edges, x, side='right')
    # Retain the original payoff plot's closed last endpoint at +6.
    if axis in ('payoff', 'normalized'): out[x == edges[-1]] = len(edges)-1
    return out


def onehot(codes, levels):
    return sparse.csr_matrix((np.ones(len(codes)), (np.arange(len(codes)), codes)),
                             shape=(len(codes), levels))


def make_layout(edges):
    names, sections = [], {}
    def add(key, values):
        sections[key] = np.arange(len(names), len(names)+len(values), dtype=int)
        names.extend(values)
    for axis in AXES:
        add(axis, [f'{axis}:{x["bin"]}' for x in axis_definition(axis)[1]])
    add('continuous', term_names())
    add('month', [f'month:{x}' for x in MONTHS[1:]])
    add('speed', [f'speed:{x}' for x in SPEEDS[1:]])
    add('board', [f'board50:{i}' for i in range(1,26)])
    for key in ('k20', 'k50'):
        add(key, [f'{key}:{i}' for i in range(1, len(edges[key])+1)])
    add('logk', ['log_K'])
    return names, sections


def make_design(frame, edges):
    n = len(frame['y'])
    parts = [onehot(bin_axis(frame[a], a), len(axis_definition(a)[1])) for a in AXES]
    original = dict(ply_count=frame['ply'], chooser_pre_rd_v2=frame['crd'],
                    disconnected_pre_rd_v2=frame['drd'], chooser_pre_sigma_v2=frame['cvol'],
                    disconnected_pre_sigma_v2=frame['dvol'])
    parts.append(sparse.csr_matrix(controls(original)))
    for key, count in [('month', 24), ('speed', 5)]:
        parts.append(onehot(frame[key].astype(int), count)[:, 1:])
    board = np.searchsorted(np.arange(-600.,601.,50.), frame['board'], side='right')
    parts.append(onehot(board, 26)[:, 1:])
    for key in ('k20', 'k50'):
        codes = np.searchsorted(edges[key], frame['K'], side='left')
        parts.append(onehot(codes, len(edges[key])+1)[:, 1:])
    parts.append(sparse.csr_matrix(np.log(frame['K']).reshape(n, 1)))
    X = sparse.hstack(parts, format='csr')
    X.eliminate_zeros()
    return X


def groups(frame):
    user = frame['chooser']
    if len(user) == 0: raise ValueError('Empty chooser block')
    if (np.diff(user) < 0).any(): raise ValueError('Chooser rows are not sorted')
    starts = np.r_[True, user[1:] != user[:-1]]
    g = np.cumsum(starts)-1
    counts = np.bincount(g)
    A = sparse.csr_matrix((np.ones(len(user)), (g, np.arange(len(user)))), shape=(len(counts),len(user)))
    return g, counts, A


def nonsingletons(frame):
    g, n, _ = groups(frame)
    keep = n[g] >= 2
    return {k:v[keep] for k,v in frame.items()}


def iter_blocks(path, batch_rows=32768):
    """PyArrow stream with complete chooser clusters across record boundaries."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    tail = None
    last_user = None
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_rows, use_threads=False):
        table = pa.Table.from_batches([batch])
        if tail is not None: table = pa.concat_tables([tail, table])
        ids = table['chooser'].to_numpy()
        first_tail = np.searchsorted(ids, ids[-1], side='left')
        tail = table.slice(int(first_tail))
        if first_tail:
            block = table.slice(0,int(first_tail))
            vals = {name:block[name].to_numpy() for name in block.column_names}
            if last_user is not None and vals['chooser'][0] <= last_user:
                raise RuntimeError('Chooser cluster split across blocks')
            last_user = vals['chooser'][-1]
            yield vals
    if tail is not None and len(tail):
        vals = {name:tail[name].to_numpy() for name in tail.column_names}
        if last_user is not None and vals['chooser'][0] <= last_user:
            raise RuntimeError('Non-contiguous chooser cluster')
        yield vals


class Moments:
    def __init__(self, edges):
        self.edges = edges
        self.names, self.sections = make_layout(edges)
        p = len(self.names)
        self.S = np.zeros((p,p)); self.b = np.zeros(p)
        self.N = 0; self.G = 0; self.all_N = 0; self.all_G = 0
        self.all_events = 0; self.events = 0
        self.counts = {}
        for axis in AXES:
            J = len(self.sections[axis])
            self.counts[axis] = {k:np.zeros(J,dtype=np.int64) for k in
                                ('n','events','all_n','all_events','choosers','switching_choosers','direct_reference_choosers')}
            self.counts[axis]['month'] = np.zeros((J,24),dtype=np.int64)

    def add(self, original):
        self.all_N += len(original['y']); self.all_events += int(original['y'].sum())
        self.all_G += len(np.unique(original['chooser']))
        for axis in AXES:
            J = len(self.sections[axis]); codes=bin_axis(original[axis],axis)
            self.counts[axis]['all_n'] += np.bincount(codes,minlength=J)
            self.counts[axis]['all_events'] += np.bincount(codes,weights=original['y'],minlength=J).astype(np.int64)
        frame = nonsingletons(original)
        if not len(frame['y']): return
        X = make_design(frame,self.edges)
        g,n,A = groups(frame); y=frame['y'].astype(float)
        sums = A @ X
        centered_means = sparse.diags(1/np.sqrt(n)) @ sums
        self.S += (X.T@X - centered_means.T@centered_means).toarray()
        self.b += np.asarray(X.T@y).ravel() - np.asarray(sums.T@((A@y)/n)).ravel()
        self.N += len(y); self.G += len(n); self.events += int(y.sum())
        for axis in AXES:
            J = len(self.sections[axis]); codes = bin_axis(frame[axis],axis)
            out=self.counts[axis]
            out['n'] += np.bincount(codes,minlength=J)
            out['events'] += np.bincount(codes,weights=y,minlength=J).astype(np.int64)
            np.add.at(out['month'],(codes,frame['month'].astype(int)),1)
            exposure=(A@onehot(codes,J)).toarray()
            present=exposure>0
            changes=present.sum(axis=1)>1
            reference=next(x['bin'] for x in axis_definition(axis)[1] if x['reference'])
            out['choosers'] += present.sum(axis=0)
            out['switching_choosers'] += present[changes].sum(axis=0)
            out['direct_reference_choosers'] += present[present[:,reference]].sum(axis=0)

    def save(self,path):
        meta=dict(edges=self.edges,N=self.N,G=self.G,all_N=self.all_N,all_G=self.all_G,
                  events=self.events,all_events=self.all_events)
        arrays={f'{a}__{k}':v for a,c in self.counts.items() for k,v in c.items()}
        np.savez_compressed(path,S=self.S,b=self.b,metadata=np.array(json.dumps(meta)),**arrays)

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as z:
            meta=json.loads(str(z['metadata'])); obj=cls(meta.pop('edges'))
            for k,v in meta.items(): setattr(obj,k,v)
            obj.S=z['S'].copy();obj.b=z['b'].copy()
            for a,c in obj.counts.items():
                for k in c: c[k]=z[f'{a}__{k}'].copy()
        return obj


def solve(S,b,C):
    """Scaled eigensolve; tests each requested contrast's estimability."""
    diagonal=np.diag(S).copy()
    cutoff=max(float(diagonal.max(initial=0))*1e-13,1e-12)
    active=diagonal>cutoff
    scale=np.zeros(len(b));scale[active]=1/np.sqrt(diagonal[active])
    H=scale[:,None]*((S+S.T)/2)*scale[None,:]
    values,vectors=np.linalg.eigh(H)
    maximum=float(values.max(initial=0))
    if float(values.min(initial=0)) < -max(1e-8,maximum*1e-8):
        raise RuntimeError('Within-chooser Gram matrix is not positive semidefinite')
    keep=values>max(maximum*1e-10,1e-12)
    V=vectors[:,keep];rank=int(keep.sum())
    inverse=((V/values[keep])@V.T)*scale[:,None]*scale[None,:]
    beta=inverse@b
    # A zero-variance coefficient direction cannot identify a contrast.
    Cs=C*scale
    residual=Cs-(Cs@V)@V.T
    rel=np.linalg.norm(residual,axis=1)/np.maximum(np.linalg.norm(Cs,axis=1),1e-30)
    identified=(rel<1e-6)&(np.linalg.norm(C[:,~active],axis=1)<1e-12)
    identified[np.linalg.norm(C,axis=1)==0]=True
    return dict(beta=beta,bread=inverse,rank=rank,identified=identified,
                projection_error=rel,condition_number=maximum/values[keep][0] if rank else None)


def fit_models(moments):
    models={}
    for axis in AXES:
        J=len(moments.sections[axis]); reference=next(x['bin'] for x in axis_definition(axis)[1] if x['reference'])
        for spec in SPECS:
            keys=[axis,'continuous','month','speed','board']
            if spec.endswith('k20'):keys+=['k20','logk']
            if spec.endswith('k50'):keys+=['k50','logk']
            indices=np.concatenate([moments.sections[k] for k in keys])
            C=np.zeros((J,len(indices)));C[np.arange(J),np.arange(J)]=1;C[:,reference]-=1
            solution=solve(moments.S[np.ix_(indices,indices)],moments.b[indices],C)
            solution.update(axis=axis,spec=spec,indices=indices,C=C,
                            estimates=C@solution['beta'],meat=np.zeros((J,J)),score_sum=np.zeros(J))
            solution['projection']=solution['bread']@C.T
            models[axis+'__'+spec]=solution
        counts=moments.counts[axis]
        rates=np.divide(counts['events'],counts['n'],out=np.zeros(J),where=counts['n']>0)
        models[axis+'__raw']=dict(axis=axis,spec='raw',rates=rates,reference=reference,
            estimates=rates-rates[reference],identified=(counts['n']>0)&(counts['n'][reference]>0),
            rank=int((counts['n']>0).sum()),n_per_bin=counts['n'].astype(float),
            meat=np.zeros((J,J)),score_sum=np.zeros(J))
    return models


def score_block(original,edges,models):
    frame=nonsingletons(original)
    if not len(frame['y']):return
    X=make_design(frame,edges);g,n,A=groups(frame);y=frame['y'].astype(float)
    for model in models.values():
        axis=model['axis']
        if model['spec']=='raw':
            codes=bin_axis(frame[axis],axis);J=len(model['rates'])
            count=(A@onehot(codes,J)).toarray()
            events=(A@sparse.csr_matrix((y,(np.arange(len(y)),codes)),shape=(len(y),J))).toarray()
            scores=np.divide(events-count*model['rates'],model['n_per_bin'],
                             out=np.zeros_like(events),where=model['n_per_bin']>0)
            scores-=scores[:,[model['reference']]]
        else:
            xx=X[:,model['indices']]
            e=y-np.asarray(xx@model['beta']).ravel()
            e-=np.asarray(A@e).ravel()[g]/n[g]
            # Sum X' residual within each chooser, then project to curve contrasts.
            cluster_scores=A@xx.multiply(e[:,None])
            scores=np.asarray(cluster_scores@model['projection'])
        model['meat']+=scores.T@scores
        model['score_sum']+=scores.sum(axis=0)


def finalize_models(moments,models,context,min_n=500,min_choosers=50,min_months=6):
    rows=[];arrays={};diagnostics=[];shapes=[]
    for key,model in models.items():
        axis,spec=model['axis'],model['spec'];G,N=moments.G,moments.N
        denominator=N-model['rank'] if spec=='raw' else N-G-model['rank']
        correction=G/(G-1)*(N-1)/denominator if G>1 and denominator>0 else None
        cov=model['meat']*correction if correction is not None else np.full_like(model['meat'],np.nan)
        critical=float(student_t.ppf(.975,G-1)) if G>1 else np.nan
        estimates=model['estimates']
        labels=axis_definition(axis)[1];counts=moments.counts[axis]
        supported=np.zeros(len(labels),dtype=bool)
        for j,item in enumerate(labels):
            se=float(np.sqrt(max(0,cov[j,j]))) if correction is not None else None
            valid=bool(model['identified'][j] and correction is not None)
            months=int(np.count_nonzero(counts['month'][j]))
            supported[j]=bool(item['display'] and valid and counts['n'][j]>=min_n and
                              counts['switching_choosers'][j]>=min_choosers and months>=min_months)
            est=float(estimates[j]*100) if valid else None
            rows.append(dict(context=context,axis=axis,specification=spec,**item,
                n=int(counts['n'][j]),events=int(counts['events'][j]),
                all_n=int(counts['all_n'][j]),all_events=int(counts['all_events'][j]),
                raw_rate_percent=float(100*counts['events'][j]/counts['n'][j]) if counts['n'][j] else None,
                choosers=int(counts['choosers'][j]),switching_choosers=int(counts['switching_choosers'][j]),
                direct_reference_choosers=int(counts['direct_reference_choosers'][j]),
                months=months,estimable=valid,display_supported=bool(supported[j]),
                estimate_pp=est,cluster_se_pp=100*se if valid else None,
                ci95_low_pp=est-100*critical*se if valid else None,
                ci95_high_pp=est+100*critical*se if valid else None,
                sample_n=N,chooser_clusters=G,within_design_rank=int(model['rank']),CR1_factor=correction))
        arrays[key+'__estimates']=estimates;arrays[key+'__covariance']=cov
        arrays[key+'__identified']=model['identified']
        diagnostics.append(dict(context=context,axis=axis,specification=spec,N=N,G=G,
            singleton_rows_dropped=moments.all_N-N,all_rows=moments.all_N,all_choosers=moments.all_G,
            design_rank=int(model['rank']),CR1_factor=correction,
            maximum_abs_curve_score_sum=float(np.max(np.abs(model['score_sum']))),
            identified_contrasts=int(model['identified'].sum()),condition_number=model.get('condition_number'),
            projection_errors=model.get('projection_error',np.zeros(len(labels))).tolist()))
        mids=np.array([x['mid'] if x['mid'] is not None else np.nan for x in labels])
        ref=next(x['bin'] for x in labels if x['reference'])
        masks = ({'left':(mids>=-600)&(mids<=-300),'shoulder':(mids>=-200)&(mids<=-50),
                  'right':(mids>=300)&(mids<=600)} if axis=='gap' else
                 {'left':(mids>=-6)&(mids<=-3),'shoulder':(mids>=-2.4)&(mids<=-1.2),
                  'right':(mids>=3)&(mids<=6)})
        weights={}
        for name,mask in masks.items():
            # Freeze bin membership; never select significant/extreme cells.
            w=mask.astype(float)*counts['n']
            weights[name]=w/w.sum() if w.sum() else None
        weights['reference']=np.eye(len(labels))[ref]
        for a,b in [('left','shoulder'),('right','shoulder'),('left','reference'),('right','reference')]:
            wa,wb=weights[a],weights[b]
            valid=wa is not None and wb is not None and correction is not None
            if valid:
                w=wa-wb
                used=np.abs(w)>0
                valid=bool(model['identified'][used].all() and supported[used].all())
            r=dict(context=context,axis=axis,specification=spec,contrast=a+'_minus_'+b,
                   status='estimated' if valid else 'insufficient_supported_bins',
                   exploratory=True,weighting='fixed opportunity weights from common estimation sample',
                   estimate_pp=None,cluster_se_pp=None,ci95_low_pp=None,ci95_high_pp=None,p_two_sided=None)
            if valid:
                value=float(w@estimates);variance=float(w@cov@w);se=np.sqrt(max(0,variance))
                p=float(2*student_t.sf(abs(value/se),G-1)) if se else (1. if value==0 else 0.)
                r.update(estimate_pp=value*100,cluster_se_pp=se*100,ci95_low_pp=100*(value-critical*se),
                         ci95_high_pp=100*(value+critical*se),p_two_sided=p)
            shapes.append(r)
    return rows,shapes,diagnostics,arrays
