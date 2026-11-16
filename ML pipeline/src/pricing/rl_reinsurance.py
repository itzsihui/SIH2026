"""Reinforcement learning for Income's annual reinsurance and capital decision.

WHY RL BELONGS HERE AND NOWHERE ELSE
The customer's premium is set by published, explainable models, because MAS FEAT and fair-dealing
require a price that can be explained and that does not drift under the customer. A learning agent
that moved live prices would breach that.

But Income makes a second decision every year that is NOT a customer price: how much reinsurance to
buy, before it knows the weather. That decision is
  sequential      this year's retained loss changes next year's capital,
  non-stationary  the climate distribution drifts, so the past is not a reliable guide,
  and it has a signal the annual price cannot legally use -- the May-July ENSO index, which
                  correlates 0.80 with that season's haze but only 0.17 at the time prices are set.
That is a Markov decision process on Income's own balance sheet. RL is applied there and only there.

ENVIRONMENT  (one step = one policy year)
  state    (capital bucket, ENSO bucket, years since last severe haze)      36 discrete states
  action   one of 9 reinsurance structures (attachment x limit), including buying none
  dynamics ENSO drawn with persistence -> severe haze drawn CONDITIONAL on ENSO (fitted 2014-2026)
           -> rain year resampled from history -> claims -> layer applied -> capital carried forward
  reward   underwriting result as a fraction of premium, minus a solvency penalty when capital
           falls through the floor. An insurer maximises utility under a capital constraint, not
           raw expected profit, and the penalty is what encodes that.
  drift    every episode draws its own climate trend, so the agent is trained against a moving
           distribution rather than the assumption that the past repeats.

Tabular Q-learning is used deliberately: 36 x 9 values can be printed in full and signed off by an
actuary. A deep policy could not be.
"""
from __future__ import annotations
import numpy as np

# (attachment as a multiple of expected claims, limit as a multiple). (inf, 0) = buy nothing.
STRUCTURES = [(np.inf, 0.0), (1.0, 2.0), (1.0, 3.0), (1.25, 2.0), (1.25, 3.0),
              (1.5, 2.0), (1.5, 3.0), (1.5, 4.0), (2.0, 3.0)]
STRUCTURE_NAMES = ["none", "1.0x att / 2x lim", "1.0x / 3x", "1.25x / 2x", "1.25x / 3x",
                   "1.5x / 2x", "1.5x / 3x (static rule)", "1.5x / 4x", "2.0x / 3x"]
RATE_ON_LINE = 1.6                  # reinsurer charges 1.6x the expected layer loss
CAP_BUCKETS = [0.5, 1.0, 2.0]       # capital / annual premium
ENSO_BUCKETS = [0.0, 0.6]           # May-Jul ONI
QUIET_BUCKETS = [1, 4]              # years since the last severe haze season
N_STATES = (len(CAP_BUCKETS) + 1) * (len(ENSO_BUCKETS) + 1) * (len(QUIET_BUCKETS) + 1)
N_ACTIONS = len(STRUCTURES)


def _b(x, edges):
    return int(np.searchsorted(edges, x))


def state_index(cap_ratio, enso, quiet):
    return (_b(cap_ratio, CAP_BUCKETS) * (len(ENSO_BUCKETS) + 1) + _b(enso, ENSO_BUCKETS)) \
        * (len(QUIET_BUCKETS) + 1) + _b(quiet, QUIET_BUCKETS)


def decode(s):
    q = s % (len(QUIET_BUCKETS) + 1); s //= (len(QUIET_BUCKETS) + 1)
    e = s % (len(ENSO_BUCKETS) + 1); c = s // (len(ENSO_BUCKETS) + 1)
    return (["<0.5x", "0.5-1x", "1-2x", ">2x"][c], ["La Nina / neutral", "mild El Nino", "strong El Nino"][e],
            ["haze last year", "1-4 quiet years", ">4 quiet years"][q])


def fit_haze_probability(oni, severe, threshold=0.5, smoothing=1.0):
    """P(severe haze season | May-Jul ONI), estimated NON-PARAMETRICALLY in two buckets.

    A logistic curve on 13 seasons with 3 positives is either separable (99% confidence the data
    cannot support) or, once regularised enough to be honest, flat enough to destroy the signal.
    Neither is defensible. Two Laplace-smoothed buckets state exactly what the record shows:

        ONI above +0.5 in May-Jul   ->  severe haze in 3 of 4 seasons
        ONI at or below +0.5        ->  severe haze in 0 of 9 seasons

    Smoothing keeps the low bucket off zero, because 9 observations cannot prove impossibility.
    """
    oni, severe = np.asarray(oni, float), np.asarray(severe, float)
    hi = oni > threshold
    p_hi = (severe[hi].sum() + smoothing) / (hi.sum() + 2 * smoothing)
    p_lo = (severe[~hi].sum() + smoothing) / ((~hi).sum() + 2 * smoothing)
    return (lambda e: float(p_hi if e > threshold else p_lo),
            dict(threshold=threshold, p_high_enso=float(p_hi), p_low_enso=float(p_lo),
                 n_high=int(hi.sum()), n_low=int((~hi).sum()), severe_high=int(severe[hi].sum()),
                 severe_low=int(severe[~hi].sum())))


class Env:
    def __init__(self, premium, exp_ratio, rain_claims, haze_claims, p_haze_given_enso, enso_hist,
                 floor_ratio=0.25, drift_sd=0.02, rng=None):
        self.premium, self.exp_ratio = float(premium), float(exp_ratio)
        self.rain = np.asarray(rain_claims, float)
        self.haze = np.asarray([h for h in haze_claims if h > 0], float)
        self.p_haze = p_haze_given_enso
        self.enso_hist = np.asarray(enso_hist, float)
        self.floor = floor_ratio * self.premium
        self.drift_sd = drift_sd
        self.rng = rng or np.random.default_rng(0)
        self._quote_cache = {}
        self.EL = self.rain.mean() + self.haze.mean() * float(np.mean([self.p_haze(e) for e in self.enso_hist]))

    def reset(self, capital=None):
        self.capital = self.premium if capital is None else float(capital)
        self.enso = float(self.rng.choice(self.enso_hist))
        self.quiet, self.trend = 3, 1.0
        self.drift = float(self.rng.normal(0.0, self.drift_sd))
        return state_index(self.capital / self.premium, self.enso, self.quiet)

    def _claims(self, enso, n=1):
        e = np.atleast_1d(enso)
        e = np.resize(e, n)
        r = self.rng.choice(self.rain, n) * self.trend
        h = (self.rng.random(n) < np.array([self.p_haze(v) for v in e])) * self.rng.choice(self.haze, n)
        return r + h

    def quote(self, action):
        """Expected layer loss, cached on (action, ENSO to 0.25) -- a reinsurer quotes off the same
        seasonal outlook, and recomputing it by simulation on every step made training intractable."""
        att_m, lim_m = STRUCTURES[action]
        if not np.isfinite(att_m):
            return np.inf, 0.0, 0.0
        att, lim = att_m * self.EL, lim_m * self.EL
        key = (action, round(self.enso * 4) / 4)
        if key not in self._quote_cache:
            draws = self._claims(np.full(6000, key[1]), 6000)
            self._quote_cache[key] = float(np.clip(draws - att, 0, lim).mean())
        return att, lim, RATE_ON_LINE * self._quote_cache[key] * self.trend

    def step(self, action):
        att, lim, reins_prem = self.quote(action)
        claims = float(self._claims(self.enso, 1)[0])
        recovery = float(np.clip(claims - att, 0, lim)) if np.isfinite(att) else 0.0
        result = self.premium * (1 - self.exp_ratio) - claims - reins_prem + recovery
        self.capital += result
        reward = result / self.premium
        breach = self.capital < self.floor
        if breach:
            reward -= 3.0
            self.capital = self.floor
        self.quiet = 0 if claims > 2 * self.rain.mean() else self.quiet + 1
        self.trend *= (1 + self.drift)
        self.enso = float(np.clip(0.45 * self.enso + 0.55 * self.rng.choice(self.enso_hist), -2.0, 3.0))
        s = state_index(self.capital / self.premium, self.enso, self.quiet)
        return s, reward, dict(result=result, claims=claims, reins_prem=reins_prem, recovery=recovery, breach=breach)


def train(env, episodes=60000, horizon=10, alpha=0.06, gamma=0.92, eps0=0.9, seed=0):
    rng = np.random.default_rng(seed)
    env.rng = np.random.default_rng(seed + 1)
    Q = np.zeros((N_STATES, N_ACTIONS))
    visits = np.zeros((N_STATES, N_ACTIONS), int)
    for ep in range(episodes):
        eps = max(0.05, eps0 * (1 - ep / episodes))
        s = env.reset()
        for _ in range(horizon):
            a = int(rng.integers(N_ACTIONS)) if rng.random() < eps else int(Q[s].argmax())
            s2, r, _ = env.step(a)
            visits[s, a] += 1
            Q[s, a] += alpha * (r + gamma * Q[s2].max() - Q[s, a])
            s = s2
    return Q, visits


def evaluate(env, policy, episodes=5000, horizon=10, seed=99):
    env.rng = np.random.default_rng(seed)
    cum, breaches, years = [], 0, []
    for _ in range(episodes):
        s = env.reset(); tot = 0.0; br = False
        for _ in range(horizon):
            a = policy(s, env)
            s, _, info = env.step(a)
            tot += info["result"]; years.append(info["result"]); br |= info["breach"]
        cum.append(tot); breaches += br
    cum, years = np.array(cum), np.array(years)
    return dict(mean_10yr=float(cum.mean()), p5_10yr=float(np.quantile(cum, .05)),
                prob_10yr_loss=float((cum < 0).mean()), prob_solvency_breach=float(breaches / episodes),
                mean_year=float(years.mean()), cvar5_year=float(np.sort(years)[:max(1, len(years) // 20)].mean()))
