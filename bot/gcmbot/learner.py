"""Öğrenen bot: verileri günceller, tüm sembollerde araştırmayı çalıştırır ve her sembol için
seçilen stratejiyi learned.json'a yazar. Motor sadece saklı testi geçen ("aktif") sembollerde
yeni işlem açar.
"""

from __future__ import annotations

import json
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


def learn(broker: Broker, cfg: Config, path: Path | None = LEARNED_PATH, data_dir: Path = data.DATA_DIR,
          progress=print) -> dict:
    """path None ise sonuç diske yazılmaz (testler)."""
    tf = cfg.trading.timeframe
    lc = cfg.learning
    universe = lc.universe or broker.find_symbols("")
    progress(f"Veri güncelleniyor: {len(universe)} sembol, {tf}")
    data.download(broker, universe, tf, data_dir=data_dir, progress=progress)
    progress("Araştırma çalışıyor")
    report = research.run(universe, tf, include_ml=lc.use_ml, max_cost_ratio=lc.max_cost_ratio,
                          data_dir=data_dir, progress=progress)
    assignments = {}
    for symbol, res in report["results"].items():
        best = res["best"]
        if not best:
            continue
        assignments[symbol] = {
            "strategy": best["strategy"], "params": best["params"], "active": res["passed"],
            "dev": best["dev"], "holdout": best["holdout"], "cost_ratio": res["cost_ratio"],
        }
    learned = {
        "time": int(time.time()), "timeframe": tf, "summary": report["summary"],
        "symbols_researched": len(report["results"]), "skipped": len(report["skipped"]),
        "assignments": assignments,
    }
    if path:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(learned, indent=1), encoding="utf-8")
        tmp.replace(path)
    active = [s for s, a in assignments.items() if a["active"]]
    progress(f"Öğrenme bitti: {len(active)} aktif sembol ({', '.join(active) or 'yok'})")
    return learned
