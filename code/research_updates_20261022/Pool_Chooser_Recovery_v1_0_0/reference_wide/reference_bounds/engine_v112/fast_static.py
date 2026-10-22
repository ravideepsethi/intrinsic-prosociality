"""Same static likelihood and gradient, with fewer full-panel temporaries.

No fast-math, approximation, changed penalty, changed starts or subsampling.
Zero-weight bootstrap accounts contribute exactly zero and are skipped.
The archived implementation remains the reference for perception models.
"""
import bootstrap_path
import numpy as np
from numba import njit
from model import Model as ReferenceModel


@njit(cache=True)
def sufficient_statistics(y, ptr, cell, kappa, loss, zeta, alpha, effect, B, lp, group, aw):
    J=len(alpha);n=len(y);H=lp.shape[0]
    probability=np.empty((n,J));row_residual=np.zeros(n)
    ga=np.zeros(J);gc=np.zeros((J,100));gb=np.zeros((J,2));gp=np.zeros((H,J))
    total=0.;den=0.;ell=np.empty(J);post=np.empty(J)
    for i in range(len(ptr)-1):
        weight=aw[i]
        if weight==0.:continue
        den+=weight;h=group[i]
        for k in range(J):ell[k]=lp[h,k]
        for r in range(ptr[i],ptr[i+1]):
            for k in range(J):
                u=alpha[k]+zeta[r]-kappa[r]*B[k,0]-loss[r]*B[k,1]+effect[k,cell[r]]
                if u>=0.:
                    e=np.exp(-u);t=np.log1p(e)
                    ell[k]+= -t if y[r]>0 else -u-t
                    probability[r,k]=1./(1.+e)
                else:
                    e=np.exp(u);t=np.log1p(e)
                    ell[k]+= u-t if y[r]>0 else -t
                    probability[r,k]=e/(1.+e)
        top=np.max(ell);s=0.
        for k in range(J):
            post[k]=np.exp(ell[k]-top);s+=post[k]
        total+=weight*(top+np.log(s))
        for k in range(J):post[k]*=weight/s
        for k in range(J):gp[h,k]+=post[k]-weight*np.exp(lp[h,k])
        for r in range(ptr[i],ptr[i+1]):
            for k in range(J):
                residual=(y[r]-probability[r,k])*post[k]
                row_residual[r]+=residual;ga[k]+=residual;gc[k,cell[r]]+=residual
                gb[k,0]-=residual*kappa[r];gb[k,1]-=residual*loss[r]
    return total,den,ga,gc,gb,gp,row_residual


class FastStaticModel(ReferenceModel):
    def objective(self,v,d,ridge=1e-6):
        if self.spec.perception:return super().objective(v,d,ridge)
        dec=self.decode(v);g=np.zeros(self.size)
        # Almost all specifications use every control: avoid NumPy's advanced-
        # indexing copy on both Z@eta and Z.T@residual at every optimizer step.
        if len(self.cols)==d['Z'].shape[1]:Z=d['Z']
        else:
            if getattr(self,'_z_source',None) is not d['Z']:
                self._z_source=d['Z'];self._selected_z=np.ascontiguousarray(d['Z'][:,self.cols])
            Z=self._selected_z
        accounts=len(d['ptr'])-1
        group=d['group'] if self.spec.tier_priors else np.zeros(accounts,np.int64)
        aw=d.get('aw',np.ones(accounts))
        total,den,ga,gc,gb,gp,residual=sufficient_statistics(
            d['y'],d['ptr'],d['cell'],d['kappa'],d['loss'],Z@dec['eta'],
            dec['alpha'],dec['effect'],dec['B'],dec['lp'],group,aw)
        if den<=0:raise ValueError('No positively weighted accounts')
        g[self.slices['alpha']]=ga;g[self.slices['eta']]=Z.T@residual
        if self.spec.surface=='type_cells':g[self.slices['cell_effect']]=gc[:,self.nonref].ravel()
        else:
            gt=gc@dec['A']
            gt_raw=gt if dec['raw_theta'] is None else gt*(1-dec['index_offset'])+ga*dec['index_offset']
            g[self.slices['theta']]=gt_raw.sum() if self.common_theta else gt_raw
            ga_index=dec['theta']@gc
            if self.spec.surface=='free':g[self.slices['A']]=ga_index[self.free_cells]
            else:
                for key,jac in dec['ijac'].items():g[self.slices[key]]=ga_index@jac
                if 'f0' in self.slices:g[self.slices['f0']]+=np.sum((ga-gt)*dec['raw_theta'])
        if self.spec.cost in ['separate','signed']:g[self.slices['cost_pair']]=gb.ravel()
        elif self.spec.cost!='none':
            angle=dec['angle'];direction=np.array([np.cos(angle),np.sin(angle)])
            gt=gb@direction;g[self.slices['amplitude']]=gt.sum() if self.common_cost else gt
            if self.spec.cost=='full':g[self.slices['angle']]=np.sum(gb*dec['amplitude'][:,None]*np.array([-np.sin(angle),np.cos(angle)]))
        g[self.slices['prior']]=gp[:,1:].ravel()
        # Identical identified-surface penalty and chain rule to base/model.py.
        effects=dec['effect'][:,self.support]
        penalty=.5*ridge*(np.mean(effects**2)+np.mean(dec['B']**2)+np.sum(dec['eta']**2))
        pg=np.zeros_like(g);pec=np.zeros_like(gc)
        pec[:,self.support]=ridge*effects/effects.size
        if self.spec.surface=='type_cells':pg[self.slices['cell_effect']]=pec[:,self.nonref].ravel()
        else:
            pt=pec@dec['A'];pt_raw=pt if dec['raw_theta'] is None else pt*(1-dec['index_offset'])
            pg[self.slices['theta']]=pt_raw.sum() if self.common_theta else pt_raw
            pa=dec['theta']@pec
            if self.spec.surface=='free':pg[self.slices['A']]=pa[self.free_cells]
            else:
                for key,jac in dec['ijac'].items():pg[self.slices[key]]=pa@jac
                if 'f0' in self.slices:pg[self.slices['f0']]-=np.sum(pt*dec['raw_theta'])
        pb=ridge*dec['B']/dec['B'].size
        if self.spec.cost in ['separate','signed']:pg[self.slices['cost_pair']]=pb.ravel()
        elif self.spec.cost!='none':
            pt=pb@np.array([np.cos(dec['angle']),np.sin(dec['angle'])])
            pg[self.slices['amplitude']]=pt.sum() if self.common_cost else pt
            if self.spec.cost=='full':pg[self.slices['angle']]=np.sum(pb*dec['amplitude'][:,None]*np.array([-np.sin(dec['angle']),np.cos(dec['angle'])]))
        pg[self.slices['eta']]=ridge*dec['eta']
        return float(-total/den+penalty),-g/den+pg
