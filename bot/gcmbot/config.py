"""Bot ayarları: config.json okunur/yazılır, pydantic ile doğrulanır."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


class MT5Settings(BaseModel):
    login: int = 0
    password: str = ""
    server: str = ""
    # Boş bırakılırsa MetaTrader5 kütüphanesi kurulu terminali kendisi bulur
    path: str = ""


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    token: str = ""


class TelegramSettings(BaseModel):
    bot_token: str = ""
    chat_id: str = ""


class TradingSettings(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["EURUSD"])
    timeframe: str = "H1"
    strategy: str = "ema_trend"
    params: dict = Field(default_factory=dict)
    magic: int = 20261030
    poll_seconds: int = Field(10, ge=1, le=300)
    close_on_opposite: bool = True

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v):
        v = v.upper()
        if v not in TIMEFRAMES:
            raise ValueError(f"Geçersiz zaman dilimi: {v}. Mevcut: {', '.join(TIMEFRAMES)}")
        return v

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v):
        v = [s.strip() for s in v if s.strip()]
        if not v:
            raise ValueError("En az bir sembol gerekli")
        return v


class RiskSettings(BaseModel):
    risk_per_trade_pct: float = Field(1.0, gt=0, le=5)
    sl_atr_mult: float = Field(1.5, gt=0)
    tp_atr_mult: float = Field(3.0, gt=0)
    atr_period: int = Field(14, ge=2)
    max_open_positions: int = Field(3, ge=1)
    max_daily_loss_pct: float = Field(3.0, gt=0, le=50)


class Config(BaseModel):
    broker: Literal["mt5", "fake"] = "mt5"
    # GÜVENLİK: false iken bot gerçek (canlı) hesapta emir göndermeyi REDDEDER
    allow_live: bool = False
    mt5: MT5Settings = Field(default_factory=MT5Settings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)


def load_config(path: Path) -> Config:
    if path.exists():
        cfg = Config.model_validate(json.loads(path.read_text(encoding="utf-8")))
    else:
        cfg = Config()
    if not cfg.api.token:
        cfg.api.token = secrets.token_urlsafe(24)
        save_config(cfg, path)
    return cfg


def save_config(cfg: Config, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
