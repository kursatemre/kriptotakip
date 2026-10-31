import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from gcmbot import indicators as ind
from gcmbot.api import create_app
from gcmbot.backtest import BacktestSettings, compare, optimize, run_backtest
from gcmbot.broker import BrokerError, FakeBroker
from gcmbot.config import Config
from gcmbot.crypto import CACHE_SECONDS, CryptoPrices
from gcmbot.engine import MAX_ATTEMPTS, Engine
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
@pytest.mark.parametrize("name", [n for n in STRATEGIES if n != "ml_boost"])
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
    # Tek işlem kazanmış olsa da TP'den önce açık pozisyon ~0.5R ezildi: düşüşe yansımalı
    assert 0 < res["metrics"]["max_drawdown_pct"] < 1


def test_backtest_commission_reduces_r():
    closes = [1.0] * 30 + [1.0 + 0.001 * i for i in range(1, 60)]
    df = bars(closes, 0.0005)
    free = run_backtest(df, OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2))["trades"][0]
    paid = run_backtest(df, OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2,
                                                        commission=0.0002))["trades"][0]
    assert paid["r"] == pytest.approx(free["r"] - 0.2, abs=0.01)


def test_backtest_sl_hit_loses_one_r():
    closes = [1.0] * 30 + [1.0 - 0.001 * i for i in range(1, 60)]
    res = run_backtest(bars(closes, 0.0005), OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2))
    t = res["trades"][0]
    assert t["reason"] == "sl" and t["r"] == pytest.approx(-1, abs=0.01)
    assert res["metrics"]["net_return_pct"] == pytest.approx(-1, abs=0.01)


def test_rollovers_count_weekday_nights_with_wednesday_triple():
    from gcmbot.backtest import rollovers
    monday = 4 * 86400  # 5 Ocak 1970 pazartesi
    assert rollovers(monday, monday + 3600) == 0  # aynı gün
    assert rollovers(monday, monday + 86400) == 1
    assert rollovers(monday + 2 * 86400, monday + 3 * 86400) == 3  # çarşamba gecesi
    assert rollovers(monday + 4 * 86400, monday + 7 * 86400) == 1  # cuma → pazartesi
    assert rollovers(monday, monday + 7 * 86400) == 7


def test_backtest_time_exit_and_swap():
    closes = [1.0] * 30 + [1.0 + 0.00001 * i for i in range(1, 300)]  # TP/SL'ye uzak, yavaş yükseliş
    df = bars(closes, 0.0005)
    df["time"] = 4 * 86400 + np.arange(len(df)) * 3600
    base = BacktestSettings(sl_atr_mult=1, tp_atr_mult=2, max_hold_bars=48)
    tr = run_backtest(df, OneShot(), base)["trades"][0]
    assert tr["reason"] == "time" and tr["exit_time"] - tr["entry_time"] == 47 * 3600
    paid = run_backtest(df, OneShot(), BacktestSettings(sl_atr_mult=1, tp_atr_mult=2, max_hold_bars=48,
                                                        swap_long=-0.0001))["trades"][0]
    assert paid["r"] < tr["r"]


def test_ml_labels():
    from gcmbot.ml import barrier_labels
    up = bars(np.linspace(1.0, 1.5, 300), 0.0005)
    yl, ys = barrier_labels(up, 1.5, 3.0, 50)
    valid = ~np.isnan(yl)
    assert valid.sum() > 100 and yl[valid][20:].mean() > 0.9 and ys[valid][20:].mean() < 0.1
    assert np.isnan(yl[-10:]).all()  # geleceği yetmeyen barlar etiketlenmez


def test_ml_has_no_lookahead():
    df = FakeBroker(bar_seconds=None, history_bars=1600).rates("EURUSD", "H1", 1600)
    params = {"train_bars": 600, "retrain": 100, "horizon": 10, "threshold": 0.3}
    full = make_strategy("ml_boost", params).signals(df)
    part = make_strategy("ml_boost", params).signals(df.iloc[:1300])
    assert (full != 0).sum() > 0
    assert (full.iloc[:1300].to_numpy() == part.to_numpy()).all()


def test_compare_and_optimize_run():
    df = FakeBroker(bar_seconds=None, history_bars=3000).rates("EURUSD", "H1", 3000)
    rows = compare(df, BacktestSettings(spread=0.0001))
    assert {r["strategy"] for r in rows} == set(STRATEGIES)
    opt = optimize(df, "donchian_breakout", BacktestSettings())
    assert opt["results"] and "test" in opt["results"][0]


# --------------------------------------------------------------------- motor
def make_engine(state_path=None, broker=None, **trading):
    cfg = Config(broker="fake")
    cfg.api.token = "t"
    cfg.trading.symbols = ["EURUSD", "XAUUSD"]
    cfg.trading.strategy = "donchian_breakout"
    for k, v in trading.items():
        setattr(cfg.trading, k, v)
    broker = broker or FakeBroker(bar_seconds=None, seed=1)
    return Engine(cfg, broker, state_path=state_path), broker


class Scripted(Strategy):
    """Her sinyal hesaplamasında sıradaki değeri döndüren test stratejisi."""
    name = "scripted"
    warmup = 5

    def __init__(self, seq):
        super().__init__()
        self.seq = list(seq)

    def last_signal(self, df):
        return self.seq.pop(0) if self.seq else 0


def scripted_engine(signals, **trading):
    engine, broker = make_engine(symbols=["EURUSD"], **trading)
    engine.strategy = Scripted(signals)
    engine.set_running(True)
    engine.tick()  # ilk tur: mevcut bar "görülmüş" sayılır
    return engine, broker


def next_bar(engine, broker):
    broker.step()
    engine.tick()


def freeze_stops(broker):
    """Sahte brokerdaki pozisyonların SL/TP'si test sırasında tetiklenmesin."""
    for p in broker._positions.values():
        p["sl"], p["tp"] = (0.0, 1e9) if p["side"] > 0 else (1e9, 0.0)


def fail(*_a, **_k):
    raise BrokerError("requote")


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
    # Parametre verilmeden strateji değişirse eskinin parametreleri taşınmaz, varsayılanlar gelir
    engine.apply_settings(trading={"strategy": "donchian_breakout"})
    assert engine.strategy.params == {"period": 20}


def test_magic_cannot_be_changed_from_api():
    engine, _ = make_engine()
    with pytest.raises(ValueError, match="magic"):
        engine.apply_settings(trading={"magic": 1})
    engine.apply_settings(trading={"magic": engine.cfg.trading.magic})  # aynı değer sorun değil


def test_engine_stops_if_account_switches_to_live():
    engine, broker = make_engine()
    engine.set_running(True)
    real = broker.account
    broker.account = lambda: {**real(), "is_demo": False}
    engine.tick()
    assert not engine.running
    assert "DURDURULDU" in engine.events[0]["message"]


def test_opposite_signal_closes_and_reverses():
    engine, broker = scripted_engine([1, -1])
    magic = engine.cfg.trading.magic
    next_bar(engine, broker)
    freeze_stops(broker)
    next_bar(engine, broker)
    assert [p.side for p in broker.positions(magic)] == [-1]
    assert len(broker.history(magic, 30)) == 1


def test_opposite_signal_skipped_when_close_on_opposite_disabled():
    engine, broker = scripted_engine([1, -1], close_on_opposite=False)
    magic = engine.cfg.trading.magic
    next_bar(engine, broker)
    freeze_stops(broker)
    next_bar(engine, broker)
    assert [p.side for p in broker.positions(magic)] == [1]
    assert "ters yönde" in engine.events[0]["message"]


def test_failed_order_is_retried_on_next_tick():
    engine, broker = scripted_engine([1, 1])
    magic = engine.cfg.trading.magic
    real_open = broker.open_position
    broker.open_position = fail
    next_bar(engine, broker)
    assert broker.positions(magic) == []
    assert "tekrar denenecek" in engine.events[0]["message"]
    broker.open_position = real_open
    engine.tick()  # aynı bar, ikinci deneme
    assert len(broker.positions(magic)) == 1


def test_order_given_up_after_max_attempts():
    engine, broker = scripted_engine([1] * 10)
    broker.open_position = fail
    broker.step()
    for _ in range(MAX_ATTEMPTS):
        engine.tick()
    assert "sinyal atlandı" in engine.events[0]["message"]
    engine.tick()  # bar artık işlenmiş sayılır, yeni deneme yok
    assert len(engine.strategy.seq) == 10 - MAX_ATTEMPTS


def test_symbol_error_does_not_block_others_and_is_reported_once():
    engine, broker = make_engine(symbols=["XAUUSD", "EURUSD"])
    real = broker.rates

    def rates(symbol, tf, n):
        if symbol == "XAUUSD":
            raise AttributeError("'NoneType' object has no attribute 'bid'")
        return real(symbol, tf, n)

    broker.rates = rates
    engine.tick()
    engine.tick()
    assert "EURUSD" in engine._last_bar
    assert len([e for e in engine.events if e["level"] == "error"]) == 1


def test_step_reconnects_after_account_error():
    engine, broker = make_engine()
    reconnects = []
    broker.reconnect = lambda: reconnects.append(1)
    real = broker.account
    broker.account = fail
    engine._step()
    assert reconnects == [1] and "requote" in engine.last_error
    broker.account = real
    engine._step()
    assert engine.last_error == "" and "giderildi" in engine.events[0]["message"]


def test_auto_mode_trades_only_active_learned_symbols():
    engine, broker = make_engine()
    engine.cfg.learning.enabled = True
    engine.learned = {"time": 0, "timeframes": ["H1", "H4", "D1"], "assignments": {
        "EURUSD": {"timeframe": "H1", "strategy": "donchian_breakout", "params": {"period": 10}, "active": True},
        "XAUUSD": {"timeframe": "H4", "strategy": "donchian_breakout", "params": {"period": 10}, "active": False},
    }}
    engine._build_strategies()
    assert engine.active_symbols() == ["EURUSD"]
    engine.set_running(True)
    for _ in range(300):
        broker.step()
        engine.tick()
    magic = engine.cfg.trading.magic
    traded = {p.symbol for p in broker.positions(magic)} | {d["symbol"] for d in broker.history(magic, 30)}
    assert traded == {"EURUSD"}
    assert engine.status()["learning"]["enabled"] is True


def test_time_limit_closes_position():
    engine, broker = scripted_engine([1])
    engine.cfg.risk.max_hold_bars = 3
    magic = engine.cfg.trading.magic
    next_bar(engine, broker)
    assert len(broker.positions(magic)) == 1
    freeze_stops(broker)
    for _ in range(4):
        next_bar(engine, broker)
    assert broker.positions(magic) == []
    assert any("süresi doldu" in e["message"] for e in engine.events)


def test_learner_end_to_end(tmp_path):
    from gcmbot import learner
    cfg = Config(broker="fake")
    cfg.learning.universe = ["EURUSD", "XAUUSD"]
    cfg.learning.use_ml = False
    cfg.learning.timeframes = ["H1", "H4"]
    broker = FakeBroker(bar_seconds=None, history_bars=3000)
    out = learner.learn(broker, cfg, tmp_path / "learned.json", data_dir=tmp_path, progress=lambda m: None)
    assert (tmp_path / "learned.json").exists() and (tmp_path / "EURUSD_H4.parquet").exists()
    assert out["symbols_researched"] == 2 and set(out["assignments"]) <= {"EURUSD", "XAUUSD"}
    assert out["timeframes"] == ["H1", "H4"] and set(out["summary"]["by_timeframe"]) == {"H1", "H4"}
    assert "monte_carlo" in out["summary"] and out["summary"]["luck_expected_active"] >= 0
    from gcmbot.data import load_symbols
    assert {"atr_H1", "atr_H4"} <= set(load_symbols(tmp_path)["EURUSD"])  # sonraki indirme öncekini silmez
    for a in out["assignments"].values():
        assert a["strategy"] in STRATEGIES and "holdout" in a and isinstance(a["active"], bool)
        assert a["timeframe"] in ("H1", "H4")
        assert "mc" in a and "hold_trades" not in a


def test_learner_prefers_passing_timeframe_then_dev_t_stat():
    from gcmbot.learner import _pick
    mk = lambda tf, active, t: {"timeframe": tf, "active": active, "dev": {"t_stat": t}}  # noqa: E731
    assert _pick([mk("H1", False, 5.0), mk("H4", True, 1.0), mk("D1", True, 2.0)])["timeframe"] == "D1"
    assert _pick([mk("H1", False, 1.0), mk("H4", False, 3.0)])["timeframe"] == "H4"


def test_engine_uses_learned_timeframe_per_symbol():
    engine, broker = make_engine()
    engine.cfg.learning.enabled = True
    engine.learned = {"time": 0, "timeframes": ["H1", "D1"], "assignments": {
        "EURUSD": {"timeframe": "D1", "strategy": "donchian_breakout", "params": {"period": 10}, "active": True}}}
    engine.cfg.learning.timeframes = ["H1", "D1"]
    engine._build_strategies()
    assert engine.timeframe_for("EURUSD") == "D1" and engine.timeframe_for("XAUUSD") == engine.cfg.trading.timeframe
    asked = []
    real = broker.rates
    broker.rates = lambda sym, tf, n: (asked.append(tf), real(sym, tf, n))[1]
    engine.tick()
    assert asked and set(asked) == {"D1"}
    # Ayarlardaki zaman dilimleri değişince eski öğrenme geçersiz
    engine.cfg.learning.timeframes = ["H4"]
    assert engine.active_symbols() == [] and engine._learn_due()


def test_old_single_timeframe_learned_file_still_loads():
    engine, _ = make_engine()
    engine.cfg.learning.enabled = True
    engine.cfg.learning.timeframes = ["H1"]
    engine.learned = {"time": 0, "timeframe": "H1", "assignments": {
        "EURUSD": {"strategy": "donchian_breakout", "params": {"period": 10}, "active": True}}}
    engine._build_strategies()
    assert engine.active_symbols() == ["EURUSD"] and engine.timeframe_for("EURUSD") == "H1"


def test_daily_start_equity_survives_restart(tmp_path):
    state = tmp_path / "state.json"
    engine, broker = make_engine(state_path=state)
    engine.tick()
    broker.balance -= 500  # %5 zarar
    restarted, _ = make_engine(state_path=state, broker=broker)
    restarted.tick()
    assert "Günlük zarar" in restarted.halted_reason


def losses(symbol, n, t, profit=-10.0):
    return [{"ticket": i, "time": t - i * 60, "symbol": symbol, "side": "buy", "volume": 0.1, "price": 1.0,
             "profit": profit} for i in range(n)]


def test_consecutive_losses_pause_symbol():
    import time as _t
    engine, broker = scripted_engine([1, 1])
    magic = engine.cfg.trading.magic
    now = int(_t.time())
    broker.history = lambda m, days: losses("EURUSD", 5, now) + losses("XAUUSD", 9, now)
    next_bar(engine, broker)
    assert broker.positions(magic) == []
    assert "EURUSD" in engine.status()["paused_symbols"] and "beklemede" in engine.events[0]["message"]
    # Son işlem kârlıysa seri bozulur
    broker.history = lambda m, days: losses("EURUSD", 1, now + 60, profit=5.0) + losses("EURUSD", 5, now)
    next_bar(engine, broker)
    assert len(broker.positions(magic)) == 1 and engine.status()["paused_symbols"] == {}


def test_loss_pause_expires_and_can_be_disabled():
    engine, broker = make_engine()
    broker.history = lambda m, days: losses("EURUSD", 6, 1000)  # çok eski zararlar
    assert engine._loss_pause_until("EURUSD") == 0
    import time as _t
    broker.history = lambda m, days: losses("EURUSD", 6, int(_t.time()))
    assert engine._loss_pause_until("EURUSD") > _t.time()
    engine.cfg.risk.max_consecutive_losses = 0
    assert engine._loss_pause_until("EURUSD") == 0


def test_drawdown_halt_until_restart(tmp_path):
    state = tmp_path / "state.json"
    engine, broker = make_engine(state_path=state)
    engine.tick()
    peak = broker.account()["equity"]
    broker.balance -= peak * 0.25
    engine.tick()
    assert engine.halted_reason.startswith("Toplam düşüş") and engine.status()["drawdown_pct"] >= 25
    # Zirve kalıcıdır: sunucu yeniden başlasa da koruma devam eder
    restarted, _ = make_engine(state_path=state, broker=broker)
    restarted.tick()
    assert restarted.halted_reason.startswith("Toplam düşüş")
    # Elle başlatma düşüşü kabul eder, zirve sıfırlanır
    restarted.set_running(True)
    assert restarted.drawdown_pct() == 0 and not restarted.halted_reason.startswith("Toplam")


def test_monte_carlo():
    from gcmbot.research import monte_carlo
    good = monte_carlo([2.0, -1.0] * 30)
    assert good["loss_prob"] < 5 and 0 < good["luck_pass_prob"] < 100
    bad = monte_carlo([-1.0] * 30)
    assert bad["loss_prob"] == 100 and bad["dd_p95_r"] == 30
    assert monte_carlo([1.0] * 10)["luck_pass_prob"] == 0  # eşik için işlem sayısı yetersiz
    assert monte_carlo([])["runs"] == 0
    # Sıkı mod şans eseri geçme ihtimalini düşürür
    rs = list(np.random.default_rng(3).normal(0.1, 1.3, 60))
    assert monte_carlo(rs, max_loss_prob=10)["luck_pass_prob"] < monte_carlo(rs)["luck_pass_prob"]


def test_strict_mode_filters_active_symbols_immediately():
    engine, _ = make_engine()
    engine.cfg.learning.enabled = True
    engine.cfg.learning.timeframes = ["H1"]
    engine.learned = {"time": 9e12, "timeframes": ["H1"], "assignments": {
        "EURUSD": {"timeframe": "H1", "strategy": "donchian_breakout", "params": {"period": 10}, "active": True,
                   "mc": {"loss_prob": 25.0}},
        "XAUUSD": {"timeframe": "H1", "strategy": "donchian_breakout", "params": {"period": 10}, "active": True,
                   "mc": {"loss_prob": 4.0}}}}
    engine._build_strategies()
    assert engine.active_symbols() == ["EURUSD", "XAUUSD"] and not engine._learn_due()
    engine.apply_settings(learning={"max_loss_prob_pct": 10})
    assert engine.active_symbols() == ["XAUUSD"] and engine._learn_due()  # şans istatistikleri için yeniden öğren


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
    assert client.post("/api/positions/1/close", headers=H).status_code == 404
    assert client.post("/api/positions/close-all", headers=H).json() == {"closed": 0}
    assert client.get("/api/events", headers=H).json()


def test_crypto_prices_cached_and_stale_on_error():
    calls = []

    def fetch(coins, currency):
        calls.append(1)
        if len(calls) > 1:
            raise OSError("ağ yok")
        return {"bitcoin": {"usd": 67000.5, "usd_24h_change": -1.25}}

    prices = CryptoPrices(fetch)
    coins = ["bitcoin", "cardano"]
    d = prices.get(coins, "usd")
    assert d["coins"][0] == {"id": "bitcoin", "price": 67000.5, "change_24h_pct": -1.25}
    assert d["coins"][1]["price"] is None and d["stale"] is False
    prices.get(coins, "usd")
    assert len(calls) == 1  # önbellekten geldi

    prices._time -= CACHE_SECONDS + 1  # önbellek süresi doldu, CoinGecko'ya ulaşılamıyor
    d = prices.get(coins, "usd")
    assert d["stale"] is True and d["coins"][0]["price"] == 67000.5 and len(calls) == 2
    prices.get(coins, "usd")
    assert len(calls) == 2  # hatadan sonra da 60 sn beklenir, CoinGecko'ya yüklenilmez


def test_api_crypto():
    engine, _ = make_engine()

    def down(coins, currency):
        raise OSError("ağ yok")

    assert TestClient(create_app(engine, crypto=CryptoPrices(down))).get(
        "/api/crypto", headers=H).status_code == 502
    up = CryptoPrices(lambda coins, cur: {c: {cur: 1.0, f"{cur}_24h_change": 0.5} for c in coins})
    r = TestClient(create_app(engine, crypto=up)).get("/api/crypto", headers=H)
    assert [c["id"] for c in r.json()["coins"]] == ["bitcoin", "ethereum", "cardano"]
    assert TestClient(create_app(engine, crypto=up)).get("/api/crypto").status_code == 401


def test_api_learning_endpoints(client):
    r = client.get("/api/learning", headers=H).json()
    assert r["enabled"] is False and r["assignments"] == {}
    r = client.put("/api/settings", headers=H, json={"learning": {"enabled": True, "every_days": 3}})
    assert r.status_code == 200 and r.json()["learning"]["settings"]["every_days"] == 3
    assert client.put("/api/settings", headers=H, json={"learning": {"every_days": 0}}).status_code == 400
    assert client.get("/api/learning").status_code == 401


def test_api_close_refuses_foreign_position():
    engine, broker = make_engine()
    client = TestClient(create_app(engine))
    foreign = broker.open_position("EURUSD", 1, 0.1, sl=1.0, tp=2.0, magic=999)  # elle açılmış gibi
    assert client.post(f"/api/positions/{foreign}/close", headers=H).status_code == 404
    assert len(broker.positions(999)) == 1
    own = broker.open_position("EURUSD", 1, 0.1, sl=1.0, tp=2.0, magic=engine.cfg.trading.magic)
    assert client.post(f"/api/positions/{own}/close", headers=H).status_code == 200
    assert broker.positions(engine.cfg.trading.magic) == []


def test_cost_settings_swap_types():
    from gcmbot.research import cost_settings
    pts = cost_settings({"swap_type": 0, "point": 0.00001, "swap_long": -13.0, "swap_short": 1.0, "spread": 0.0002})
    assert pts.swap_long == pytest.approx(-0.00013) and pts.swap_short == pytest.approx(0.00001)
    assert pts.spread == 0.0002
    # Hisse: yıllık %-15 faiz, 360 gün
    pct = cost_settings({"swap_type": 2, "swap_long": -15.0, "swap_short": -14.0}, price=360.0)
    assert pct.swap_long == pytest.approx(-0.15) and pct.swap_short == pytest.approx(-0.14)
