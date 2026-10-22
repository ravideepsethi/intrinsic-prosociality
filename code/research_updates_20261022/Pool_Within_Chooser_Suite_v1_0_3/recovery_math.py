"""Independent one-column reductions for the isolated exact-ply recovery.

This is a diagnostic alternative implementation, not a relaxed tolerance or
a claim about the cause of the v102 discrepancy on the user's machine.
"""
from __future__ import annotations
import numpy as np
import fe_suite as fe
import checked_math as checked


def transformed(d,X,unit,weight):
    if unit!='chooser' or weight!='opportunity':
        raise ValueError('Independent recovery transformation supports chooser OLS only')
    cs,cn=fe.starts_counts(d['chooser'])
    Z=np.empty((len(X),X.shape[1]+1),dtype=np.float64,order='C')
    for j in range(Z.shape[1]):
        column=np.array(d['y'] if j==0 else X[:,j-1],dtype=np.float64,copy=True,order='C')
        Z[:,j]=column-np.repeat(np.add.reduceat(column,cs)/cn,cn)
    counts={'rows':len(X),'choosers':len(cn),'fe_units':len(cn),
      'singleton_choosers':int((cn==1).sum()),'singleton_fe_units':int((cn==1).sum()),
      'rows_in_nonsingleton_fe_units':int(cn[cn>1].sum()),
      'zero_grant_choosers':int((np.add.reduceat(d['y'],cs)==0).sum()),
      'grants':int(d['y'].sum()),'patron_choosers':int((d['patron'][cs]==1).sum())}
    return Z,np.ones(len(X)),cs,counts


def hash_design(digest,Z,w,starts):
    # Shape/boundaries are hashed too: passes must consume identical blocks.
    for a in (np.asarray(Z.shape,dtype='<i8'),Z,w,starts):
        digest.update(np.ascontiguousarray(a).view(np.uint8))


def check_design_hashes(moment_audits,score_audits):
    if len(moment_audits)!=len(score_audits):raise ValueError('Worker count changed between passes')
    for j,(m,s) in enumerate(zip(moment_audits,score_audits)):
        if not m.get('centered_design_sha256') or m['centered_design_sha256']!=s.get('centered_design_sha256'):
            raise ValueError(f'Centered design differs between passes in worker {j}')


def record(audit,name,value):
    audit[name]=max(audit.get(name,0.),float(value))


def check_response_products(Q,G,audit):
    y=np.ascontiguousarray(Q[:,0])
    reference=np.array([np.sum(np.ascontiguousarray(Q[:,j])*y) for j in range(Q.shape[1])])
    bounds=np.maximum(np.sqrt(np.maximum(np.diag(G)*G[0,0],0)),1.)
    error=np.max(np.abs(reference-G[:,0])/bounds)
    record(audit,'max_response_cross_product_error',error)
    if error>1e-11:raise ValueError(f'Independent response cross-product check failed: {error:.6g}')


def predict(x,beta,audit):
    # Explicit column accumulation is authoritative for this recovery.
    reference=np.zeros(len(x));bound=np.zeros(len(x))
    for j,b in enumerate(beta):
        term=np.ascontiguousarray(x[:,j])*b
        reference+=term;bound+=np.abs(term)
    alternative=checked.matvec(x,beta)
    error=np.max(np.abs(reference-alternative)/np.maximum(bound,1.))
    record(audit,'max_prediction_method_difference',error)
    audit['prediction_method_disagreements']=audit.get('prediction_method_disagreements',0)+int(error>1e-11)
    return reference


def cluster_scores(x,we,starts,audit):
    score=np.empty((len(starts),x.shape[1]),dtype=np.float64)
    for j in range(x.shape[1]):
        contribution=np.ascontiguousarray(x[:,j])*we
        score[:,j]=np.add.reduceat(contribution,starts)
        error=abs(np.sum(score[:,j])-np.sum(contribution))/max(np.sum(np.abs(contribution)),1.)
        record(audit,'max_score_reduction_error',error)
        if error>1e-11:raise ValueError(f'Cluster score reduction failed: {error:.6g}')
    return score
