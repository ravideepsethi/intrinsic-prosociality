"""Chooser-by-board-state absorption with covariance clustered by chooser.

Complete chooser histories must stay in one input block and one worker shard.
Neither covariance clustering nor its finite-sample G uses the absorbed units.
"""
from __future__ import annotations
import json
import numpy as np
from scipy import sparse
from scipy.stats import t as student_t, f as f_distribution
from fe_engine import (make_layout as base_layout,make_design as base_design,
                       groups,onehot,bin_axis,axis_definition,solve,AXES)

VERSION='1.0.0'
STATES=('roughly_equal','better','clearly_better')
SPECS=('chooser_state_controls','chooser_state_controls_k20','chooser_state_controls_k50')
INTERACTED='chooser_state_controls_k20_interacted'

def states(board):
    if not np.isfinite(board).all() or (board < -100).any():
        raise ValueError('Pooled estimator only accepts competitive positions, evaluation >= -100')
    return np.where(board<=100,0,np.where(board<300,1,2)).astype(int)

def absorption(frame):
    g,gn,B=groups(frame)
    state=states(frame['board'])
    codes=g*3+state
    unique,u=np.unique(codes,return_inverse=True)
    n=np.bincount(u)
    A=onehot(u,len(n)).T.tocsr()
    chooser_unit=sparse.csr_matrix((np.ones(len(n)),(unique//3,np.arange(len(n)))),shape=(len(gn),len(n)))
    return dict(g=g,G=len(gn),B=B,u=u,H=len(n),n=n,A=A,state=state,
                unit_state=unique%3,chooser_unit=chooser_unit)

def retain_units(frame):
    a=absorption(frame)
    keep=a['n'][a['u']]>=2
    return {k:v[keep] for k,v in frame.items()}

def within_crossproducts(X,y,a):
    """Sparse FE moments, with stable handling of near-constant columns.

    Subtracting two large sums of squares can give a constant nuisance column
    a small positive variance. Recenter candidate columns directly before
    rank determination; this matters when K and RD are narrowly restricted.
    """
    sums=a['A']@X;center=sparse.diags(1/np.sqrt(a['n']))@sums
    raw=(X.T@X).toarray();S=raw-(center.T@center).toarray()
    b=np.asarray(X.T@y).ravel()-np.asarray(sums.T@((a['A']@y)/a['n'])).ravel()
    candidates=np.flatnonzero(np.abs(np.diag(S))<=1e-10*np.maximum(1,np.diag(raw)))
    if len(candidates):
        Z=X[:,candidates].toarray()-sums[:,candidates].toarray()[a['u']]/a['n'][a['u'],None]
        variance=np.sum(Z*Z,axis=0)
        zero=variance<=1e-20*np.maximum(1,np.diag(raw)[candidates])
        Z[:,zero]=0
        cross=np.asarray(X.T@Z)
        S[:,candidates]=cross;S[candidates,:]=cross.T
        S[np.ix_(candidates,candidates)]=Z.T@Z
        b[candidates]=Z.T@y
    return (S+S.T)/2,b

def layout(edges):
    names,sections=base_layout(edges)
    for axis in AXES:
        J=len(axis_definition(axis)[1]);key=axis+'_by_state'
        sections[key]=np.arange(len(names),len(names)+3*J)
        names += [f'{axis}:{STATES[s]}:{j}' for s in range(3) for j in range(J)]
    return names,sections

def design(frame,edges):
    state=states(frame['board'])
    parts=[base_design(frame,edges)]
    for axis in AXES:
        J=len(axis_definition(axis)[1])
        parts.append(onehot(state*J+bin_axis(frame[axis],axis),3*J))
    return sparse.hstack(parts,format='csr')

class PooledMoments:
    def __init__(self,edges):
        self.edges=edges;self.names,self.sections=layout(edges)
        P=len(self.names);self.S=np.zeros((P,P));self.b=np.zeros(P)
        self.N=self.G=self.H=self.events=0
        self.all_N=self.all_G=self.all_events=0
        self.state_N=np.zeros(3,dtype=np.int64);self.state_H=np.zeros(3,dtype=np.int64)
        self.state_events=np.zeros(3,dtype=np.int64)
        self.all_state_N=np.zeros(3,dtype=np.int64);self.all_state_events=np.zeros(3,dtype=np.int64)
        self.counts={}
        for axis in AXES:
            J=len(axis_definition(axis)[1])
            self.counts[axis]={key:np.zeros((4,J),dtype=np.int64) for key in
              ('n','events','all_n','all_events','choosers','switching_choosers','direct_reference_choosers')}
            self.counts[axis]['month']=np.zeros((4,J,24),dtype=np.int64)

    def add(self,original):
        st=states(original['board']);y0=original['y']
        self.all_N+=len(y0);self.all_G+=len(np.unique(original['chooser']));self.all_events+=int(y0.sum())
        self.all_state_N+=np.bincount(st,minlength=3)
        self.all_state_events+=np.bincount(st,weights=y0,minlength=3).astype(np.int64)
        for axis in AXES:
            J=len(axis_definition(axis)[1]);code=bin_axis(original[axis],axis);out=self.counts[axis]
            for row,mask in [(0,np.ones(len(st),dtype=bool))]+[(s+1,st==s) for s in range(3)]:
                out['all_n'][row]+=np.bincount(code[mask],minlength=J)
                out['all_events'][row]+=np.bincount(code[mask],weights=y0[mask],minlength=J).astype(np.int64)
        frame=retain_units(original)
        if not len(frame['y']):return
        a=absorption(frame);X=design(frame,self.edges);y=frame['y'].astype(float)
        S,b=within_crossproducts(X,y,a)
        self.S+=S;self.b+=b
        self.N+=len(y);self.G+=a['G'];self.H+=a['H'];self.events+=int(y.sum())
        self.state_N+=np.bincount(a['state'],minlength=3)
        self.state_H+=np.bincount(a['unit_state'],minlength=3)
        self.state_events+=np.bincount(a['state'],weights=y,minlength=3).astype(np.int64)
        for axis in AXES:
            J=len(axis_definition(axis)[1]);code=bin_axis(frame[axis],axis);out=self.counts[axis]
            ref=next(x['bin'] for x in axis_definition(axis)[1] if x['reference'])
            present=(a['A']@onehot(code,J)).toarray()>0
            changes=present.sum(axis=1)>1
            switch=present&changes[:,None]
            direct=present&present[:,[ref]]
            for row,mask in [(0,np.ones(len(y),dtype=bool))]+[(s+1,a['state']==s) for s in range(3)]:
                out['n'][row]+=np.bincount(code[mask],minlength=J)
                out['events'][row]+=np.bincount(code[mask],weights=y[mask],minlength=J).astype(np.int64)
                np.add.at(out['month'][row],(code[mask],frame['month'][mask].astype(int)),1)
                for key,mat in [('choosers',present),('switching_choosers',switch),('direct_reference_choosers',direct)]:
                    if row==0:
                        # Count accounts once even when they contribute several absorbed units.
                        out[key][row]+=((a['chooser_unit']@mat.astype(np.int8))>0).sum(axis=0)
                    else:
                        out[key][row]+=mat[a['unit_state']==row-1].sum(axis=0)

    def merge(self,other):
        if self.edges!=other.edges:raise ValueError('Different K cutpoints across shards')
        self.S+=other.S;self.b+=other.b
        for k in ('N','G','H','events','all_N','all_G','all_events','state_N','state_H','state_events','all_state_N','all_state_events'):
            setattr(self,k,getattr(self,k)+getattr(other,k))
        for axis,c in self.counts.items():
            for k in c:c[k]+=other.counts[axis][k]

    def save(self,path):
        meta={k:int(getattr(self,k)) for k in ('N','G','H','events','all_N','all_G','all_events')}
        meta['edges']=self.edges
        arrays={k:getattr(self,k) for k in ('S','b','state_N','state_H','state_events','all_state_N','all_state_events')}
        arrays.update({axis+'__'+k:v for axis,c in self.counts.items() for k,v in c.items()})
        np.savez_compressed(path,metadata=np.array(json.dumps(meta)),**arrays)

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as z:
            meta=json.loads(str(z['metadata']));obj=cls(meta.pop('edges'))
            for k,v in meta.items():setattr(obj,k,v)
            for k in ('S','b','state_N','state_H','state_events','all_state_N','all_state_events'):setattr(obj,k,z[k].copy())
            for axis,c in obj.counts.items():
                for k in c:c[k]=z[axis+'__'+k].copy()
        return obj

def fit_models(m, interaction=True):
    models={}
    for axis in AXES:
        J=len(axis_definition(axis)[1]);ref=next(x['bin'] for x in axis_definition(axis)[1] if x['reference'])
        for spec in (('chooser_state_controls_k20', INTERACTED) if interaction else ('chooser_state_controls_k20',)):
            interaction=spec==INTERACTED
            keys=[axis+'_by_state' if interaction else axis,'continuous','month','speed','board']
            if 'k20' in spec:keys+=['k20','logk']
            if 'k50' in spec:keys+=['k50','logk']
            indices=np.concatenate([m.sections[k] for k in keys]);curves=3*J if interaction else J
            C=np.zeros((curves,len(indices)))
            for s in range(3 if interaction else 1):
                C[s*J+np.arange(J),s*J+np.arange(J)]=1
                C[s*J:((s+1)*J),s*J+ref]-=1
            model=solve(m.S[np.ix_(indices,indices)],m.b[indices],C)
            model.update(axis=axis,spec=spec,indices=indices,C=C,reference=ref,interacted=interaction,
              estimates=C@model['beta'],projection=model['bread']@C.T,
              meat=np.zeros((curves,curves)),score_sum=np.zeros(curves))
            models[axis+'__'+spec]=model
        n=m.counts[axis]['n'][0];ev=m.counts[axis]['events'][0]
        rates=np.divide(ev,n,out=np.zeros(J),where=n>0)
        models[axis+'__raw']=dict(axis=axis,spec='raw',reference=ref,interacted=False,
          rates=rates,n_per_bin=n,estimates=rates-rates[ref],identified=(n>0)&(n[ref]>0),
          rank=int((n>0).sum()),meat=np.zeros((J,J)),score_sum=np.zeros(J))
    return models

def score_block(original,edges,models):
    frame=retain_units(original)
    if not len(frame['y']):return
    a=absorption(frame);X=design(frame,edges);y=frame['y'].astype(float)
    for model in models.values():
        if model['spec']=='raw':
            code=bin_axis(frame[model['axis']],model['axis']);J=len(model['rates'])
            count=(a['B']@onehot(code,J)).toarray()
            events=(a['B']@sparse.csr_matrix((y,(np.arange(len(y)),code)),shape=(len(y),J))).toarray()
            scores=np.divide(events-count*model['rates'],model['n_per_bin'],
              out=np.zeros_like(events),where=model['n_per_bin']>0)
            scores-=scores[:,[model['reference']]]
        else:
            xx=X[:,model['indices']]
            e=y-np.asarray(xx@model['beta']).ravel()
            e-=np.asarray(a['A']@e).ravel()[a['u']]/a['n'][a['u']]
            # Absorb by chooser x state; sum scores by chooser across all states.
            cluster_scores=a['B']@xx.multiply(e[:,None])
            scores=np.asarray(cluster_scores@model['projection'])
        model['meat']+=scores.T@scores
        model['score_sum']+=scores.sum(axis=0)

def supports(m,axis,row,min_n,min_choosers,min_months):
    c=m.counts[axis]
    return ((c['n'][row]>=min_n)&(c['switching_choosers'][row]>=min_choosers)&
      (np.count_nonzero(c['month'][row],axis=1)>=min_months))

def finish(m,models,min_n=500,min_choosers=50,min_months=6):
    rows=[];shapes=[];tests=[];diagnostics=[];arrays={}
    for key,model in models.items():
        axis=model['axis'];spec=model['spec'];J=len(axis_definition(axis)[1]);labels=axis_definition(axis)[1]
        denom=m.N-model['rank'] if spec=='raw' else m.N-m.H-model['rank']
        factor=m.G/(m.G-1)*(m.N-1)/denom if m.G>1 and denom>0 else None
        cov=model['meat']*factor if factor is not None else np.full_like(model['meat'],np.nan)
        critical=float(student_t.ppf(.975,m.G-1)) if m.G>1 else np.nan
        identified=model['identified'] & (factor is not None)
        arrays[key+'__estimates']=model['estimates'];arrays[key+'__covariance']=cov
        arrays[key+'__identified']=identified
        diagnostic=dict(axis=axis,specification=spec,estimation_rows=m.N,chooser_clusters=m.G,
          absorbed_chooser_state_units=m.H,within_design_rank=int(model['rank']),CR1_factor=factor,
          residual_degrees_of_freedom=denom,identified_contrasts=int(identified.sum()),
          condition_number=model.get('condition_number'),
          max_projection_error=float(np.max(model.get('projection_error',np.zeros(1)))),
          maximum_abs_curve_score_sum=float(np.max(np.abs(model['score_sum']))))
        diagnostics.append(diagnostic)
        for s in range(3 if model['interacted'] else 1):
            cr=s+1 if model['interacted'] else 0;offset=s*J
            support=supports(m,axis,cr,min_n,min_choosers,min_months)
            for j,item in enumerate(labels):
                k=offset+j;ok=bool(identified[k]);counts=m.counts[axis]
                se=float(np.sqrt(max(0,cov[k,k]))) if ok else None
                estimate=float(model['estimates'][k]*100) if ok else None
                rows.append(dict(axis=axis,specification=spec,context=STATES[s] if model['interacted'] else 'pooled_competitive',
                  **item,n=int(counts['n'][cr,j]),events=int(counts['events'][cr,j]),
                  all_n=int(counts['all_n'][cr,j]),all_events=int(counts['all_events'][cr,j]),
                  choosers=int(counts['choosers'][cr,j]),switching_choosers=int(counts['switching_choosers'][cr,j]),
                  direct_reference_choosers=int(counts['direct_reference_choosers'][cr,j]),
                  months=int(np.count_nonzero(counts['month'][cr,j])),estimable=ok,
                  display_supported=bool(item['display'] and ok and support[j] and support[model['reference']]),
                  estimate_pp=estimate,cluster_se_pp=100*se if ok else None,
                  ci95_low_pp=estimate-100*critical*se if ok else None,
                  ci95_high_pp=estimate+100*critical*se if ok else None,
                  sample_n=m.N,chooser_clusters=m.G,absorbed_units=m.H))
        if not model['interacted']:
            mids=np.array([v['mid'] if v['mid'] is not None else np.nan for v in labels])
            masks=({'left':(mids>=-600)&(mids<=-300),'shoulder':(mids>=-200)&(mids<=-50),'right':(mids>=300)&(mids<=600)}
              if axis=='gap' else {'left':(mids>=-6)&(mids<=-3),'shoulder':(mids>=-2.4)&(mids<=-1.2),'right':(mids>=3)&(mids<=6)} if axis=='payoff' else
              {'left':(mids>=-.5)&(mids<=-.25),'shoulder':(mids>=-.2)&(mids<=-.1),'right':(mids>=.25)&(mids<=.5)})
            weights={}
            for name,mask in masks.items():
                w=mask.astype(float)*m.counts[axis]['n'][0];weights[name]=w/w.sum() if w.sum() else None
            weights['reference']=np.eye(J)[model['reference']]
            support=supports(m,axis,0,min_n,min_choosers,min_months)
            for a,b in [('left','shoulder'),('right','shoulder'),('left','reference'),('right','reference')]:
                row=dict(axis=axis,specification=spec,contrast=a+'_minus_'+b,status='insufficient_supported_bins',
                  estimate_pp=None,cluster_se_pp=None,ci95_low_pp=None,ci95_high_pp=None,p_two_sided=None,
                  exploratory=True)
                if weights[a] is not None and weights[b] is not None:
                    w=weights[a]-weights[b];used=w!=0
                    if identified[used].all() and support[used].all():
                        value=float(w@model['estimates']);se=float(np.sqrt(max(0,w@cov@w)))
                        p=float(2*student_t.sf(abs(value/se),m.G-1)) if se else (1. if value==0 else 0.)
                        row.update(status='estimated',estimate_pp=100*value,cluster_se_pp=100*se,
                          ci95_low_pp=100*(value-critical*se),ci95_high_pp=100*(value+critical*se),p_two_sided=p)
                shapes.append(row)
        else:
            tests.append(heterogeneity_test(m,model,cov,min_n,min_choosers,min_months))
    holm(shapes,lambda r:r['specification']=='chooser_state_controls_k20','p_two_sided','p_holm_primary_shape')
    holm(tests,lambda r:True,'p_cluster_F','p_holm_two_axes')
    return rows,shapes,tests,diagnostics,arrays

def heterogeneity_test(m,model,cov,min_n,min_choosers,min_months):
    axis=model['axis'];labels=axis_definition(axis)[1];J=len(labels)
    common=np.logical_and.reduce([supports(m,axis,s+1,min_n,min_choosers,min_months) for s in range(3)])
    bins=[j for j,x in enumerate(labels) if x['display'] and not x['reference'] and common[j]]
    row=dict(axis=axis,status='insufficient_common_support',tested_bin_centres=[labels[j]['mid'] for j in bins],
      requested_restrictions=2*len(bins),restriction_rank=None,F_statistic=None,p_cluster_F=None,
      chooser_clusters=m.G,exploratory=True,
      null='Equal reference-normalized axis-bin effects in all three competitive board states; other control slopes remain common.')
    if not bins:return row
    C=np.zeros((2*len(bins),3*J))
    for z,s in enumerate((1,2)):
        for i,j in enumerate(bins):C[z*len(bins)+i,s*J+j]=1;C[z*len(bins)+i,j]=-1
    used=(np.abs(C).sum(axis=0)>0)
    if not model['identified'][used].all() or not np.isfinite(cov).all():
        row['status']='unidentified_restrictions';return row
    delta=C@model['estimates'];V=C@cov@C.T;V=(V+V.T)/2
    diagonal=np.diag(V)
    if (diagonal<=0).any():row['status']='degenerate_restriction_variance';return row
    scale=1/np.sqrt(diagonal);H=scale[:,None]*V*scale[None,:]
    values,vectors=np.linalg.eigh(H);keep=values>max(1e-10*values.max(),1e-12)
    if values.min()<-max(1e-8,1e-8*values.max()):raise ValueError('Invalid heterogeneity covariance')
    q=int(keep.sum());z=scale*delta
    residual=z-vectors[:,keep]@(vectors[:,keep].T@z)
    if np.linalg.norm(residual)>1e-6*max(np.linalg.norm(z),1e-10):
        row['status']='restriction_outside_covariance_support';return row
    W=float(np.sum((vectors[:,keep].T@z)**2/values[keep])) if q else 0.
    if q==0:row['status']='zero_rank_restriction_covariance';return row
    row.update(status='estimated',restriction_rank=q,F_statistic=W/q,
      p_cluster_F=float(f_distribution.sf(W/q,q,m.G-1)),Wald_statistic=W,
      denominator_df=m.G-1,max_projection_error=float(np.linalg.norm(residual)))
    return row

def holm(rows,selector,pkey,outkey):
    selected=[r for r in rows if selector(r)]
    p=np.array([r.get(pkey) if r.get(pkey) is not None else 1. for r in selected])
    order=np.argsort(p);previous=0.
    for rank,i in enumerate(order):
        previous=max(previous,min(1.,(len(p)-rank)*p[i]))
        selected[i][outkey]=previous if selected[i].get(pkey) is not None else None
        selected[i][outkey+'_family_size']=len(p)
