import math


class _norm_dist:
    """Pure-Python drop-in for scipy.stats.norm (only the subset nsepython needs)."""

    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def pdf(x):
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


norm = _norm_dist()