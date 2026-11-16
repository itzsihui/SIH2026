"""Rain trigger frequency model: expected days per centre per month with daily rain >= the trigger.

Trained on centre-months 2010-2025; validated leave-one-year-out (each year predicted by a model that never saw it).
Candidates (all Poisson, offset = log valid days):
  M0 island     one rate for all centres and months
  M1 season     island rate by calendar month
  M2 centre     each centre's own historical rate (burning cost, no shrinkage)
  M3 glm        log rate = month + centre effect, ridge-shrunk toward the island (credibility)
  M4 glm+enso   M3 + ONI of the previous Oct-Dec (what is known when the annual price is set)
  M5 gbm        gradient boosting (Poisson loss) on month, lat, lon, ONI - challenger, less explainable
"""
from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_poisson_deviance


def centre_months(cd: pd.DataFrame, centres: pd.DataFrame, oni: pd.DataFrame, mm: float) -> pd.DataFrame:
    cd = cd.assign(year=cd.date.dt.year, month=cd.date.dt.month, valid=cd.rain.notna(), hit=cd.rain >= mm)
    cm = cd.groupby(["centre_id", "year", "month"]).agg(days=("valid", "sum"), y=("hit", "sum")).reset_index()
    cm = cm[cm.days > 0].merge(centres[["centre_id", "lat", "lon"]], on="centre_id")
    return cm.merge(oni, on="year", how="left")


def _design(df, centres_order):
    m = pd.get_dummies(df.month.astype("category").cat.set_categories(range(1, 13)), prefix="m").astype(float)
    c = pd.get_dummies(df.centre_id.astype("category").cat.set_categories(centres_order), prefix="c").astype(float)
    return m, c


class Model:
    def __init__(self, kind: str, alpha: float = 1e-3):
        self.kind, self.alpha = kind, alpha

    def fit(self, tr: pd.DataFrame):
        self.order = sorted(tr.centre_id.unique())
        k = self.kind
        if k == "island":
            self.rate = tr.y.sum() / tr.days.sum()
        elif k == "season":
            self.rate = (tr.groupby("month").y.sum() / tr.groupby("month").days.sum()).to_dict()
        elif k == "centre":
            self.rate = (tr.groupby("centre_id").y.sum() / tr.groupby("centre_id").days.sum()).to_dict()
            self.island = tr.y.sum() / tr.days.sum()
        elif k in ("glm", "glm+enso"):
            X = self._X(tr)
            self.glm = PoissonRegressor(alpha=self.alpha, max_iter=3000)
            self.glm.fit(X, tr.y / tr.days, sample_weight=tr.days)
        elif k == "gbm":
            self.gbm = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05,
                                                     max_leaf_nodes=15, min_samples_leaf=200, random_state=0)
            self.gbm.fit(tr[["month", "lat", "lon", "oni_prev_ond"]], tr.y / tr.days, sample_weight=tr.days)
        return self

    def _X(self, df):
        m, c = _design(df, self.order)
        X = pd.concat([m, c], axis=1)
        if self.kind == "glm+enso":
            X["oni_prev_ond"] = df.oni_prev_ond.fillna(0).values
        return X.values

    def rate_per_day(self, df: pd.DataFrame) -> np.ndarray:
        k = self.kind
        if k == "island":
            return np.full(len(df), self.rate)
        if k == "season":
            return df.month.map(self.rate).values
        if k == "centre":
            return df.centre_id.map(self.rate).fillna(self.island).values
        if k in ("glm", "glm+enso"):
            return self.glm.predict(self._X(df))
        return self.gbm.predict(df[["month", "lat", "lon", "oni_prev_ond"]])

    def predict(self, df):            # expected trigger days in the row's valid days
        return np.clip(self.rate_per_day(df) * df.days.values, 1e-9, None)


def loyo(cm: pd.DataFrame, kinds, years, alpha=1e-3) -> pd.DataFrame:
    rows = []
    for y in years:
        tr, te = cm[cm.year != y], cm[cm.year == y]
        for k in kinds:
            p = Model(k, alpha).fit(tr).predict(te)
            rows.append({"year": y, "model": k, "deviance": mean_poisson_deviance(te.y, p, sample_weight=None),
                         "pred_days_per_centre": p.sum() / te.centre_id.nunique(),
                         "actual_days_per_centre": te.y.sum() / te.centre_id.nunique()})
    return pd.DataFrame(rows)
