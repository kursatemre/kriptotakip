"""Al-sat stratejileri.

Her strateji, kapanmış barlardan oluşan bir DataFrame alır
(sütunlar: time, open, high, low, close) ve her bar için sinyal üretir:
  +1 = AL, -1 = SAT, 0 = sinyal yok.

Sinyal, barın KAPANIŞINDA oluşur; işlem bir sonraki barın açılışında açılır.
Yeni strateji eklemek için Strategy'den türetip STRATEGIES sözlüğüne ekleyin.
"""

from __future__ import annotations

import pandas as pd

from . import indicators as ind


class Strategy:
    name = ""
    title = ""
    description = ""
    default_params: dict = {}
    # Optimizasyonda denenecek değerler (backtest.optimize)
    param_grid: dict = {}

    def __init__(self, params: dict | None = None):
        unknown = set(params or {}) - set(self.default_params)
        if unknown:
            raise ValueError(f"{self.name}: bilinmeyen parametre(ler): {', '.join(sorted(unknown))}")
        self.params = {**self.default_params, **(params or {})}
        for key, default in self.default_params.items():
            self.params[key] = type(default)(self.params[key])

    @property
    def warmup(self) -> int:
        """Sinyal üretmek için gereken minimum bar sayısı."""
        return max(int(v) for v in self.params.values()) + 5

    def signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def last_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.warmup:
            return 0
        return int(self.signals(df).iloc[-1])


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _to_signal(buy: pd.Series, sell: pd.Series) -> pd.Series:
    out = pd.Series(0, index=buy.index, dtype=int)
    out[buy.fillna(False)] = 1
    out[sell.fillna(False)] = -1
    return out


class EmaTrend(Strategy):
    name = "ema_trend"
    title = "EMA Kesişimi + Trend Filtresi"
    description = (
        "Hızlı EMA yavaş EMA'yı yukarı keserse ve fiyat trend EMA'sının üstündeyse AL; "
        "aşağı keserse ve fiyat trend EMA'sının altındaysa SAT."
    )
    default_params = {"fast": 20, "slow": 50, "trend": 200}
    param_grid = {"fast": [10, 20, 30], "slow": [50, 100], "trend": [100, 200]}

    def signals(self, df):
        c = df["close"]
        fast = ind.ema(c, self.params["fast"])
        slow = ind.ema(c, self.params["slow"])
        trend = ind.ema(c, self.params["trend"])
        return _to_signal(
            _cross_up(fast, slow) & (c > trend),
            _cross_down(fast, slow) & (c < trend),
        )


class RsiPullback(Strategy):
    name = "rsi_pullback"
    title = "RSI Geri Çekilme (Trend Yönünde)"
    description = (
        "Yükselen trendde (fiyat > trend EMA) RSI aşırı satım bölgesinden yukarı çıkınca AL; "
        "düşen trendde RSI aşırı alım bölgesinden aşağı inince SAT."
    )
    default_params = {"period": 14, "oversold": 30, "overbought": 70, "trend": 200}
    param_grid = {"period": [7, 14], "oversold": [25, 30, 35], "overbought": [65, 70, 75], "trend": [200]}

    def signals(self, df):
        c = df["close"]
        r = ind.rsi(c, self.params["period"])
        trend = ind.ema(c, self.params["trend"])
        lo = pd.Series(float(self.params["oversold"]), index=c.index)
        hi = pd.Series(float(self.params["overbought"]), index=c.index)
        return _to_signal(
            _cross_up(r, lo) & (c > trend),
            _cross_down(r, hi) & (c < trend),
        )


class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    title = "Donchian Kanal Kırılımı"
    description = (
        "Kapanış son N barın en yükseğini kırarsa AL, en düşüğünü kırarsa SAT "
        "(klasik trend takip / 'turtle' yaklaşımı)."
    )
    default_params = {"period": 20}
    param_grid = {"period": [10, 20, 40, 55]}

    def signals(self, df):
        n = self.params["period"]
        # shift(1): mevcut barı kanala dahil etme
        upper = df["high"].rolling(n, min_periods=n).max().shift(1)
        lower = df["low"].rolling(n, min_periods=n).min().shift(1)
        c = df["close"]
        return _to_signal(_cross_up(c, upper), _cross_down(c, lower))


class BollingerReversion(Strategy):
    name = "bollinger_reversion"
    title = "Bollinger Bandı Dönüşü"
    description = (
        "Fiyat alt bandın altından tekrar bandın içine girerse AL, "
        "üst bandın üstünden tekrar içine girerse SAT (yatay piyasalar için)."
    )
    default_params = {"period": 20, "mult": 2.0}
    param_grid = {"period": [14, 20, 30], "mult": [1.5, 2.0, 2.5]}

    def signals(self, df):
        c = df["close"]
        lower, _, upper = ind.bollinger(c, self.params["period"], self.params["mult"])
        return _to_signal(_cross_up(c, lower), _cross_down(c, upper))


STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (EmaTrend, RsiPullback, DonchianBreakout, BollingerReversion)
}


def make_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"Bilinmeyen strateji: {name}. Mevcut: {', '.join(STRATEGIES)}")
    return STRATEGIES[name](params)


def describe_strategies() -> list[dict]:
    return [
        {
            "name": cls.name,
            "title": cls.title,
            "description": cls.description,
            "default_params": cls.default_params,
            "param_grid": cls.param_grid,
        }
        for cls in STRATEGIES.values()
    ]
