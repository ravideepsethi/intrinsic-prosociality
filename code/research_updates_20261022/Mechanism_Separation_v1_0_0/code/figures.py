"""Exportable scientific figures from aggregate results only."""
from common import *
def figures(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report=Path(report);plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    a=report/'regular_equal_surface.parquet';b=report/'regular_equal_K_groups.parquet'
    if a.exists() and b.exists():
        d=pd.read_parquet(a);k=pd.read_parquet(b);d=d.merge(k,on=['sample','kgroup'])
        fig,ax=plt.subplots(figsize=(6.8,4.3))
        for gap,color,label in [(-100,'#b44c36','Weaker opponent: −100'),(100,'#236ca0','Stronger opponent: +100')]:
            x=d[d.gap==gap].sort_values('mean_abs_rg_near_100')
            ax.errorbar(x.mean_abs_rg_near_100,x.coefficient_pp,yerr=1.96*x.se_pp,fmt='o-',color=color,label=label,capsize=3)
            for _,r in x.iterrows():
                if np.isfinite(r.coefficient_pp):ax.annotate(str(int(r.kgroup)),(r.mean_abs_rg_near_100,r.coefficient_pp),xytext=(4,5),textcoords='offset points',fontsize=8)
        ax.axhline(0,color='gray',lw=.8);ax.set_xlabel('Mean |draw payoff| near ±100 (rating points)')
        ax.set_ylabel('Grant contrast relative to equal ratings (pp)');ax.legend(frameon=False)
        fig.text(.13,.01,'Group 0 is own RD at its floor. K-group contrasts are descriptive.',fontsize=8)
        fig.tight_layout(rect=(0,.04,1,1))
        for ext in ('png','pdf'):fig.savefig(report/('Figure_M1.'+ext),dpi=180)
        plt.close(fig)
    p=report/'regular_equal_predicted_gap_profiles.parquet'
    if p.exists():
        d=pd.read_parquet(p)
        if 'model' in d:
            fig,ax=plt.subplots(figsize=(7.2,4.5))
            for name,x in d.groupby('model'):ax.plot(x.gap,x.pp_difference,label=name.replace('_',' '))
            ax.axhline(0,color='gray',lw=.8);ax.axvline(0,color='gray',lw=.8)
            ax.set_xlabel('Opponent minus chooser rating');ax.set_ylabel('Model-predicted contrast (pp)')
            ax.legend(frameon=False,fontsize=8,ncol=2);fig.tight_layout()
            for ext in ('png','pdf'):fig.savefig(report/('Figure_M2.'+ext),dpi=180)
            plt.close(fig)
