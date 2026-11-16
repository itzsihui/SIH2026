"""Stall impact model: how much THIS stall's sales fall when the weather turns bad.

Answers "it rained but my shop was not affected": two stalls under the same gauge get the same trigger, but
their cover (and so their price) follows each stall's own measured response, learned from consented QR history.

Model (a random-slope model estimated by empirical Bayes, i.e. partial pooling):
  sales_ratio[stall, day] = QR sales / the stall's normal QR sales for that weekday
  1 - sales_ratio         = k[stall, peril] * pooled_drop(weather that day) + noise
  pooled_drop(x)          : island-wide dose-response curve, by rain band and PSI band
  k[stall, peril]         : the stall's sensitivity (1 = typical, 0 = unaffected, 2 = twice as affected)
  k is shrunk toward 1 in proportion to how little evidence the stall has (few bad days -> close to 1).
"""
from __future__ import annotations
import numpy as np, pandas as pd

RAIN_BINS = [-0.1, 10, 30, 50, 70, 100, 1e9]          # mm per day at the centre's gauge
PSI_BINS = [0, 100, 150, 200, 1e9]


def baseline(qr, trading, clean, dow, train_mask):
    """Each stall's normal QR sales per weekday: median over clean trading days in the training period."""
    D, S = qr.shape
    base = np.full((7, S), np.nan)
    for d in range(7):
        m = (dow == d)[:, None] & trading & clean & train_mask[:, None]
        x = np.where(m, qr, np.nan)
        base[d] = np.nanmedian(x, axis=0)
    return base[dow]                                    # D x S


def pooled_curves(ratio, valid, rain_c, psi_c):
    """Island-wide average drop by rain band (on clear-air days) and by PSI band (on dry days)."""
    out = {}
    rb = np.digitize(rain_c, RAIN_BINS) - 1
    pb = np.digitize(psi_c, PSI_BINS) - 1
    dry, clear = rain_c < 10, psi_c <= 100
    out["rain"] = np.array([1 - np.nanmean(np.where(valid & (rb == b) & clear, ratio, np.nan))
                            for b in range(len(RAIN_BINS) - 1)])
    out["haze"] = np.array([1 - np.nanmean(np.where(valid & (pb == b) & dry, ratio, np.nan))
                            for b in range(len(PSI_BINS) - 1)])
    out["rain"] -= out["rain"][0]; out["haze"] -= out["haze"][0]     # drop relative to a normal day
    return out, rb, pb


def stall_sensitivity(ratio, valid, p, min_p=0.03):
    """Per-stall slope through the origin of (1 - ratio) on pooled drop p, then empirical-Bayes shrinkage to 1."""
    m = valid & (p >= min_p)
    y = np.where(m, 1 - ratio, 0.0); x = np.where(m, p, 0.0)
    sxx = (x * x).sum(0); sxy = (x * y).sum(0); n = m.sum(0)
    k_raw = np.where(sxx > 0, sxy / np.maximum(sxx, 1e-12), np.nan)
    resid = np.where(m, y - k_raw[None, :] * x, 0.0)
    s2 = (resid ** 2).sum(0) / np.maximum(n - 1, 1)
    var_k = np.where(sxx > 0, s2 / np.maximum(sxx, 1e-12), np.inf)
    ok = np.isfinite(k_raw) & np.isfinite(var_k) & (n >= 2)
    tau2 = max(np.nanvar(k_raw[ok]) - np.nanmean(var_k[ok]), 1e-4)      # between-stall variance
    w = np.where(ok, tau2 / (tau2 + var_k), 0.0)
    k_eb = np.where(ok, w * k_raw + (1 - w) * 1.0, 1.0)
    return k_raw, k_eb, w, n, tau2
