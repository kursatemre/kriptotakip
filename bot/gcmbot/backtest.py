"""Backtest: stratejileri geçmiş veride dener, karşılaştırır ve optimize eder.

Varsayımlar (canlı motorla aynı mantık):
- Sinyal barın kapanışında oluşur, işlem bir sonraki barın açılışında açılır.
- Barlar BID fiyatıdır (MT5 gibi); alışlar ASK = bid + spread'den açılır.
- SL ve TP aynı barda ikisi birden tetiklenirse kötü senaryo (SL) varsayılır.
- Her işlemde sermayenin risk_pct%'i riske edilir (bileşik).
- Max düşüş, açık pozisyonun bar içindeki en kötü fiyattaki zararını da içerir.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from .strategies import STRATEGIES, Strategy, make_strategy


@dataclass
class BacktestSettings:
    risk_pct: float = 1.0
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    atr_period: int = 14
    spread: float = 0.0  # fiyat cinsinden (ör. EURUSD için 0.0001 = 1 pip)
    # İşlem başı toplam maliyet (komisyon + swap tahmini), fiyat cinsinden. Ör. lot başı 7$
    # gidiş-dönüş komisyon EURUSD'de 0.00007'dir.
    commission: float = 0.0
    # Gecelik swap, fiyat cinsinden (+ alacak, - borç); çarşamba gecesi 3 kat sayılır
    swap_long: float = 0.0
    swap_short: float = 0.0
    # Bu kadar bar sonra pozisyon kapatılır (0 = kapalı; strateji kendi değerini verebilir)
    max_hold_bars: int = 0
    close_on_opposite: bool = True
    initial_equity: float = 10_000.0

    @classmethod
    def from_config(cls, cfg, spread: float = 0.0, commission: float = 0.0,
                    swap_long: float = 0.0, swap_short: float = 0.0):
        r = cfg.risk
        return cls(risk_pct=r.risk_per_trade_pct, sl_atr_mult=r.sl_atr_mult,
                   tp_atr_mult=r.tp_atr_mult, atr_period=r.atr_period, spread=spread,
                   commission=commission, swap_long=swap_long, swap_short=swap_short,
                   max_hold_bars=r.max_hold_bars, close_on_opposite=cfg.trading.close_on_opposite)


def rollovers(t0: int, t1: int) -> int:
    """t0'da açılıp t1'de kapanan pozisyonun ödediği swap gecesi sayısı.

    Swap pazartesi-cuma her gece alınır; hafta sonu için çarşamba gecesi 3 kat sayılır.
    """
    n = 0
    for day in range(int(t0) // 86400, int(t1) // 86400):
        weekday = (day + 3) % 7  # 1 Ocak 1970 perşembe; pazartesi = 0
        if weekday < 5:
            n += 3 if weekday == 2 else 1
    return n


def run_backtest(df: pd.DataFrame, strategy: Strategy, s: BacktestSettings) -> dict:
    df = df.reset_index(drop=True)
    sig = strategy.signals(df).to_numpy()
    atr = ind.atr(df, s.atr_period).to_numpy()
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    t = df["time"].to_numpy()
    n, sp = len(df), s.spread
    max_hold = strategy.max_hold_bars or s.max_hold_bars

    trades = []
    equity = s.initial_equity
    curve = [equity]
    pos = None  # dict(side, entry, sl, tp, sl_dist, i)

    def r_multiple(exit_price, swap=0.0):
        return ((exit_price - pos["entry"]) * pos["side"] - s.commission + swap) / pos["sl_dist"]

    def close(exit_price, i, reason):
        nonlocal equity, pos
        nights = rollovers(t[pos["i"]], t[i])
        r = r_multiple(exit_price, nights * (s.swap_long if pos["side"] > 0 else s.swap_short))
        money = equity * s.risk_pct / 100 * r
        equity += money
        trades.append({
            "side": "buy" if pos["side"] > 0 else "sell",
            "entry_time": int(t[pos["i"]]), "exit_time": int(t[i]),
            "entry": pos["entry"], "exit": exit_price, "r": round(r, 3),
            "profit": round(money, 2), "reason": reason,
        })
        pos = None

    def mark(i):
        """Bar içindeki en kötü fiyata göre varlık (açık pozisyonun zararı dahil)."""
        if pos is None or pos["i"] > i:
            return equity
        worst = l[i] if pos["side"] > 0 else h[i] + sp
        return equity + equity * s.risk_pct / 100 * r_multiple(worst)

    for i in range(strategy.warmup, n):
        # 1) Açık pozisyonun bu bar içinde SL/TP'ye değip değmediği
        if pos is not None and pos["i"] <= i:
            if pos["side"] > 0:  # alış BID ile kapanır
                if l[i] <= pos["sl"]:
                    close(min(pos["sl"], o[i]), i, "sl")
                elif h[i] >= pos["tp"]:
                    close(max(pos["tp"], o[i]), i, "tp")
            else:  # satış ASK ile kapanır
                if h[i] + sp >= pos["sl"]:
                    close(max(pos["sl"], o[i] + sp), i, "sl")
                elif l[i] + sp <= pos["tp"]:
                    close(min(pos["tp"], o[i] + sp), i, "tp")
        # Süre doldu: bar kapanışında çık
        if pos is not None and max_hold and i - pos["i"] + 1 >= max_hold:
            close(c[i] if pos["side"] > 0 else c[i] + sp, i, "time")

        curve.append(mark(i))
        if i == n - 1:
            break

        # 2) Bar kapanışındaki sinyale göre bir sonraki barın açılışında işlem
        side = int(sig[i])
        if pos is not None and side == -pos["side"] and s.close_on_opposite:
            close(o[i + 1] if pos["side"] > 0 else o[i + 1] + sp, i + 1, "signal")
        if pos is None and side != 0 and atr[i] > 0:  # NaN (ısınma) ve 0 ATR elenir
            entry = o[i + 1] + sp if side > 0 else o[i + 1]
            sl_dist = atr[i] * s.sl_atr_mult
            tp_dist = atr[i] * s.tp_atr_mult
            pos = {"side": side, "entry": entry, "sl_dist": sl_dist, "i": i + 1,
                   "sl": entry - side * sl_dist, "tp": entry + side * tp_dist}

    if pos is not None:
        close(c[-1] if pos["side"] > 0 else c[-1] + sp, n - 1, "end")
    curve.append(equity)

    return {"metrics": _metrics(trades, curve, s.initial_equity, df), "trades": trades}


def _metrics(trades, curve, initial, df) -> dict:
    rs = np.array([tr["r"] for tr in trades]) if trades else np.array([])
    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    dd = ((peak - curve) / peak).max() * 100 if len(curve) else 0.0
    gains, losses = rs[rs > 0].sum(), -rs[rs < 0].sum()
    pf = gains / losses if losses > 0 else (float("inf") if gains > 0 else 0.0)
    return {
        "bars": len(df),
        "from": int(df["time"].iloc[0]) if len(df) else 0,
        "to": int(df["time"].iloc[-1]) if len(df) else 0,
        "trades": len(trades),
        "win_rate_pct": round(float((rs > 0).mean() * 100), 1) if len(rs) else 0.0,
        "profit_factor": round(float(pf), 2) if np.isfinite(pf) else None,
        "avg_r": round(float(rs.mean()), 3) if len(rs) else 0.0,
        "net_return_pct": round(float((curve[-1] / initial - 1) * 100), 2),
        "max_drawdown_pct": round(float(dd), 2),
        "final_equity": round(float(curve[-1]), 2),
    }


def _score(m: dict, min_trades: int) -> float:
    """Optimizasyon skoru: getiri / düşüş. Az işlem yapan sonuçlar elenir."""
    if m["trades"] < min_trades:
        return -1e9
    return m["net_return_pct"] / max(m["max_drawdown_pct"], 1.0)


def compare(df: pd.DataFrame, s: BacktestSettings) -> list[dict]:
    """Tüm stratejileri varsayılan parametrelerle dener, en iyiden kötüye sıralar."""
    rows = []
    for name in STRATEGIES:
        strat = make_strategy(name)
        m = run_backtest(df, strat, s)["metrics"]
        rows.append({"strategy": name, "params": strat.params, "metrics": m})
    return sorted(rows, key=lambda r: _score(r["metrics"], 1), reverse=True)


def optimize(df: pd.DataFrame, name: str, s: BacktestSettings, train_ratio: float = 0.7,
             min_trades: int = 10, top: int = 5) -> dict:
    """Parametre taraması.

    Verinin ilk %70'inde (eğitim) en iyi parametreler aranır, sonra bu parametreler
    hiç görmedikleri son %30'da (test) denenir. Test sonucu eğitimden çok kötüyse
    strateji büyük ihtimalle geçmişe aşırı uydurulmuştur (overfitting).
    """
    cls = STRATEGIES[name]
    split = int(len(df) * train_ratio)
    train, test = df.iloc[:split], df.iloc[split:]
    keys = list(cls.param_grid)
    results = []
    for values in itertools.product(*(cls.param_grid[k] for k in keys)):
        params = dict(zip(keys, values))
        if name == "ema_trend" and params["fast"] >= params["slow"]:
            continue
        m = run_backtest(train, cls(params), s)["metrics"]
        results.append({"params": params, "train": m, "score": _score(m, min_trades)})
    results.sort(key=lambda r: r["score"], reverse=True)
    best = results[:top]
    for r in best:
        strat = cls(r["params"])
        # İndikatörler ısınsın diye test diliminin önüne eğitimin son `warmup` barı eklenir;
        # run_backtest ısınma barlarında işlem açmadığı için işlemler yine sadece test diliminde olur
        warm_test = df.iloc[max(split - strat.warmup, 0):]
        r["test"] = run_backtest(warm_test, strat, s)["metrics"]
        del r["score"]
    return {"strategy": name, "train_bars": len(train), "test_bars": len(test), "results": best}
