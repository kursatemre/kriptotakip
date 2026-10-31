"""Öğrenen bot: verileri günceller, tüm sembollerde araştırmayı çalıştırır ve her sembol için
seçilen stratejiyi learned.json'a yazar. Motor sadece saklı testi geçen ("aktif") sembollerde
yeni işlem açar.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from . import data, research
from .broker import Broker
from .config import Config

LEARNED_PATH = Path(__file__).resolve().parent.parent / "learned.json"


def load_learned(path: Path = LEARNED_PATH) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pick(candidates: list[dict]) -> dict:
    """Bir sembolün zaman dilimlerindeki sonuçlarından birini seçer: saklı testi geçenler önce,
    aralarından geliştirme dönemi t-istatistiği en yüksek olan (saklı test seçimde kullanılmaz)."""
    return max(candidates, key=lambda c: (c["active"], c["dev"]["t_stat"]))


def learn(broker: Broker, cfg: Config, path: Path | None = LEARNED_PATH, data_dir: Path = data.DATA_DIR,
          progress=print) -> dict:
    """path None ise sonuç diske yazılmaz (testler)."""
    lc = cfg.learning
    universe = lc.universe or broker.find_symbols("")
    per_symbol: dict[str, list[dict]] = {}
    researched, summaries = set(), {}
    for tf in lc.timeframes:
        progress(f"Veri güncelleniyor: {len(universe)} sembol, {tf}")
        data.download(broker, universe, tf, data_dir=data_dir, progress=progress)
        progress(f"Araştırma çalışıyor ({tf})")
        report = research.run(universe, tf, include_ml=lc.use_ml, max_cost_ratio=lc.max_cost_ratio,
                              max_loss_prob=lc.max_loss_prob_pct, data_dir=data_dir, progress=progress)
        summaries[tf] = report["summary"]
        researched |= set(report["results"])
        for symbol, res in report["results"].items():
            best = res["best"]
            if best:
                per_symbol.setdefault(symbol, []).append({
                    "timeframe": tf, "strategy": best["strategy"], "params": best["params"],
                    "active": res["passed"], "dev": best["dev"], "holdout": best["holdout"],
                    "cost_ratio": res["cost_ratio"], "mc": best["mc"], "hold_trades": best["hold_trades"],
                })
    assignments = {symbol: _pick(c) for symbol, c in per_symbol.items()}
    active = [a for a in assignments.values() if a["active"]]
    trades = sum(a["holdout"]["trades"] for a in active)
    # Aktif sembollerin saklı test işlemleri zaman sırasıyla tek portföy gibi
    portfolio = sorted((t for a in active for t in a["hold_trades"]), key=lambda t: t[0])
    # Bir sembol birden çok zaman diliminde denendiği için şans eseri aktif olma ihtimali de artar
    luck_expected = sum(1 - math.prod(1 - c["mc"]["luck_pass_prob"] / 100 for c in cands)
                        for cands in per_symbol.values())
    for a in assignments.values():
        del a["hold_trades"]
    learned = {
        "time": int(time.time()), "timeframes": list(lc.timeframes), "max_loss_prob_pct": lc.max_loss_prob_pct,
        "summary": {
            "passed": sorted(s for s, a in assignments.items() if a["active"]),
            "holdout_trades": trades,
            # Aktif seçimlerin saklı testteki işlem ağırlıklı ortalama R'si
            "holdout_avg_r": round(sum(a["holdout"]["avg_r"] * a["holdout"]["trades"] for a in active) / trades, 4)
            if trades else 0.0,
            "monte_carlo": research.monte_carlo([r for _, r in portfolio]),
            "holdout_from": portfolio[0][0] if portfolio else None,
            "luck_expected_active": round(luck_expected, 1),
            "by_timeframe": summaries,
        },
        "symbols_researched": len(researched), "assignments": assignments,
    }
    if path:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(learned, indent=1), encoding="utf-8")
        tmp.replace(path)
    names = [f"{s} {a['timeframe']}" for s, a in assignments.items() if a["active"]]
    progress(f"Öğrenme bitti: {len(names)} aktif sembol ({', '.join(names) or 'yok'})")
    return learned
