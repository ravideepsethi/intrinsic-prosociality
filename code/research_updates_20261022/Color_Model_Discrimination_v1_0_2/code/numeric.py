"""Logistic transform: SciPy fast path when available, stable NumPy fallback."""
import numpy as np

def numpy_expit(x):
    a=np.asarray(x,dtype=np.float64)
    # exp(-abs(x)) cannot overflow. Preserve the small negative-tail probability.
    z=np.exp(-np.abs(a))
    lower=z/(1.+z)
    return np.where(a>=0.,1.-lower,lower)

try:
    from scipy.special import expit
    LOGISTIC_BACKEND='scipy.special.expit'
except ModuleNotFoundError as exc:
    # Do not disguise a broken installed SciPy dependency as an absent package.
    if exc.name not in ('scipy','scipy.special'):raise
    expit=numpy_expit
    LOGISTIC_BACKEND='numpy_stable_expit'
