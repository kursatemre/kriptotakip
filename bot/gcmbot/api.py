"""Mobil uygulamanın konuştuğu REST API (FastAPI).

Tüm uç noktalar (health hariç) `Authorization: Bearer <token>` başlığı ister.
Token config.json içindeki api.token değeridir.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backtest import BacktestSettings, compare, optimize, run_backtest
from .broker import BrokerError
from .config import TIMEFRAMES
from .crypto import CryptoError, CryptoPrices
from .engine import Engine
from .strategies import STRATEGIES, describe_strategies, make_strategy


class SettingsIn(BaseModel):
    trading: dict | None = None
    risk: dict | None = None
    learning: dict | None = None


class BacktestIn(BaseModel):
    symbol: str
    timeframe: str = "H1"
    bars: int = Field(5000, ge=300, le=100_000)
    mode: str = "single"  # single | compare | optimize
    strategy: str = "ema_trend"
    params: dict = Field(default_factory=dict)
    # Boşsa anlık spread kullanılır (hafta sonu/haber anında yanıltıcı olabilir)
    spread: float | None = Field(None, ge=0)
    commission: float = Field(0.0, ge=0)  # işlem başı maliyet, fiyat cinsinden


def create_app(engine: Engine, web_dir: Path | None = None, crypto: CryptoPrices | None = None) -> FastAPI:
    app = FastAPI(title="GCM Bot API")
    crypto = crypto or CryptoPrices()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def auth(request: Request):
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(token, engine.cfg.api.token):
            raise HTTPException(401, "Geçersiz token")

    @app.exception_handler(BrokerError)
    async def broker_error(_, exc: BrokerError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    api = [Depends(auth)]

    @app.get("/api/status", dependencies=api)
    def status():
        return engine.status()

    @app.post("/api/bot/start", dependencies=api)
    def start():
        engine.set_running(True)
        return engine.status()

    @app.post("/api/bot/stop", dependencies=api)
    def stop():
        engine.set_running(False)
        return engine.status()

    @app.get("/api/positions", dependencies=api)
    def positions():
        return [p.to_dict() for p in engine.broker.positions(engine.cfg.trading.magic)]

    @app.post("/api/positions/{ticket}/close", dependencies=api)
    def close_position(ticket: int):
        # Sadece botun açtığı pozisyonlar: MT5'te elle açılan işlemlere dokunulmaz
        mine = {p.ticket for p in engine.broker.positions(engine.cfg.trading.magic)}
        if ticket not in mine:
            raise HTTPException(404, f"#{ticket} botun açtığı açık bir pozisyon değil")
        engine.broker.close_position(ticket)
        engine.event("info", f"#{ticket} uygulamadan elle kapatıldı", notify=True)
        return {"ok": True}

    @app.post("/api/positions/close-all", dependencies=api)
    def close_all():
        closed = 0
        for p in engine.broker.positions(engine.cfg.trading.magic):
            engine.broker.close_position(p.ticket)
            closed += 1
        engine.event("warn", f"Tüm pozisyonlar kapatıldı ({closed} adet)", notify=True)
        return {"closed": closed}

    @app.get("/api/history", dependencies=api)
    def history(days: int = 30):
        return engine.broker.history(engine.cfg.trading.magic, days)

    @app.get("/api/events", dependencies=api)
    def events(limit: int = 100):
        return list(engine.events)[:limit]

    @app.get("/api/learning", dependencies=api)
    def learning():
        return engine.learning_status()

    @app.post("/api/learn", dependencies=api)
    def learn():
        started = engine.learn_now()
        return {"started": started, **engine.learning_status()}

    @app.get("/api/crypto", dependencies=api)
    def crypto_prices():
        c = engine.cfg.crypto
        try:
            return crypto.get(c.coins, c.currency)
        except CryptoError as e:
            raise HTTPException(502, str(e)) from e

    @app.get("/api/strategies", dependencies=api)
    def strategies():
        return {"strategies": describe_strategies(), "timeframes": list(TIMEFRAMES)}

    @app.put("/api/settings", dependencies=api)
    def settings(body: SettingsIn):
        try:
            engine.apply_settings(body.trading, body.risk, body.learning)
        except Exception as e:  # pydantic ValidationError dahil
            raise HTTPException(400, str(e)) from e
        return engine.status()

    @app.post("/api/backtest", dependencies=api)
    def backtest(body: BacktestIn):
        tf = body.timeframe.upper()
        if tf not in TIMEFRAMES:
            raise HTTPException(400, f"Geçersiz zaman dilimi: {tf}")
        if body.strategy not in STRATEGIES:
            raise HTTPException(400, f"Bilinmeyen strateji: {body.strategy}")
        df = engine.broker.rates(body.symbol, tf, body.bars)
        spread = body.spread
        if spread is None:
            bid, ask = engine.broker.price(body.symbol)
            spread = max(ask - bid, 0)
        s = BacktestSettings.from_config(engine.cfg, spread=spread, commission=body.commission)
        if body.mode == "compare":
            return {"mode": "compare", "results": compare(df, s)}
        if body.mode == "optimize":
            return {"mode": "optimize", **optimize(df, body.strategy, s)}
        res = run_backtest(df, make_strategy(body.strategy, body.params), s)
        return {"mode": "single", "metrics": res["metrics"], "trades": res["trades"][-50:]}

    # Flutter web derlemesi varsa aynı adresten servis et (iPhone'da Safari'den açılabilir)
    if web_dir and web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app
