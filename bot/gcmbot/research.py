"""Strateji araştırması: tüm sembollerde aday stratejileri aşırı uydurmaya karşı sıkı kurallarla dener.

Her sembol için:
1. Verinin son %25'i SAKLI TEST olarak ayrılır; seçimde hiç kullanılmaz.
2. Her aday (strateji + parametre) tüm veride bir kez çalıştırılır (stratejiler nedenseldir,
   ML modeli yürüyen pencereyle eğitilir); işlemler giriş zamanına göre geliştirme/saklı
   test diye ayrılır. Sonuçlar R cinsindendir (1R = riske edilen tutar), spread ve swap dahil.
3. Geliştirme dönemi 4 parçaya bölünür. Aday ancak en az 3 parçada kârlıysa ve yeterli
   işlem yaptıysa seçilebilir; uygun olanlardan t-istatistiği en yüksek olan seçilir.
4. Seçilen aday saklı testte bir kez ölçülür. Geçme şartı: yeterli işlem ve PF eşiği.
5. Monte Carlo: saklı test işlemleri yeniden örneklenir; zarar olasılığı, kötü senaryodaki düşüş
   ve hiç üstünlük yokken eşiği şans eseri geçme olasılığı hesaplanır.

Çok sayıda aday denendiği için bazı adaylar geliştirme döneminde şans eseri iyi görünür; asıl
ölçü saklı testtir. Saklı testi geçenler de kısmen şanslı olabilir: geçen sayısı, şans eseri
beklenen sayıdan belirgin fazla değilse sonuç şansla açıklanabilir.
"""

from __future__ import annotations

import itertools
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .backtest import BacktestSettings, run_backtest
from .strategies import STRATEGIES, make_strategy

HOLDOUT_FRAC = 0.25
FOLDS = 4
MIN_DEV_TRADES = 40
MIN_POSITIVE_FOLDS = 3
MIN_HOLDOUT_TRADES = 20
MIN_HOLDOUT_PF = 1.1
MC_RUNS = 2000


def candidates(include_ml: bool = True) -> list[tuple[str, dict]]:
    out = []
    for name, cls in STRATEGIES.items():
        if name == "ml_boost" and not include_ml:
            continue
        keys = list(cls.param_grid)
        for values in itertools.product(*(cls.param_grid[k] for k in keys)):
            params = dict(zip(keys, values))
            if name == "ema_trend" and params["fast"] >= params["slow"]:
                continue
            out.append((name, params))
    return out


def r_stats(rs) -> dict:
    rs = np.asarray(rs, dtype=float)
    n = len(rs)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0, "pf": 0.0, "max_dd_r": 0.0,
                "t_stat": 0.0}
    gains, losses = rs[rs > 0].sum(), -rs[rs < 0].sum()
    pf = gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)
    cum = np.concatenate([[0.0], np.cumsum(rs)])
    sd = rs.std(ddof=1) if n > 1 else 0.0
    return {
        "trades": n,
        "win_rate": round(float((rs > 0).mean() * 100), 1),
        "avg_r": round(float(rs.mean()), 4),
        "total_r": round(float(rs.sum()), 2),
        "pf": round(float(pf), 3) if math.isfinite(pf) else None,
        "max_dd_r": round(float((np.maximum.accumulate(cum) - cum).max()), 2),
        "t_stat": round(float(rs.mean() / sd * math.sqrt(n)), 2) if sd > 0 else 0.0,
    }


def _pf(rs: np.ndarray) -> np.ndarray:
    gains = np.where(rs > 0, rs, 0).sum(axis=-1)
    losses = -np.where(rs < 0, rs, 0).sum(axis=-1)
    return np.divide(gains, losses, out=np.full(gains.shape, np.inf), where=losses > 0)


def monte_carlo(rs, runs: int = MC_RUNS, seed: int = 0) -> dict:
    """İşlemleri yerine koyarak yeniden örnekler (bootstrap).

    loss_prob: ortalama R'nin ≤ 0 çıktığı senaryoların yüzdesi.
    dd_p95_r: senaryoların %95'inde aşılmayan en büyük düşüş (R; %1 riskle ≈ hesabın yüzdesi).
    luck_pass_prob: işlemler ortalaması 0 olacak şekilde kaydırıldığında (yani hiç üstünlük yokken)
    saklı test eşiğini (işlem sayısı + PF) geçen senaryoların yüzdesi.
    """
    rs = np.asarray(rs, dtype=float)
    n = len(rs)
    if n < 2:
        return {"runs": 0, "loss_prob": 100.0, "dd_p95_r": 0.0, "luck_pass_prob": 0.0}
    boot = rs[np.random.default_rng(seed).integers(0, n, size=(runs, n))]
    cum = np.cumsum(boot, axis=1)
    dd = (np.maximum.accumulate(np.maximum(cum, 0), axis=1) - cum).max(axis=1)
    luck = n >= MIN_HOLDOUT_TRADES and _pf(boot - rs.mean()) >= MIN_HOLDOUT_PF
    return {
        "runs": runs,
        "loss_prob": round(float((boot.mean(axis=1) <= 0).mean() * 100), 1),
        "dd_p95_r": round(float(np.percentile(dd, 95)), 1),
        "luck_pass_prob": round(float(np.mean(luck) * 100), 1),
    }


def cost_settings(meta: dict, price: float = 0.0, sl_atr_mult: float = 1.5,
                  tp_atr_mult: float = 3.0) -> BacktestSettings:
    """Sembolün spread'i ve swap'ı ile backtest ayarları (`price`: swap tipi 2 için güncel fiyat)."""
    swap_type = meta.get("swap_type", 0)
    if swap_type == 0:  # point cinsinden
        point = meta.get("point", 0.0)
        swap_long, swap_short = meta.get("swap_long", 0.0) * point, meta.get("swap_short", 0.0) * point
    elif swap_type == 2:  # yıllık faiz yüzdesi (hisseler): gecelik fiyat karşılığı
        swap_long = price * meta.get("swap_long", 0.0) / 100 / 360
        swap_short = price * meta.get("swap_short", 0.0) / 100 / 360
    else:  # para cinsinden (lot başı): yaklaşık olarak fiyata çevir
        per_price = meta["tick_value"] / meta["tick_size"] if meta.get("tick_size") else 0.0
        swap_long = meta.get("swap_long", 0.0) / per_price if per_price else 0.0
        swap_short = meta.get("swap_short", 0.0) / per_price if per_price else 0.0
    return BacktestSettings(sl_atr_mult=sl_atr_mult, tp_atr_mult=tp_atr_mult, spread=meta.get("spread", 0.0),
                            swap_long=swap_long, swap_short=swap_short)


def evaluate_symbol(df: pd.DataFrame, meta: dict, cands: list[tuple[str, dict]],
                    holdout_frac: float = HOLDOUT_FRAC) -> dict:
    df = df.reset_index(drop=True)
    times = df["time"].to_numpy()
    split_time = int(times[int(len(df) * (1 - holdout_frac))])
    settings = cost_settings(meta, price=float(df["close"].iloc[-1]))
    rows = []
    for name, params in cands:
        strat = make_strategy(name, params)
        if len(df) < strat.warmup + 1000:
            continue
        trades = run_backtest(df, strat, settings)["trades"]
        dev = [tr for tr in trades if tr["entry_time"] < split_time]
        hold = [tr for tr in trades if tr["entry_time"] >= split_time]
        start = int(times[strat.warmup])
        edges = np.linspace(start, split_time, FOLDS + 1)
        fold_r = [round(sum(tr["r"] for tr in dev if edges[k] <= tr["entry_time"] < edges[k + 1]), 2)
                  for k in range(FOLDS)]
        rows.append({
            "strategy": name, "params": strat.params,
            "dev": r_stats([tr["r"] for tr in dev]), "folds": fold_r,
            "positive_folds": int(sum(f > 0 for f in fold_r)),
            "holdout": r_stats([tr["r"] for tr in hold]),
            "_hold": [[int(tr["entry_time"]), round(float(tr["r"]), 4)] for tr in hold],
        })
    # Seçim SADECE geliştirme dönemine göre
    eligible = [r for r in rows if r["dev"]["trades"] >= MIN_DEV_TRADES and r["dev"]["avg_r"] > 0
                and r["positive_folds"] >= MIN_POSITIVE_FOLDS]
    best = max(eligible, key=lambda r: r["dev"]["t_stat"]) if eligible else None
    if best:
        best["hold_trades"] = best.pop("_hold")  # [giriş zamanı, R]: portföy Monte Carlo'su için
        best["mc"] = monte_carlo([r for _, r in best["hold_trades"]])
    passed = bool(best) and best["holdout"]["trades"] >= MIN_HOLDOUT_TRADES and (
        best["holdout"]["pf"] is None or best["holdout"]["pf"] >= MIN_HOLDOUT_PF)
    years = (times[-1] - split_time) / (365.25 * 86400)
    return {
        "bars": len(df), "from": int(times[0]), "split": split_time, "to": int(times[-1]),
        "spread": meta.get("spread"), "candidates": len(rows), "eligible": len(eligible),
        "best": best, "passed": passed, "holdout_years": round(float(years), 2),
        # Tanı amaçlı: TÜM adayların saklı testteki ortalaması (seçimde kullanılmaz)
        "all_holdout_avg_r": round(float(np.mean([r["holdout"]["avg_r"] for r in rows])), 4) if rows else 0.0,
    }


def cost_ratio(meta: dict, timeframe: str) -> float:
    atr = meta.get("atr_" + timeframe) or 0.0
    return meta.get("spread", 0.0) / atr if atr > 0 else math.inf


def run(symbols: list[str], timeframe: str, include_ml: bool = True, max_cost_ratio: float = 0.2,
        data_dir: Path = data.DATA_DIR, progress=print) -> dict:
    metas = data.load_symbols(data_dir)
    cands = candidates(include_ml)
    results, skipped = {}, {}
    for i, symbol in enumerate(symbols, 1):
        df, meta = data.load_bars(symbol, timeframe, data_dir), metas.get(symbol)
        if df is None or meta is None:
            skipped[symbol] = "veri yok"
            continue
        ratio = cost_ratio(meta, timeframe)
        if ratio > max_cost_ratio:
            skipped[symbol] = f"maliyet yüksek (spread/ATR {ratio:.2f})"
            continue
        t0 = time.time()
        res = evaluate_symbol(df, meta, cands)
        res["cost_ratio"] = round(ratio, 3)
        results[symbol] = res
        b = res["best"]
        progress(f"[{i}/{len(symbols)}] {symbol}: {res['bars']} bar, {res['eligible']}/{res['candidates']} uygun aday"
                 + (f", seçilen {b['strategy']} → saklı test {b['holdout']['trades']} işlem, "
                    f"PF {b['holdout']['pf']}, ort {b['holdout']['avg_r']:+.3f}R"
                    f" {'GEÇTİ' if res['passed'] else 'kaldı'}" if b else ", uygun aday yok")
                 + f" ({time.time() - t0:.0f} sn)")
    report = {"timeframe": timeframe, "created": int(time.time()), "candidates": len(cands),
              "results": results, "skipped": skipped, "summary": summarize(results)}
    (data_dir / f"research_{timeframe}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def summarize(results: dict) -> dict:
    selected = {s: r for s, r in results.items() if r["best"]}
    hold = [r["best"]["holdout"] for r in selected.values()]
    total_trades = sum(h["trades"] for h in hold)
    return {
        "symbols": len(results),
        "with_selection": len(selected),
        "passed": sorted(s for s, r in results.items() if r["passed"]),
        "holdout_trades": total_trades,
        # Seçilen adayların saklı testteki işlem ağırlıklı ortalama R'si: gerçek bir üstünlük varsa > 0
        "holdout_avg_r": round(sum(h["avg_r"] * h["trades"] for h in hold) / total_trades, 4) if total_trades else 0.0,
        "holdout_positive": sum(h["avg_r"] > 0 for h in hold),
        # Hiç üstünlük olmasaydı şans eseri geçmesi beklenen sembol sayısı (Monte Carlo)
        "luck_expected_passes": round(sum(r["best"]["mc"]["luck_pass_prob"] for r in selected.values()) / 100, 1),
    }
