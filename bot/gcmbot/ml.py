"""Makine öğrenmesi stratejisi (gradient boosting, yürüyen pencere ile yeniden eğitim).

Her bar için "şimdi alış (satış) açılsa, SL'den önce TP'ye ulaşır mıydı?" sorusu etiketlenir
(üçlü bariyer yöntemi) ve geçmiş barların özelliklerinden bu olasılığı tahmin eden iki model
(alış, satış) eğitilir. Olasılık eşiği geçerse işlem açılır.

Geleceğe bakma (look-ahead) olmaması için:
- Özellikler sadece o bara kadarki barları kullanır.
- Model her `retrain` barda bir, sadece o ana kadarki veriyle yeniden eğitilir.
- Etiketi o anda henüz kesinleşmemiş barlar (son `horizon` bar) eğitime alınmaz (purge).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .strategies import Strategy

FEATURE_WARMUP = 210  # EMA200 vb. için


def features(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    a = ind.atr(df, 14)
    f = pd.DataFrame(index=df.index)
    for n in (1, 3, 6, 12, 24, 48):
        f[f"ret{n}"] = (c - c.shift(n)) / a
    for n in (20, 50, 200):
        f[f"ema{n}"] = (c - ind.ema(c, n)) / a
    f["rsi14"] = ind.rsi(c, 14)
    f["rsi3"] = ind.rsi(c, 3)
    f["atr_pct"] = a / c
    f["atr_ratio"] = a / ind.atr(df, 100)
    lo, _, up = ind.bollinger(c, 20, 2.0)
    f["bb"] = (c - lo) / (up - lo)
    hh, ll = h.rolling(20).max(), l.rolling(20).min()
    f["donchian"] = (c - ll) / (hh - ll)
    f["range"] = (h - l) / a
    t = pd.to_datetime(df["time"], unit="s")
    f["hour_sin"] = np.sin(2 * np.pi * t.dt.hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * t.dt.hour / 24)
    f["dow"] = t.dt.day_of_week.astype(float)
    return f.replace([np.inf, -np.inf], np.nan)


def barrier_labels(df: pd.DataFrame, sl_mult: float, tp_mult: float, horizon: int,
                   atr_period: int = 14) -> tuple[np.ndarray, np.ndarray]:
    """Bar i'nin kapanışında sinyal → i+1 açılışında giriş. TP, SL'den önce ve `horizon` bar
    içinde gelirse 1, gelmezse 0; yeterli gelecek veri yoksa NaN. Aynı barda ikisi de
    tetiklenirse backtest gibi SL varsayılır."""
    o, h, l = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low"))
    a = ind.atr(df, atr_period).to_numpy()
    n = len(df)
    long_y = np.full(n, np.nan)
    short_y = np.full(n, np.nan)
    for i in range(n - 1):
        if not a[i] > 0:
            continue
        end = i + 1 + horizon
        if end > n:
            break
        entry = o[i + 1]
        l_tp, l_sl = entry + tp_mult * a[i], entry - sl_mult * a[i]
        s_tp, s_sl = entry - tp_mult * a[i], entry + sl_mult * a[i]
        ly = sy = 0.0
        l_done = s_done = False
        for j in range(i + 1, end):
            if not l_done:
                if l[j] <= l_sl:
                    l_done = True
                elif h[j] >= l_tp:
                    ly, l_done = 1.0, True
            if not s_done:
                if h[j] >= s_sl:
                    s_done = True
                elif l[j] <= s_tp:
                    sy, s_done = 1.0, True
            if l_done and s_done:
                break
        long_y[i], short_y[i] = ly, sy
    return long_y, short_y


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    # Sığ ağaçlar + güçlü düzenlileştirme: finansal veride aşırı uydurmaya karşı
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                          min_samples_leaf=80, l2_regularization=1.0, random_state=0)


# Aynı veri ve eğitim ayarlarıyla (sadece eşik farklı) tekrar eğitmemek için olasılık önbelleği
_PROBA_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


class MLBoost(Strategy):
    name = "ml_boost"
    title = "Makine Öğrenmesi (Gradient Boosting)"
    description = (
        "Fiyat, momentum, volatilite ve saat özelliklerinden 'bu işlem SL'den önce TP'ye ulaşır mı?' "
        "olasılığını tahmin eden model. Her 'retrain' barda bir, sadece geçmiş veriyle yeniden "
        "eğitilir; olasılık eşiği geçerse işlem açar, pozisyonu en fazla 'horizon' bar tutar."
    )
    # sl_mult/tp_mult etiketlemede kullanılır; risk ayarlarındaki SL/TP çarpanlarıyla aynı olmalı
    default_params = {"threshold": 0.45, "horizon": 24, "train_bars": 4000, "retrain": 500,
                      "sl_mult": 1.5, "tp_mult": 3.0}
    param_grid = {"threshold": [0.40, 0.45, 0.50], "horizon": [24], "train_bars": [4000], "retrain": [500],
                  "sl_mult": [1.5], "tp_mult": [3.0]}

    @property
    def warmup(self) -> int:
        return int(self.params["train_bars"]) + FEATURE_WARMUP

    @property
    def max_hold_bars(self) -> int:
        return int(self.params["horizon"])

    def _probabilities(self, df: pd.DataFrame, start: int) -> tuple[np.ndarray, np.ndarray]:
        p = self.params
        key = (len(df), int(df["time"].iloc[0]), int(df["time"].iloc[-1]), float(df["close"].iloc[-1]),
               start, p["horizon"], p["train_bars"], p["retrain"], p["sl_mult"], p["tp_mult"])
        if key in _PROBA_CACHE:
            return _PROBA_CACHE[key]
        X = features(df).to_numpy()
        yl, ys = barrier_labels(df, p["sl_mult"], p["tp_mult"], int(p["horizon"]))
        n = len(df)
        pl, ps = np.zeros(n), np.zeros(n)
        H, train, step = int(p["horizon"]), int(p["train_bars"]), int(p["retrain"])
        valid_x = ~np.isnan(X).any(axis=1)
        for t0 in range(start, n, step):
            t1 = min(n, t0 + step)
            lo = max(0, t0 - train)
            hi = t0 - H - 1  # bu barların etiketi t0 anında kesinleşmiş durumda
            if hi - lo < 500:
                continue
            idx = np.arange(lo, hi)
            idx = idx[valid_x[idx] & ~np.isnan(yl[idx])]
            if len(idx) < 300:
                continue
            pred = np.arange(t0, t1)
            pred = pred[valid_x[pred]]
            if not len(pred):
                continue
            for y, out in ((yl, pl), (ys, ps)):
                if len(np.unique(y[idx])) < 2:
                    continue
                m = _model().fit(X[idx], y[idx])
                out[pred] = m.predict_proba(X[pred])[:, 1]
        if len(_PROBA_CACHE) > 64:
            _PROBA_CACHE.clear()
        _PROBA_CACHE[key] = (pl, ps)
        return pl, ps

    def _to_signals(self, pl, ps) -> np.ndarray:
        thr = self.params["threshold"]
        return np.where((pl > thr) & (pl >= ps), 1, np.where(ps > thr, -1, 0))

    def signals(self, df):
        pl, ps = self._probabilities(df, self.warmup)
        return pd.Series(self._to_signals(pl, ps), index=df.index, dtype=int)

    def last_signal(self, df):
        if len(df) < self.warmup:
            return 0
        # Canlıda sadece son bar için: son veriyle eğit, son barı tahmin et
        pl, ps = self._probabilities(df, len(df) - 1)
        return int(self._to_signals(pl[-1:], ps[-1:])[0])
