"""Canlı işlem motoru.

Arka planda bir thread olarak çalışır: her `poll_seconds` saniyede bir her sembol
için yeni kapanmış bar olup olmadığına bakar, varsa stratejinin sinyaline göre
pozisyon açar/kapatır. Mobil uygulama botu API üzerinden başlatıp durdurur.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

from . import indicators as ind
from .broker import Broker, BrokerError
from .config import Config
from .risk import position_size, stop_levels
from .strategies import make_strategy

log = logging.getLogger("gcmbot")

BARS = 500
# Başarısız emir (requote, bağlantı hatası...) aynı bar içinde en fazla bu kadar denenir
MAX_ATTEMPTS = 3


class Engine:
    def __init__(self, cfg: Config, broker: Broker, on_config_change=None, state_path: Path | None = None):
        self.cfg = cfg
        self.broker = broker
        self.on_config_change = on_config_change
        # Gün başı varlık burada saklanır; bot yeniden başlatılınca günlük zarar limiti sıfırlanmaz
        self.state_path = state_path
        self.running = False  # True iken yeni işlem açar
        self.halted_reason = ""  # günlük zarar limiti vb.
        self.last_check = 0.0
        self.last_error = ""
        self.events: deque[dict] = deque(maxlen=300)
        self._last_bar: dict[str, int] = {}
        self._last_signal: dict[str, dict] = {}
        self._attempts: dict[str, int] = {}
        self._symbol_errors: dict[str, str] = {}
        self._day: date | None = None
        self._day_start_equity = 0.0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.strategy = make_strategy(cfg.trading.strategy, cfg.trading.params)
        self._load_state()

    # ------------------------------------------------------------------ olaylar
    def event(self, level: str, message: str, notify: bool = False):
        self.events.appendleft({"time": int(time.time()), "level": level, "message": message})
        getattr(log, "warning" if level == "warn" else level, log.info)(message)
        if notify:
            self._telegram(message)

    def _telegram(self, text: str):
        tg = self.cfg.telegram
        if not (tg.bot_token and tg.chat_id):
            return

        def send():
            try:
                data = urllib.parse.urlencode({"chat_id": tg.chat_id, "text": f"🤖 GCM Bot\n{text}"}).encode()
                urllib.request.urlopen(
                    f"https://api.telegram.org/bot{tg.bot_token}/sendMessage", data=data, timeout=10
                )
            except Exception as e:  # bildirim hatası botu durdurmamalı
                log.warning("Telegram bildirimi gönderilemedi: %s", e)

        threading.Thread(target=send, daemon=True).start()

    # ------------------------------------------------------------- kalıcı durum
    def _load_state(self):
        if not (self.state_path and self.state_path.exists()):
            return
        try:
            s = json.loads(self.state_path.read_text(encoding="utf-8"))
            day = date.fromisoformat(s["day"])
            equity = float(s["day_start_equity"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("%s okunamadı, yok sayılıyor: %s", self.state_path.name, e)
            return
        if day == datetime.now(timezone.utc).date():
            self._day, self._day_start_equity = day, equity

    def _save_state(self):
        if not self.state_path:
            return
        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self._day.isoformat(), "day_start_equity": self._day_start_equity}),
                           encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as e:
            log.warning("%s yazılamadı: %s", self.state_path.name, e)

    # ------------------------------------------------------------ yaşam döngüsü
    def start_thread(self):
        self._thread = threading.Thread(target=self._loop, name="engine", daemon=True)
        self._thread.start()

    def shutdown(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _reset_bar_tracking(self):
        self._last_bar.clear()
        self._attempts.clear()
        self._symbol_errors.clear()

    def set_running(self, running: bool):
        with self._lock:
            if running:
                acc = self.broker.account()
                self._check_account_allowed(acc)
                self.halted_reason = ""
                # Başlatıldığında eski sinyallerle işlem açmamak için mevcut barları "görülmüş" say
                self._reset_bar_tracking()
            self.running = running
        self.event("info", "Bot BAŞLATILDI" if running else "Bot DURDURULDU", notify=True)

    def _check_account_allowed(self, acc: dict):
        if not acc["is_demo"] and not self.cfg.allow_live:
            raise BrokerError(
                "Bu hesap DEMO değil! Güvenlik için bot gerçek hesapta çalışmaz "
                "(config.json içinde allow_live=false)."
            )
        if not acc.get("algo_trading_enabled", True):
            raise BrokerError("MT5'te 'Algo Trading' butonu kapalı. Terminalde açın.")

    def apply_settings(self, trading: dict | None = None, risk: dict | None = None):
        """Ayarları doğrular, uygular ve kaydeder. Hatalıysa ValueError fırlatır."""
        with self._lock:
            new = self.cfg.model_copy(deep=True)
            if trading:
                if "magic" in trading and trading["magic"] != new.trading.magic:
                    # magic değişirse bot açık pozisyonlarını tanımaz, onları yönetemez
                    raise ValueError("magic numarası uygulamadan değiştirilemez; gerekirse config.json'dan, "
                                     "bot durdurulmuş ve pozisyon yokken değiştirin.")
                merged = {**new.trading.model_dump(), **trading}
                if merged["strategy"] != new.trading.strategy and "params" not in trading:
                    merged["params"] = {}  # eski stratejinin parametreleri yenisine uymaz
                new.trading = new.trading.model_validate(merged)
            if risk:
                new.risk = new.risk.model_validate({**new.risk.model_dump(), **risk})
            strategy = make_strategy(new.trading.strategy, new.trading.params)
            new.trading.params = strategy.params
            self.cfg.trading, self.cfg.risk = new.trading, new.risk
            self.strategy = strategy
            self._reset_bar_tracking()
            self._last_signal.clear()
        if self.on_config_change:
            self.on_config_change(self.cfg)
        self.event("info", f"Ayarlar güncellendi: {strategy.title} {strategy.params}, "
                           f"{', '.join(self.cfg.trading.symbols)} {self.cfg.trading.timeframe}")

    # -------------------------------------------------------------------- döngü
    def _loop(self):
        while not self._stop.is_set():
            self._step()
            self._stop.wait(self.cfg.trading.poll_seconds)

    def _step(self):
        """Döngünün bir turu: tick + hata bildirimi + gerekirse yeniden bağlanma."""
        try:
            self.tick()
            if self.last_error:
                self.event("info", "Sorun giderildi, bot normal çalışıyor.", notify=True)
            self.last_error = ""
        except Exception as e:
            msg = f"Hata: {e}"
            if msg != self.last_error:
                self.event("error", msg, notify=True)
            self.last_error = msg
            # tick() sadece hesap seviyesindeki hatalarda buraya düşer; en olası sebep
            # MT5 terminalinin kapanması/yeniden başlaması, bu yüzden yeniden bağlanmayı dene
            try:
                self.broker.reconnect()
            except Exception as re:
                log.warning("Yeniden bağlanılamadı: %s", re)

    def tick(self):
        """Tek bir kontrol turu (testlerde doğrudan çağrılır)."""
        with self._lock:
            self.last_check = time.time()
            acc = self.broker.account()
            if self.running:
                # Bot çalışırken terminalde başka (gerçek) hesaba geçilmiş olabilir
                try:
                    self._check_account_allowed(acc)
                except BrokerError as e:
                    self.running = False
                    self.event("error", f"Bot DURDURULDU: {e}", notify=True)
            self._check_daily_loss(acc)
            for symbol in self.cfg.trading.symbols:
                try:
                    self._process_symbol(symbol, acc)
                    self._symbol_errors.pop(symbol, None)
                except Exception as e:  # bir sembolün hatası diğerlerini engellemesin
                    msg = f"{symbol}: {e}"
                    if self._symbol_errors.get(symbol) != msg:  # aynı hatayı her turda bildirme
                        self.event("error", msg, notify=True)
                    self._symbol_errors[symbol] = msg

    def _check_daily_loss(self, acc: dict):
        today = datetime.now(timezone.utc).date()
        if self._day != today:
            self._day = today
            self._day_start_equity = acc["equity"]
            self._save_state()
            if self.halted_reason.startswith("Günlük"):
                self.halted_reason = ""
        limit = self.cfg.risk.max_daily_loss_pct
        loss_pct = (self._day_start_equity - acc["equity"]) / self._day_start_equity * 100 \
            if self._day_start_equity else 0
        if loss_pct >= limit and not self.halted_reason:
            self.halted_reason = f"Günlük zarar limiti aşıldı (%{loss_pct:.2f} ≥ %{limit}). Yarına kadar yeni işlem yok."
            self.event("warn", self.halted_reason, notify=True)

    def _process_symbol(self, symbol: str, acc: dict):
        df = self.broker.rates(symbol, self.cfg.trading.timeframe, BARS)
        if len(df) < self.strategy.warmup:
            raise BrokerError(f"Yetersiz veri ({len(df)} bar, en az {self.strategy.warmup} gerekli)")
        bar_time = int(df["time"].iloc[-1])
        prev = self._last_bar.get(symbol)
        if prev is None:
            self._last_bar[symbol] = bar_time
            return  # ilk tur: mevcut barın sinyali eski, işlem açılmaz
        if bar_time <= prev:
            return  # yeni bar yok

        signal = self.strategy.last_signal(df)
        self._last_signal[symbol] = {"time": bar_time, "signal": signal}
        if signal != 0 and self.running:
            try:
                self._act(symbol, signal, df, acc)
            except Exception as e:
                # Bar "işlendi" sayılmaz, sonraki turda tekrar denenir
                attempts = self._attempts.get(symbol, 0) + 1
                if attempts < MAX_ATTEMPTS:
                    self._attempts[symbol] = attempts
                    raise BrokerError(f"{e} (tekrar denenecek, deneme {attempts}/{MAX_ATTEMPTS})") from e
                self._finish_bar(symbol, bar_time)
                raise BrokerError(f"{e} ({MAX_ATTEMPTS} deneme başarısız, sinyal atlandı)") from e
        self._finish_bar(symbol, bar_time)

    def _finish_bar(self, symbol: str, bar_time: int):
        self._last_bar[symbol] = bar_time
        self._attempts.pop(symbol, None)

    def _act(self, symbol: str, signal: int, df, acc: dict):
        side_txt = "AL" if signal > 0 else "SAT"
        magic = self.cfg.trading.magic
        mine = [p for p in self.broker.positions(magic) if p.symbol == symbol]

        # Ters yönde pozisyon varsa kapat
        if self.cfg.trading.close_on_opposite:
            for p in [p for p in mine if p.side == -signal]:
                self.broker.close_position(p.ticket)
                self.event("info", f"{symbol} #{p.ticket} ters sinyalle kapatıldı (kâr/zarar: {p.profit:.2f})",
                           notify=True)
                mine.remove(p)

        if any(p.side == signal for p in mine):
            return  # aynı yönde zaten pozisyon var
        if mine:
            # Ters pozisyon duruyor (close_on_opposite kapalı). Yeni emir netting hesapta mevcut
            # pozisyonu kapatır/çevirir, hedging hesapta ikinci pozisyon açar; ikisi de backtest'ten farklı.
            self.event("warn", f"{symbol} {side_txt} sinyali atlandı: ters yönde açık pozisyon var")
            return
        if self.halted_reason:
            self.event("warn", f"{symbol} {side_txt} sinyali atlandı: {self.halted_reason}")
            return
        if len(self.broker.positions(magic)) >= self.cfg.risk.max_open_positions:
            self.event("warn", f"{symbol} {side_txt} sinyali atlandı: maksimum açık pozisyon sayısına ulaşıldı")
            return

        self._open(symbol, signal, df, acc)

    def _open(self, symbol: str, side: int, df, acc: dict):
        r = self.cfg.risk
        info = self.broker.symbol_info(symbol)
        atr_value = float(ind.atr(df, r.atr_period).iloc[-1])
        bid, ask = self.broker.price(symbol)
        entry = ask if side > 0 else bid
        sl, tp = stop_levels(side, entry, atr_value, r.sl_atr_mult, r.tp_atr_mult, info)
        volume = position_size(acc["equity"], r.risk_per_trade_pct, abs(entry - sl), info)
        side_txt = "AL" if side > 0 else "SAT"
        if volume <= 0:
            self.event("warn", f"{symbol} {side_txt} atlandı: risk ayarına göre lot, minimum lottan küçük")
            return
        ticket = self.broker.open_position(symbol, side, volume, sl, tp, self.cfg.trading.magic,
                                           comment=f"gcmbot {self.strategy.name}")
        self.event("info", f"{symbol} {side_txt} {volume} lot @ {entry} | SL {sl} TP {tp} (#{ticket})",
                   notify=True)

    # ------------------------------------------------------------------ durum
    def status(self) -> dict:
        acc = self.broker.account()
        return {
            "running": self.running,
            "halted_reason": self.halted_reason,
            "last_error": self.last_error,
            "last_check": int(self.last_check),
            "broker": self.broker.name,
            "account": acc,
            "day_start_equity": round(self._day_start_equity, 2),
            "trading": self.cfg.trading.model_dump(),
            "risk": self.cfg.risk.model_dump(),
            "strategy_title": self.strategy.title,
            # Kopya: motor thread'i sözlüğü değiştirirken JSON'a çevrilmesin
            "last_signals": dict(self._last_signal),
        }
