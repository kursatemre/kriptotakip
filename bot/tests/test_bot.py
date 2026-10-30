import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from gcmbot import indicators as ind
from gcmbot.api import create_app
from gcmbot.backtest import BacktestSettings, compare, optimize, run_backtest
from gcmbot.broker import BrokerError, FakeBroker
from gcmbot.config import Config
from gcmbot.engine import Engine
from gcmbot.risk import SymbolInfo, position_size, stop_levels
from gcmbot.strategies import STRATEGIES, Strategy, make_strategy

EURUSD = SymbolInfo("EURUSD", point=0.00001, digits=5, tick_size=0.00001, tick_value=1.0,
                    volume_min=0.01, volume_max=100, volume_step=0.01)


def bars(closes, spread_hl=0.0):
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({
        "time": np.arange(len(c)) * 3600, "open": o,
        "high": np.maximum(o, c) + spread_hl, "low": np.minimum(o, c) - spread_hl, "close": c,
    })


# --------------------------------------------------------------- indikatörler
def test_rsi_bounds_and_trend():
    up = pd.Series(np.linspace(1, 2, 100))
    assert ind.rsi(up).iloc[-1] == 100
    noisy = pd.Series(np.random.default_rng(0).normal(0, 1, 500).cumsum() + 100)
    r = ind.rsi(noisy).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_indicators_are_causal():
    df = FakeBroker(bar_seconds=None).rates("EURUSD", "H1", 600)
    full = make_strategy("ema_trend").signals(df)
    part = make_strategy("ema_trend").signals(df.iloc[:400])
    # İlk 400 barın sinyalleri sonraki verilerden etkilenmemeli
    assert (full.iloc[:400].to_numpy() == part.to_numpy()).all()


# ---------------------------------------------------------------- stratejiler
@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_produce_valid_signals(name):
    df = FakeBroker(bar_seconds=None, history_bars=3000).rates("EURUSD", "H1", 3000)
    s = make_strategy(name).signals(df)
    assert set(s.unique()) <= {-1, 0, 1}
    assert (s != 0).sum() > 0


def test_unknown_param_rejected():
    with pytest.raises(ValueError):
        make_strategy("ema_trend", {"nope": 1})


def test_ema_cross_buy_signal():
    closes = [1.0] * 250 + list(np.linspace(1.0, 1.2, 60))
    sig = make_strategy("ema_trend", {"fast": 5, "slow": 20, "trend": 50}).signals(bars(closes))
    assert sig.iloc[250:].max() == 1
    assert sig.min() >= 0


# ----------------------------------------------------------------------- risk
def test_position_size_risks_expected_amount():
    vol = position_size(10_000, 1.0, 0.0020, EURUSD)  # 20 pip stop, 100$ risk
    assert vol == pytest.approx(0.5)
    assert position_size(100, 0.1, 0.0050, EURUSD) == 0.0  # min lottan küçük -> işlem yok


def test_stop_levels():
    sl, tp = stop_levels(1, 1.1, 0.001, 1.5, 3.0, EURUSD)
    assert sl == pytest.approx(1.0985) and tp == pytest.approx(1.103)
    sl, tp = stop_levels(-1, 1.1, 0.001, 1.5, 3.0, EURUSD)
    assert sl > 1.1 > tp


# ------------------------------------------------------------------- backtest
class OneShot(Strategy):
    """Belirli barda tek bir sinyal veren test stratejisi."""
    name = "oneshot"
    default_params = {"at": 20, "side": 1}
    warmup = 15

    def signals(self, df):
        s = pd.Series(0, index=df.index)
        s.iloc[self.params["at"]] = self.params["side"]
        return s


def test_backtest_tp_hit():
    closes = [1.0] * 30 + [1.0 + 0.001 * i for i in range(1, 60)]
    res = run_backtest(bars(closes, 0.0005), OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2))
    assert res["trades"][0]["reason"] == "tp"
    assert res["trades"][0]["r"] > 1.5
    assert res["metrics"]["net_return_pct"] > 0


def test_backtest_sl_hit_loses_one_r():
    closes = [1.0] * 30 + [1.0 - 0.001 * i for i in range(1, 60)]
    res = run_backtest(bars(closes, 0.0005), OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2))
    t = res["trades"][0]
    assert t["reason"] == "sl" and t["r"] == pytest.approx(-1, abs=0.01)
    assert res["metrics"]["net_return_pct"] == pytest.approx(-1, abs=0.01)


def test_compare_and_optimize_run():
    df = FakeBroker(bar_seconds=None, history_bars=3000).rates("EURUSD", "H1", 3000)
    rows = compare(df, BacktestSettings(spread=0.0001))
    assert {r["strategy"] for r in rows} == set(STRATEGIES)
    opt = optimize(df, "donchian_breakout", BacktestSettings())
    assert opt["results"] and "test" in opt["results"][0]


# --------------------------------------------------------------------- motor
def make_engine(**trading):
    cfg = Config(broker="fake")
    cfg.api.token = "t"
    cfg.trading.symbols = ["EURUSD", "XAUUSD"]
    cfg.trading.strategy = "donchian_breakout"
    for k, v in trading.items():
        setattr(cfg.trading, k, v)
    broker = FakeBroker(bar_seconds=None, seed=1)
    return Engine(cfg, broker), broker


def test_engine_trades_only_when_running():
    engine, broker = make_engine()
    engine.tick()
    for _ in range(100):
        broker.step()
        engine.tick()
    assert broker.positions(engine.cfg.trading.magic) == [] and broker.history(engine.cfg.trading.magic, 30) == []

    engine.set_running(True)
    for _ in range(300):
        broker.step()
        engine.tick()
    magic = engine.cfg.trading.magic
    assert len(broker.positions(magic)) + len(broker.history(magic, 30)) > 0
    # Sembol başına en fazla 1 pozisyon
    syms = [p.symbol for p in broker.positions(magic)]
    assert len(syms) == len(set(syms))


def test_engine_refuses_live_account():
    engine, broker = make_engine()
    real = broker.account
    broker.account = lambda: {**real(), "is_demo": False}
    with pytest.raises(BrokerError, match="DEMO"):
        engine.set_running(True)
    assert not engine.running


def test_engine_daily_loss_halt():
    engine, broker = make_engine()
    engine.tick()
    broker.balance -= 500  # %5 zarar
    engine.tick()
    assert "Günlük zarar" in engine.halted_reason


def test_apply_settings_validates():
    engine, _ = make_engine()
    with pytest.raises(Exception):
        engine.apply_settings(trading={"timeframe": "X9"})
    with pytest.raises(ValueError):
        engine.apply_settings(trading={"strategy": "yok"})
    engine.apply_settings(trading={"strategy": "rsi_pullback", "params": {"period": 7}})
    assert engine.strategy.params["period"] == 7 and engine.strategy.params["trend"] == 200


# ------------------------------------------------------------------------ API
@pytest.fixture
def client():
    engine, _ = make_engine()
    return TestClient(create_app(engine))


H = {"Authorization": "Bearer t"}


def test_api_auth(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    assert client.get("/api/status", headers=H).json()["account"]["is_demo"] is True


def test_api_flow(client):
    assert client.post("/api/bot/start", headers=H).json()["running"] is True
    assert client.post("/api/bot/stop", headers=H).json()["running"] is False
    assert client.get("/api/strategies", headers=H).json()["strategies"]
    r = client.put("/api/settings", headers=H, json={"risk": {"risk_per_trade_pct": 99}})
    assert r.status_code == 400
    r = client.put("/api/settings", headers=H, json={"trading": {"strategy": "ema_trend", "symbols": ["EURUSD"]}})
    assert r.status_code == 200 and r.json()["trading"]["symbols"] == ["EURUSD"]
    r = client.post("/api/backtest", headers=H, json={"symbol": "EURUSD", "bars": 1000, "mode": "compare"})
    assert r.status_code == 200 and len(r.json()["results"]) == len(STRATEGIES)
    assert client.post("/api/positions/1/close", headers=H).status_code == 400
    assert client.post("/api/positions/close-all", headers=H).json() == {"closed": 0}
    assert client.get("/api/events", headers=H).json()
