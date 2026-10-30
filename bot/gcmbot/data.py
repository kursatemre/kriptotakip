"""Araştırma verisi: brokerdan geçmiş barları indirip diske (bot/data) kaydeder.

Her sembol/zaman dilimi için bir parquet dosyası tutulur; sonraki indirmelerde yeni barlar
eklenir. Sembollerin maliyet bilgisi (spread, swap, lot) data/symbols.json'a yazılır.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from . import indicators as ind
from .broker import Broker, BrokerError

log = logging.getLogger("gcmbot")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def bars_path(symbol: str, timeframe: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{symbol}_{timeframe}.parquet"


def load_bars(symbol: str, timeframe: str, data_dir: Path = DATA_DIR) -> pd.DataFrame | None:
    p = bars_path(symbol, timeframe, data_dir)
    return pd.read_parquet(p) if p.exists() else None


def load_symbols(data_dir: Path = DATA_DIR) -> dict[str, dict]:
    p = data_dir / "symbols.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _rates_with_retry(broker: Broker, symbol: str, timeframe: str, count: int, tries: int = 6) -> pd.DataFrame:
    # MT4 ilk istekte geçmişi indirmeye başlar ve "no history data" döner; biraz bekleyip tekrar dene
    for attempt in range(tries):
        try:
            return broker.rates(symbol, timeframe, count)
        except BrokerError:
            if attempt == tries - 1:
                raise
            time.sleep(1.5)
    raise AssertionError("ulaşılamaz")


def download(broker: Broker, symbols: list[str], timeframe: str, bars: int = 100_000,
             deep: bool = True, data_dir: Path = DATA_DIR, progress=print) -> dict[str, int]:
    """Sembollerin geçmişini indirir/günceller; sembol başına toplam bar sayısını döner."""
    data_dir.mkdir(parents=True, exist_ok=True)
    meta = load_symbols(data_dir)
    counts = {}
    for i, symbol in enumerate(symbols, 1):
        try:
            old = load_bars(symbol, timeframe, data_dir)
            # Derin geçmiş sadece ilk indirmede gerekir; sonra yeni barlar eklenir
            if deep and old is None and hasattr(broker, "load_history"):
                broker.load_history(symbol, timeframe)
            new = _rates_with_retry(broker, symbol, timeframe, bars)
            df = new if old is None else (
                pd.concat([old, new]).drop_duplicates("time", keep="last").sort_values("time")
                .reset_index(drop=True))
            df.to_parquet(bars_path(symbol, timeframe, data_dir), index=False)
            info = broker.symbol_info(symbol)
            bid, ask = broker.price(symbol)
            atr = float(ind.atr(df).iloc[-2000:].median()) if len(df) > 30 else float("nan")  # tipik oynaklık
            meta[symbol] = {**asdict(info), "spread": ask - bid, "atr_" + timeframe: atr,
                            "updated": int(time.time())}
            counts[symbol] = len(df)
            # Her sembolden sonra yaz: uzun indirme yarıda kesilirse inen veri kullanılabilsin
            (data_dir / "symbols.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            progress(f"[{i}/{len(symbols)}] {symbol} {timeframe}: {len(df)} bar")
        except Exception as e:  # bir sembolün hatası diğerlerini durdurmasın
            progress(f"[{i}/{len(symbols)}] {symbol}: HATA {e}")
    return counts
