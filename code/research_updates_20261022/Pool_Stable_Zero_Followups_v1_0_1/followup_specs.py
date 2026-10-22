"""Design declared before the follow-up run, after viewing the earlier results.

This is an exploratory follow-up, not an external preregistration. No outcome-
dependent bandwidth, polynomial degree, cutoff, or stability threshold selection.
"""
from dataclasses import dataclass, asdict

VERSION = '1.0.1'
SAMPLES = ('rd75_k11_12', 'rd75')
BANDWIDTHS = {'normalized': (.025, .05, .1), 'payoff': (.5, 1., 2.), 'gap': (25., 50., 100.)}
MAIN_H = {'normalized': .05, 'payoff': .5, 'gap': 25.}
PLACEBOS = (-.10, .10)
PRIMARY_SAMPLE = 'rd75_k11_12'
SUPPORT = dict(min_n=500, min_choosers=50, min_months=6, min_gap_levels=5)
TERMS = ('left_slope', 'right_slope', 'right_minus_left_slope',
         'jump_right_minus_left', 'center_atom_minus_left_limit')


def num(x):
    return format(x, '.8g').replace('-', 'm').replace('.', 'p')


@dataclass(frozen=True)
class Spec:
    axis: str
    h: float
    center: float = 0.
    degree: int = 2
    scope: str = 'pooled'
    omit_ties: bool = False

    @property
    def key(self):
        return f'{self.axis}_h{num(self.h)}_c{num(self.center)}_d{self.degree}_{self.scope}_' + ('omit_ties' if self.omit_ties else 'keep_ties')

    def dictionary(self):
        return asdict(self)


def definitions():
    out = []
    for axis, hs in BANDWIDTHS.items():
        for h in hs:
            for degree in (1, 2):
                out.append(Spec(axis, h, degree=degree))
    # All normalized bandwidths; one declared payoff/gap bandwidth each.
    for axis, hs in [('normalized', BANDWIDTHS['normalized']), ('payoff', (.5,)), ('gap', (25.,))]:
        for h in hs:
            out.append(Spec(axis, h, omit_ties=True))
            out.append(Spec(axis, h, scope='by_state'))
    out.extend(Spec('normalized', .05, center=c) for c in PLACEBOS)
    assert len(out) == 30 and len({s.key for s in out}) == len(out)
    return out


PRIMARY = Spec('normalized', .05)
PLACEBO_SPECS = tuple(Spec('normalized', .05, center=c) for c in (0., *PLACEBOS))


def is_primary(sample, spec):
    return sample == PRIMARY_SAMPLE and spec == PRIMARY
