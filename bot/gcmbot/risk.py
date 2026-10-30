"""Risk yönetimi: lot hesabı ve stop/hedef seviyeleri."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SymbolInfo:
    name: str
    point: float
    digits: int
    tick_size: float
    tick_value: float  # 1 lotta, fiyat tick_size kadar oynarsa hesap para birimi cinsinden kâr/zarar
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int = 0  # brokerın izin verdiği minimum stop mesafesi (point)


def stop_levels(side: int, entry: float, atr_value: float, sl_mult: float, tp_mult: float,
                info: SymbolInfo) -> tuple[float, float]:
    """ATR tabanlı stop-loss ve take-profit seviyeleri."""
    min_dist = (info.stops_level + 1) * info.point
    sl_dist = max(atr_value * sl_mult, min_dist)
    tp_dist = max(atr_value * tp_mult, min_dist)
    if side > 0:
        sl, tp = entry - sl_dist, entry + tp_dist
    else:
        sl, tp = entry + sl_dist, entry - tp_dist
    return round(sl, info.digits), round(tp, info.digits)


def position_size(equity: float, risk_pct: float, sl_distance: float, info: SymbolInfo) -> float:
    """Stop olursa sermayenin risk_pct%'i kaybedilecek şekilde lot hesaplar.

    Hesaplanan lot brokerın minimum lotundan küçükse 0 döner (işlem açılmaz),
    böylece istenenden fazla risk alınmaz.
    """
    if sl_distance <= 0 or info.tick_size <= 0 or info.tick_value <= 0:
        return 0.0
    risk_money = equity * risk_pct / 100
    loss_per_lot = sl_distance / info.tick_size * info.tick_value
    raw = risk_money / loss_per_lot
    steps = math.floor(raw / info.volume_step + 1e-9)
    volume = round(steps * info.volume_step, 8)
    if volume < info.volume_min:
        return 0.0
    return min(volume, info.volume_max)
