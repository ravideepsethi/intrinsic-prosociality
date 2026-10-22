"""B5 within-chooser profiles, anchored to each group's own P2 composition."""
from fw_common import *
from fw_b import sample,fit_model
from fw_design import profile_bins,EVAL_LABELS,GROUPS

def run(a,run,parts,key):
    work=run/'B/profiles';report=run/'B/report';pk=digest([key,'B_profiles']);end=work/'final'
    if completed(end,pk):return load(end/'status.json')
    rows=[]
    for kind in ['gap','evaluation']:
        spec=dict(name='profile_'+kind,profile=kind,reg='rG',equal=kind=='gap')
        folder=work/kind;_,info=fit_model(parts,folder,digest([pk,kind]),spec,a)
        with np.load(folder/'final/model.npz') as z:
            beta=z['beta'];V=z['covariance'];names=z['names'].tolist();means=z['means'];base=dict(scale=z['scale'],null=z['null'])
        nb=23 if kind=='gap' else 8;counts=np.zeros((4,nb));ref=11 if kind=='gap' else 2
        for p in parts:
            d,_=sample(frame(p),spec);b=profile_bins(d,kind)
            for g in range(4):counts[g]+=np.bincount(b[d.group_code.to_numpy()==g],minlength=nb)
        for g in range(4):
            total=counts[g].sum()
            if not total:continue
            for b in range(nb):
                q=np.array([(float(b==int(n.split('bin')[1]))-counts[g,int(n.split('bin')[1])]/total)
                    if n.startswith(f'g{g}:bin') else 0. for n in names])
                Q=np.r_[q,np.eye(4)[g]]
                contrast=np.array([float(n==f'g{g}:bin{b}') for n in names])
                label=(f'[{50*(b-11)-25},{50*(b-11)+25})' if 0<b<22 else '<-525' if b==0 else '>=525') if kind=='gap' else EVAL_LABELS[b]
                ok=estimable(base,q) and counts[g,b]>0
                rows.append(dict(profile=kind,group=GROUPS[g],bin=b,label=label,opportunities=int(counts[g,b]),
                    reference_bin=ref,**(infer(means[g]+q@beta,Q@V@Q) if ok else dict(status='NOT_ESTIMABLE')),
                    reference_difference_pp=float(contrast@beta) if estimable(base,contrast) else None))
    table(report,'tabB5_profiles',rows)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,2,figsize=(12,4.6));colors=['#2369a8','#d1642b','#50914f','#787878']
    for ax,kind in zip(axs,['gap','evaluation']):
      supported=False
      for g,color in zip(GROUPS,colors):
        z=[r for r in rows if r['profile']==kind and r['group']==g and r.get('status')=='ESTIMATED']
        if not z:continue
        supported=True
        x=[(r['bin']-11)*50 if kind=='gap' else r['bin'] for r in z]
        ax.plot(x,[r['estimate'] for r in z],label=g,color=color,lw=1.5)
        ax.fill_between(x,[r['ci_low'] for r in z],[r['ci_high'] for r in z],color=color,alpha=.12)
      ax.set_ylabel('Adjusted grant rate (%)');ax.spines[['top','right']].set_visible(False)
      if not supported:ax.text(.5,.5,'No separately estimable bins',ha='center',va='center',transform=ax.transAxes)
    axs[0].set_xlabel('Opponent rating minus chooser rating (50-point bins)')
    axs[0].set_title('Roughly equal positions; tails pooled')
    axs[1].set_xticks(range(8),EVAL_LABELS,rotation=35,ha='right',fontsize=8);axs[1].set_title('Competitive evaluation profile')
    axs[1].set_xlabel('Evaluation from disconnected side (cp)');axs[1].legend(frameon=False)
    fig.suptitle('P1 history groups; P2 choices after ply 10');fig.tight_layout();fig.savefig(report/'figB1_gap_by_group.pdf');plt.close(fig)
    status=dict(status='ESTIMATED',standardization='Own group P2 composition; linear probability fit, so intervals may extend beyond 0–100%.',
        gap_reference='[-25,25)',gap_tail_bins='All gaps below -525 or at least 525 pooled in endpoint bins',evaluation_reference='[0,50)')
    save(end/'status.json',status);certify(end,pk,parts,outputs=list(report.glob('tabB5_profiles.*'))+[report/'figB1_gap_by_group.pdf']);return status
