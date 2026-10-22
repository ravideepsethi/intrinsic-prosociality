"""Numerical definitions, independent of file and SQL implementation."""
import numpy as np
import pandas as pd
from common import DAY

def percentile(hist,values):
    """Right-continuous ECDF, one account per previous-month snapshot."""
    ratings=hist.rating.to_numpy(float);counts=hist.n.to_numpy(np.int64)
    if len(ratings)==0 or counts.sum()<=0:raise RuntimeError('Empty reference population')
    if np.any(np.diff(ratings)<=0) or np.any(counts<=0):raise RuntimeError('Invalid reference histogram')
    sums=np.r_[0,np.cumsum(counts)]
    values=np.asarray(values,float);out=100*sums[np.searchsorted(ratings,values,side='right')]/sums[-1]
    return np.where(np.isfinite(values),out,np.nan)

def stakes(base,hist):
    out=base.copy();out['rating_draw']=out.rating+out.rg;out['rating_win']=out.rating+out.rc
    out['percentile_pre']=percentile(hist,out.rating)
    out['percentile_draw']=percentile(hist,out.rating_draw)
    out['percentile_win']=percentile(hist,out.rating_win)
    out['percentile_pp']=out.percentile_win-out.percentile_draw
    out['cross_100']=np.floor(out.rating_win/100)>np.floor(out.rating_draw/100)
    # Counterfactual comparison, not a claim about psychological salience.
    for boundary in (50,75,90,95,99):
        out[f'cross_p{boundary}']=(out.percentile_win>=boundary)&(out.percentile_draw<boundary)
    out['standing_decile']=np.minimum(9,np.floor(out.percentile_pre/10)).astype(int)+1
    out['rating_band_200']=(200*np.floor(out.rating/200)).astype(int)
    out['rd_band']=np.where(out.rd<=60,'RD<=60',np.where(out.rd<=110,'60<RD<=110','RD>110'))
    return out

def prior_features(history,targets,batch_size=4096):
    """Last 50/100 strictly earlier start rating observations, same account.

    Inputs: history sorted by (user_id,t,game_id); targets in any order. Retain
    101 past rows per account across months to detect a tie cut at row 100.
    No outcome, rating update, or focal pregame rating enters these windows.
    """
    fields=['n_prior_capped101','sd50','sd100','iqr100','detrended_sd100',
            'span100_days','last_start_age_days','missing100','tie50','tie100']
    out=pd.DataFrame({k:np.full(len(targets),np.nan) for k in fields})
    out['n_prior_capped101']=0
    if not len(history) or not len(targets):return out
    u=history.user_id.to_numpy(np.int64);t=history.t.to_numpy(np.int64);r=history.rating.to_numpy(float)
    r=np.where(r>0,r,np.nan)
    keys=np.empty(len(u),dtype=[('u','i8'),('t','i8')]);keys['u']=u;keys['t']=t
    # Strict left search excludes ALL events at the focal second.
    anchors=np.empty(len(targets),dtype=keys.dtype)
    anchors['u']=targets.user_id.to_numpy(np.int64);anchors['t']=targets.t.to_numpy(np.int64)
    ends=np.searchsorted(keys,anchors,side='left')
    for start in range(0,len(targets),batch_size):
        stop=min(start+batch_size,len(targets));en=ends[start:stop];uu=anchors['u'][start:stop]
        jj=en[:,None]-np.arange(1,102)[None,:];ix=np.maximum(jj,0)
        same=(jj>=0)&(u[ix]==uu[:,None]);rr=r[ix];tt=t[ix]
        count=np.sum(same,axis=1);out.loc[start:stop-1,'n_prior_capped101']=count
        age=np.where(same[:,0],(anchors['t'][start:stop]-tt[:,0])/DAY,np.nan)
        out.loc[start:stop-1,'last_start_age_days']=age
        for width in (50,100):
            tie=same[:,width]&(tt[:,width-1]==tt[:,width])
            valid=(count>=width)&np.all(np.isfinite(rr[:,:width]),axis=1)&~tie
            sd=np.full(len(en),np.nan);sd[valid]=np.std(rr[valid,:width],axis=1,ddof=1)
            out.loc[start:stop-1,f'sd{width}']=sd
            out.loc[start:stop-1,f'tie{width}']=tie.astype(float)
            if width==100:
                iqr=np.full(len(en),np.nan);det=iqr.copy();span=iqr.copy()
                if valid.any():
                    z=rr[valid,:100];quant=np.quantile(z,[.25,.75],axis=1)
                    iqr[valid]=quant[1]-quant[0]
                    x=np.arange(100,dtype=float)-49.5;center=z-z.mean(axis=1)[:,None]
                    residual=center-(center@x/(x@x))[:,None]*x
                    det[valid]=np.sqrt(np.sum(residual**2,axis=1)/98)
                    span[valid]=(tt[valid,0]-tt[valid,99])/DAY
                out.loc[start:stop-1,'iqr100']=iqr;out.loc[start:stop-1,'detrended_sd100']=det
                out.loc[start:stop-1,'span100_days']=span
                out.loc[start:stop-1,'missing100']=np.sum(same[:,:100]&~np.isfinite(rr[:,:100]),axis=1)
    return out

def add_ratios(df):
    for denominator in ('sd50','sd100','iqr100','detrended_sd100'):
        x=df[denominator].to_numpy(float)
        # A zero-width history is an explicit coverage category, not infinity.
        df['premium_over_'+denominator]=np.divide(df.ki,x,out=np.full(len(df),np.nan),where=np.isfinite(x)&(x>1e-9))
    df['history100_complete']=df.sd100.notna()
    df['history100_zero']=df.sd100.le(1e-9)&df.sd100.notna()
    return df
