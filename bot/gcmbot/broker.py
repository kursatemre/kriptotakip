"""Broker katmanı.

- MT5Broker: GCM'nin MetaTrader 5 terminaline resmi `MetaTrader5` Python
  kütüphanesi ile bağlanır (sadece Windows'ta çalışır).
- FakeBroker: Rastgele fiyat üreten sahte broker. MT5 olmadan uygulamayı ve
  botu denemek / test etmek için.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .risk import SymbolInfo


class BrokerError(Exception):
    pass


@dataclass
class Position:
    ticket: int
    symbol: str
    side: int  # +1 alış, -1 satış
    volume: float
    open_price: float
    sl: float
    tp: float
    profit: float
    open_time: int  # unix saniye
    comment: str = ""

    def to_dict(self):
        d = asdict(self)
        d["side"] = "buy" if self.side > 0 else "sell"
        return d


class Broker:
    name = "base"

    def connect(self) -> None: ...
    def shutdown(self) -> None: ...
    def reconnect(self) -> None: ...
    def account(self) -> dict: raise NotImplementedError
    def symbol_info(self, symbol: str) -> SymbolInfo: raise NotImplementedError
    def rates(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame: raise NotImplementedError
    def price(self, symbol: str) -> tuple[float, float]: raise NotImplementedError
    def positions(self, magic: int) -> list[Position]: raise NotImplementedError
    def open_position(self, symbol: str, side: int, volume: float, sl: float, tp: float,
                      magic: int, comment: str = "") -> int: raise NotImplementedError
    def close_position(self, ticket: int) -> None: raise NotImplementedError
    def history(self, magic: int, days: int) -> list[dict]: raise NotImplementedError
    def find_symbols(self, text: str) -> list[str]: return []


# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------

class MT5Broker(Broker):
    name = "mt5"

    def __init__(self, login: int = 0, password: str = "", server: str = "", path: str = ""):
        try:
            import MetaTrader5 as mt5  # noqa: N813
        except ImportError as e:
            raise BrokerError(
                "MetaTrader5 kütüphanesi bulunamadı. Windows'ta `pip install MetaTrader5` çalıştırın."
            ) from e
        self.mt5 = mt5
        self._login, self._password, self._server, self._path = login, password, server, path
        # MetaTrader5 kütüphanesi thread-safe değil; tüm çağrılar bu kilitten geçer
        self._lock = threading.RLock()

    def _err(self, what: str) -> BrokerError:
        return BrokerError(f"{what}: {self.mt5.last_error()}")

    def connect(self):
        with self._lock:
            kwargs = {}
            if self._login:
                kwargs = {"login": self._login, "password": self._password, "server": self._server}
            ok = self.mt5.initialize(self._path, **kwargs) if self._path else self.mt5.initialize(**kwargs)
            if not ok:
                raise self._err("MT5 başlatılamadı (terminal kurulu ve açık mı, giriş bilgileri doğru mu?)")

    def shutdown(self):
        with self._lock:
            self.mt5.shutdown()

    def reconnect(self):
        """Terminal kapanıp açıldığında eski bağlantı kullanılamaz; baştan bağlan."""
        with self._lock:
            self.mt5.shutdown()
            self.connect()

    def account(self):
        with self._lock:
            a = self.mt5.account_info()
            if a is None:
                raise self._err("Hesap bilgisi alınamadı")
            term = self.mt5.terminal_info()
            return {
                "login": a.login,
                "server": a.server,
                "name": a.name,
                "currency": a.currency,
                "leverage": a.leverage,
                "balance": a.balance,
                "equity": a.equity,
                "margin": a.margin,
                "margin_free": a.margin_free,
                "is_demo": a.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO,
                "hedging": a.margin_mode == self.mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
                "algo_trading_enabled": bool(term and term.trade_allowed),
            }

    def _select(self, symbol):
        if not self.mt5.symbol_select(symbol, True):
            raise self._err(f"'{symbol}' sembolü bulunamadı (Piyasa Gözlemi'ndeki adı kontrol edin)")

    def symbol_info(self, symbol):
        with self._lock:
            self._select(symbol)
            s = self.mt5.symbol_info(symbol)
            if s is None:
                raise self._err(f"'{symbol}' bilgisi alınamadı")
            return SymbolInfo(
                name=s.name, point=s.point, digits=s.digits,
                tick_size=s.trade_tick_size, tick_value=s.trade_tick_value,
                volume_min=s.volume_min, volume_max=s.volume_max, volume_step=s.volume_step,
                stops_level=s.trade_stops_level,
            )

    def _timeframe(self, tf: str):
        return getattr(self.mt5, f"TIMEFRAME_{tf}")

    def rates(self, symbol, timeframe, count):
        with self._lock:
            self._select(symbol)
            # +1: en sondaki bar henüz kapanmamış olan bardır, onu atıyoruz
            data = self.mt5.copy_rates_from_pos(symbol, self._timeframe(timeframe), 0, count + 1)
        if data is None or len(data) == 0:
            raise self._err(f"'{symbol}' fiyat verisi alınamadı")
        df = pd.DataFrame(data)[["time", "open", "high", "low", "close", "tick_volume"]]
        return df.iloc[:-1].reset_index(drop=True)

    def _tick(self, symbol):
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            raise self._err(f"'{symbol}' fiyatı alınamadı")
        return t

    def price(self, symbol):
        with self._lock:
            self._select(symbol)
            t = self._tick(symbol)
        return t.bid, t.ask

    def positions(self, magic):
        with self._lock:
            ps = self.mt5.positions_get()
        if ps is None:
            raise self._err("Pozisyonlar alınamadı")
        return [
            Position(
                ticket=p.ticket, symbol=p.symbol,
                side=1 if p.type == self.mt5.POSITION_TYPE_BUY else -1,
                volume=p.volume, open_price=p.price_open, sl=p.sl, tp=p.tp,
                profit=p.profit + p.swap, open_time=int(p.time), comment=p.comment,
            )
            for p in ps if p.magic == magic
        ]

    def _filling(self, symbol):
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise self._err(f"'{symbol}' bilgisi alınamadı")
        mode = info.filling_mode
        if mode & 1:  # SYMBOL_FILLING_FOK
            return self.mt5.ORDER_FILLING_FOK
        if mode & 2:  # SYMBOL_FILLING_IOC
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, request, what):
        result = self.mt5.order_send(request)
        if result is None:
            raise self._err(what)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise BrokerError(f"{what}: retcode={result.retcode} ({result.comment})")
        return result

    def open_position(self, symbol, side, volume, sl, tp, magic, comment=""):
        with self._lock:
            self._select(symbol)
            tick = self._tick(symbol)
            buy = side > 0
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
                "price": tick.ask if buy else tick.bid,
                "sl": float(sl),
                "tp": float(tp),
                "deviation": 20,
                "magic": magic,
                "comment": comment[:31],
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(symbol),
            }
            result = self._send(request, f"{symbol} emri gönderilemedi")
            return int(result.order)

    def close_position(self, ticket):
        with self._lock:
            ps = self.mt5.positions_get(ticket=ticket)
            if not ps:
                raise BrokerError(f"#{ticket} numaralı pozisyon bulunamadı")
            p = ps[0]
            tick = self._tick(p.symbol)
            is_buy = p.type == self.mt5.POSITION_TYPE_BUY
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": self.mt5.ORDER_TYPE_SELL if is_buy else self.mt5.ORDER_TYPE_BUY,
                "position": p.ticket,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": 20,
                "magic": p.magic,
                "comment": "gcmbot kapat",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(p.symbol),
            }
            self._send(request, f"#{ticket} kapatılamadı")

    def history(self, magic, days):
        now = datetime.now(timezone.utc)
        with self._lock:
            deals = self.mt5.history_deals_get(now - timedelta(days=days), now + timedelta(days=1))
        if deals is None:
            raise self._err("İşlem geçmişi alınamadı")
        out = []
        for d in deals:
            if d.magic != magic or d.entry != self.mt5.DEAL_ENTRY_OUT:
                continue
            # Kapanış işlemi pozisyonun tersi yöndedir
            pos_side = "sell" if d.type == self.mt5.DEAL_TYPE_BUY else "buy"
            out.append({
                "ticket": d.position_id, "time": int(d.time), "symbol": d.symbol, "side": pos_side,
                "volume": d.volume, "price": d.price,
                "profit": round(d.profit + d.swap + d.commission, 2),
            })
        return sorted(out, key=lambda x: x["time"], reverse=True)

    def find_symbols(self, text):
        """Adında `text` geçen semboller (GCM'de EURUSD yerine EURUSD. gibi adlar olabilir)."""
        with self._lock:
            found = self.mt5.symbols_get(group=f"*{text}*")
        return sorted(s.name for s in found or ())


# ---------------------------------------------------------------------------
# Sahte broker (MT5'siz deneme ve testler için)
# ---------------------------------------------------------------------------

_FAKE_SPECS = {
    # sembol: (başlangıç fiyatı, digits, tick_size, tick_value, spread)
    "EURUSD": (1.0800, 5, 0.00001, 1.0, 0.00010),
    "GBPUSD": (1.2700, 5, 0.00001, 1.0, 0.00015),
    "USDJPY": (150.00, 3, 0.001, 0.67, 0.015),
    "XAUUSD": (2000.0, 2, 0.01, 1.0, 0.30),
}


class FakeBroker(Broker):
    """Rastgele yürüyüş fiyatları üretir.

    bar_seconds verilirse her bar_seconds saniyede bir yeni bar oluşur
    (canlı deneme). None ise barlar sadece step() ile ilerler (testler).
    """

    name = "fake"

    def __init__(self, bar_seconds: float | None = 5, seed: int = 42, history_bars: int = 2000,
                 balance: float = 10_000.0):
        self.bar_seconds = bar_seconds
        self.history_bars = history_bars
        self.rng = np.random.default_rng(seed)
        self.balance = balance
        self._bars: dict[str, pd.DataFrame] = {}
        self._positions: dict[int, dict] = {}
        self._closed: list[dict] = []
        self._next_ticket = 1000
        self._started = time.time()
        self._advanced = 0
        self._lock = threading.RLock()

    # --- fiyat üretimi ---
    def _spec(self, symbol):
        return _FAKE_SPECS.get(symbol, (100.0, 2, 0.01, 1.0, 0.05))

    def _gen(self, symbol, n, start_price, start_time):
        _, digits, *_ = self._spec(symbol)
        # Rejim değiştiren trend + gürültü: stratejilerin denenebileceği gerçekçi-ish veri
        drift = np.repeat(self.rng.normal(0, 0.0004, n // 100 + 1), 100)[:n]
        rets = drift + self.rng.normal(0, 0.002, n)
        close = start_price * np.exp(np.cumsum(rets))
        open_ = np.concatenate([[start_price], close[:-1]])
        wick = np.abs(self.rng.normal(0, 0.0012, (2, n))) * close
        high = np.maximum(open_, close) + wick[0]
        low = np.minimum(open_, close) - wick[1]
        times = start_time + np.arange(n) * 3600
        return pd.DataFrame({
            "time": times, "open": open_.round(digits), "high": high.round(digits),
            "low": low.round(digits), "close": close.round(digits), "tick_volume": 100,
        })

    def _ensure(self, symbol):
        if symbol not in self._bars:
            price = self._spec(symbol)[0]
            start = int(time.time()) // 3600 * 3600 - self.history_bars * 3600
            self._bars[symbol] = self._gen(symbol, self.history_bars, price, start)

    def _auto_advance(self):
        if self.bar_seconds is None:
            return
        due = int((time.time() - self._started) / self.bar_seconds)
        if due > self._advanced:
            self.step(due - self._advanced)

    def step(self, n: int = 1):
        """Tüm sembolleri n bar ilerletir ve SL/TP kontrolü yapar."""
        with self._lock:
            self._advanced += n
            for symbol, df in list(self._bars.items()):
                last = df.iloc[-1]
                new = self._gen(symbol, n, float(last["close"]), int(last["time"]) + 3600)
                self._bars[symbol] = pd.concat([df, new], ignore_index=True).tail(self.history_bars + 500)
                for _, bar in new.iterrows():
                    self._check_stops(symbol, bar)

    def _check_stops(self, symbol, bar):
        for ticket, p in list(self._positions.items()):
            if p["symbol"] != symbol:
                continue
            if p["side"] > 0:
                hit = p["sl"] if bar["low"] <= p["sl"] else p["tp"] if bar["high"] >= p["tp"] else None
            else:
                hit = p["sl"] if bar["high"] >= p["sl"] else p["tp"] if bar["low"] <= p["tp"] else None
            if hit is not None:
                self._close(ticket, hit, int(bar["time"]))

    def _pnl(self, p, exit_price):
        _, _, tick_size, tick_value, _ = self._spec(p["symbol"])
        return (exit_price - p["open_price"]) * p["side"] / tick_size * tick_value * p["volume"]

    def _close(self, ticket, exit_price, t):
        p = self._positions.pop(ticket)
        profit = round(self._pnl(p, exit_price), 2)
        self.balance += profit
        self._closed.append({
            "ticket": ticket, "time": t, "symbol": p["symbol"],
            "side": "buy" if p["side"] > 0 else "sell", "volume": p["volume"],
            "price": exit_price, "profit": profit, "magic": p["magic"],
        })

    # --- Broker arayüzü ---
    def account(self):
        with self._lock:
            self._auto_advance()
            floating = sum(self._pnl(p, self._mid(p["symbol"])) for p in self._positions.values())
            return {
                "login": 12345678, "server": "FakeBroker-Demo", "name": "Deneme", "currency": "USD",
                "leverage": 100, "balance": round(self.balance, 2),
                "equity": round(self.balance + floating, 2), "margin": 0.0,
                "margin_free": round(self.balance + floating, 2),
                "is_demo": True, "hedging": True, "algo_trading_enabled": True,
            }

    def symbol_info(self, symbol):
        _, digits, tick_size, tick_value, _ = self._spec(symbol)
        return SymbolInfo(name=symbol, point=tick_size, digits=digits, tick_size=tick_size,
                          tick_value=tick_value, volume_min=0.01, volume_max=100, volume_step=0.01)

    def rates(self, symbol, timeframe, count):
        with self._lock:
            self._ensure(symbol)
            self._auto_advance()
            return self._bars[symbol].tail(count).reset_index(drop=True)

    def _mid(self, symbol):
        self._ensure(symbol)
        return float(self._bars[symbol]["close"].iloc[-1])

    def price(self, symbol):
        with self._lock:
            mid = self._mid(symbol)
            spread = self._spec(symbol)[4]
            return mid - spread / 2, mid + spread / 2

    def positions(self, magic):
        with self._lock:
            self._auto_advance()
            out = []
            for t, p in self._positions.items():
                if p["magic"] != magic:
                    continue
                out.append(Position(
                    ticket=t, symbol=p["symbol"], side=p["side"], volume=p["volume"],
                    open_price=p["open_price"], sl=p["sl"], tp=p["tp"],
                    profit=round(self._pnl(p, self._mid(p["symbol"])), 2),
                    open_time=p["open_time"], comment=p["comment"],
                ))
            return out

    def open_position(self, symbol, side, volume, sl, tp, magic, comment=""):
        with self._lock:
            bid, ask = self.price(symbol)
            ticket = self._next_ticket
            self._next_ticket += 1
            self._positions[ticket] = {
                "symbol": symbol, "side": side, "volume": volume,
                "open_price": ask if side > 0 else bid, "sl": sl, "tp": tp,
                "magic": magic, "comment": comment, "open_time": int(time.time()),
            }
            return ticket

    def close_position(self, ticket):
        with self._lock:
            if ticket not in self._positions:
                raise BrokerError(f"#{ticket} numaralı pozisyon bulunamadı")
            p = self._positions[ticket]
            bid, ask = self.price(p["symbol"])
            self._close(ticket, bid if p["side"] > 0 else ask, int(time.time()))

    def history(self, magic, days):
        with self._lock:
            return [
                {k: v for k, v in d.items() if k != "magic"}
                for d in reversed(self._closed) if d["magic"] == magic
            ]

    def find_symbols(self, text):
        return sorted(s for s in _FAKE_SPECS if text.upper() in s)


def make_broker(cfg) -> Broker:
    if cfg.broker == "fake":
        return FakeBroker()
    return MT5Broker(cfg.mt5.login, cfg.mt5.password, cfg.mt5.server, cfg.mt5.path)
