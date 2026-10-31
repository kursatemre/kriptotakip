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
from . import learner
from .broker import Broker, BrokerError
from .config import Config
from .risk import position_size, stop_levels
from .strategies import Strategy, make_strategy

log = logging.getLogger("gcmbot")

BARS = 500
# Başarısız emir (requote, bağlantı hatası...) aynı bar içinde en fazla bu kadar denenir
MAX_ATTEMPTS = 3
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
# Öğrenme başarısız olursa (ör. bağlantı) en erken bu kadar sonra tekrar denenir
LEARN_RETRY_SECONDS = 3600
# Üst üste zarar koruması için bakılan kapanmış işlem geçmişi
LOSS_HISTORY_DAYS = 90
DRAWDOWN_HALT = "Toplam düşüş limiti"


class Engine:
    def __init__(self, cfg: Config, broker: Broker, on_config_change=None, state_path: Path | None = None,
                 learned_path: Path | None = None):
        self.cfg = cfg
        self.broker = broker
        self.on_config_change = on_config_change
        # Gün başı varlık burada saklanır; bot yeniden başlatılınca günlük zarar limiti sıfırlanmaz
        self.state_path = state_path
        # Öğrenme sonucu (sembol → strateji); None ise sadece bellekte tutulur
        self.learned_path = learned_path
        self.learned = learner.load_learned(learned_path) if learned_path else None
        self.strategies: dict[str, Strategy] = {}
        self.learning_running = False
        self.learning_progress = ""
        self._last_learn_attempt = 0.0
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
        self._peak_equity = 0.0  # düşüş koruması için varlığın en yüksek değeri
        self._paused: dict[str, int] = {}  # sembol → üst üste zarar sonrası yeniden işlem zamanı
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.strategy = make_strategy(cfg.trading.strategy, cfg.trading.params)
        self._load_state()
        self._build_strategies()

    # ---------------------------------------------------------------- öğrenme
    @property
    def auto(self) -> bool:
        return self.cfg.learning.enabled

    def _learned_timeframes(self) -> list[str]:
        lr = self.learned or {}
        return lr.get("timeframes") or ([lr["timeframe"]] if lr.get("timeframe") else [])

    def _assignments(self) -> dict:
        # Ayarlardaki zaman dilimleri değiştiyse eski öğrenme geçersizdir
        if set(self._learned_timeframes()) != set(self.cfg.learning.timeframes):
            return {}
        return self.learned.get("assignments", {})

    def _build_strategies(self):
        self.strategies = {}
        for symbol, a in self._assignments().items():
            try:
                self.strategies[symbol] = make_strategy(a["strategy"], a["params"])
            except ValueError as e:
                log.warning("%s: öğrenilen strateji yüklenemedi: %s", symbol, e)

    def active_symbols(self) -> list[str]:
        """Yeni işlem açılabilecek semboller."""
        if not self.auto:
            return list(self.cfg.trading.symbols)
        limit = self.cfg.learning.max_loss_prob_pct  # sıkı mod yeniden öğrenmeyi beklemeden uygulanır
        return [s for s, a in self._assignments().items()
                if a.get("active") and s in self.strategies and a.get("mc", {}).get("loss_prob", 0) <= limit]

    def strategy_for(self, symbol: str) -> Strategy | None:
        return self.strategies.get(symbol) if self.auto else self.strategy

    def timeframe_for(self, symbol: str) -> str:
        if self.auto:
            a = self._assignments().get(symbol)
            if a:
                return a.get("timeframe") or self.learned["timeframe"]  # eski learned.json'da ortak
        return self.cfg.trading.timeframe

    def learn_now(self) -> bool:
        """Öğrenmeyi arka planda başlatır; zaten çalışıyorsa False döner."""
        with self._lock:
            if self.learning_running:
                return False
            self.learning_running = True
            self._last_learn_attempt = time.time()
        threading.Thread(target=self._learn, name="learn", daemon=True).start()
        return True

    def _learn_due(self) -> bool:
        if not self.auto or self.learning_running:
            return False
        if time.time() - self._last_learn_attempt < LEARN_RETRY_SECONDS:
            return False
        lr = self.learned
        return (not lr or set(self._learned_timeframes()) != set(self.cfg.learning.timeframes)
                or lr.get("max_loss_prob_pct", 100.0) != self.cfg.learning.max_loss_prob_pct
                or time.time() - lr.get("time", 0) > self.cfg.learning.every_days * 86400)

    def _learn(self):
        self.event("info", "Öğrenme başladı: veriler güncelleniyor ve tüm semboller araştırılıyor.", notify=True)

        def progress(msg):
            self.learning_progress = msg
            log.info(msg)

        try:
            result = learner.learn(self.broker, self.cfg, self.learned_path, progress=progress)
            with self._lock:
                self.learned = result
                self._build_strategies()
                self._reset_bar_tracking()  # zaman dilimi değişen sembollerde bar takibi baştan
            active = self.active_symbols() if self.auto else [
                s for s, a in result["assignments"].items() if a["active"]]
            self.event("info", f"Öğrenme bitti: {len(active)} sembol işlem için uygun"
                               f"{' (' + ', '.join(active) + ')' if active else ''}.", notify=True)
        except Exception as e:
            self.event("error", f"Öğrenme başarısız: {e}", notify=True)
        finally:
            self.learning_running = False
            self.learning_progress = ""

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
            self._peak_equity = float(s.get("peak_equity", 0.0))
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
            tmp.write_text(json.dumps({"day": self._day.isoformat(), "day_start_equity": self._day_start_equity,
                                       "peak_equity": self._peak_equity}), encoding="utf-8")
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
                if self.halted_reason.startswith(DRAWDOWN_HALT):
                    self._peak_equity = acc["equity"]  # elle başlatma düşüşü kabul etmek demek: zirve sıfırlanır
                    self._save_state()
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
            raise BrokerError("MetaTrader'da otomatik işlem kapalı: 'AutoTrading/Algo Trading' butonunu açın "
                              "(MT4'te ayrıca GcmBotBridge'de 'Canlı işlemlere izin ver' işaretli olmalı).")

    def apply_settings(self, trading: dict | None = None, risk: dict | None = None,
                       learning: dict | None = None):
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
            if learning:
                new.learning = new.learning.model_validate({**new.learning.model_dump(), **learning})
            strategy = make_strategy(new.trading.strategy, new.trading.params)
            new.trading.params = strategy.params
            self.cfg.trading, self.cfg.risk, self.cfg.learning = new.trading, new.risk, new.learning
            self.strategy = strategy
            self._build_strategies()
            self._reset_bar_tracking()
            self._last_signal.clear()
        if self.on_config_change:
            self.on_config_change(self.cfg)
        if self.auto:
            self.event("info", f"Ayarlar güncellendi: öğrenen mod, {', '.join(self.cfg.learning.timeframes)}, "
                               f"{len(self.active_symbols())} aktif sembol")
        else:
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
        if self._learn_due():
            self.learn_now()

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
            self._check_drawdown(acc)
            active = self.active_symbols()
            # Açık pozisyonu olan semboller de izlenir (süre sınırı); pasif sembolde yeni işlem açılmaz
            held = sorted({p.symbol for p in self.broker.positions(self.cfg.trading.magic)})
            for symbol in dict.fromkeys([*active, *held]):
                try:
                    self._process_symbol(symbol, acc, can_open=symbol in active)
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

    def _check_drawdown(self, acc: dict):
        if acc["equity"] > self._peak_equity:
            self._peak_equity = acc["equity"]
            self._save_state()
        limit = self.cfg.risk.max_drawdown_pct
        dd = self.drawdown_pct()
        if limit and dd >= limit and not self.halted_reason.startswith(DRAWDOWN_HALT):
            self.halted_reason = (f"{DRAWDOWN_HALT} aşıldı (zirveden %{dd:.1f} ≥ %{limit}). Bot yeniden "
                                  "başlatılana kadar yeni işlem yok.")
            self.event("warn", self.halted_reason, notify=True)

    def drawdown_pct(self, equity: float | None = None) -> float:
        if equity is None:
            equity = self.broker.account()["equity"]
        return (self._peak_equity - equity) / self._peak_equity * 100 if self._peak_equity > 0 else 0.0

    def _loss_pause_until(self, symbol: str) -> int:
        """Sembolde son kapanan işlemler üst üste zararlıysa yeniden işlem açılabilecek zaman, değilse 0."""
        r = self.cfg.risk
        if not r.max_consecutive_losses:
            return 0
        closed = [d for d in self.broker.history(self.cfg.trading.magic, LOSS_HISTORY_DAYS) if d["symbol"] == symbol]
        streak = 0
        for d in sorted(closed, key=lambda d: d["time"], reverse=True):
            if d["profit"] >= 0:
                break
            streak += 1
        if streak < r.max_consecutive_losses:
            return 0
        until = int(max(d["time"] for d in closed) + r.loss_pause_hours * 3600)
        return until if until > time.time() else 0

    def _process_symbol(self, symbol: str, acc: dict, can_open: bool = True):
        strat = self.strategy_for(symbol)
        if strat is None:
            return  # stratejisi bilinmeyen sembolde açık pozisyon: SL/TP yönetir
        tf = self.timeframe_for(symbol)
        # Önce sadece son barlara bak; tam veri yalnızca yeni bar kapandığında çekilir
        bar_time = int(self.broker.rates(symbol, tf, 3)["time"].iloc[-1])
        prev = self._last_bar.get(symbol)
        if prev is None:
            self._last_bar[symbol] = bar_time
            return  # ilk tur: mevcut barın sinyali eski, işlem açılmaz
        if bar_time <= prev:
            return  # yeni bar yok

        df = self.broker.rates(symbol, tf, max(BARS, strat.warmup + 10))
        bar_time = int(df["time"].iloc[-1])
        self._close_expired(symbol, strat, bar_time, tf)
        if not can_open:
            self._finish_bar(symbol, bar_time)
            return
        if len(df) < strat.warmup:
            self._finish_bar(symbol, bar_time)
            raise BrokerError(f"Yetersiz veri ({len(df)} bar, en az {strat.warmup} gerekli)")

        signal = strat.last_signal(df)
        self._last_signal[symbol] = {"time": bar_time, "signal": signal, "strategy": strat.name}
        if signal != 0 and self.running:
            try:
                self._act(symbol, signal, df, acc, strat)
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

    def _close_expired(self, symbol: str, strat: Strategy, bar_time: int, tf: str):
        """Süre sınırı dolan pozisyonları kapatır (backtest'teki 'time' çıkışı ile aynı)."""
        hold = strat.max_hold_bars or self.cfg.risk.max_hold_bars
        if not hold:
            return
        tf_sec = TF_SECONDS[tf]
        for p in self.broker.positions(self.cfg.trading.magic):
            # bar_time son kapanan barın açılışı; şu an ≈ bar_time + tf_sec
            if p.symbol == symbol and bar_time + tf_sec - p.open_time >= hold * tf_sec:
                self.broker.close_position(p.ticket)
                self.event("info", f"{symbol} #{p.ticket} süresi doldu ({hold} bar), kapatıldı "
                                   f"(kâr/zarar: {p.profit:.2f})", notify=True)

    def _act(self, symbol: str, signal: int, df, acc: dict, strat: Strategy):
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
        until = self._loss_pause_until(symbol)
        if until:
            self._paused[symbol] = until
            self.event("warn", f"{symbol} {side_txt} sinyali atlandı: üst üste "
                               f"{self.cfg.risk.max_consecutive_losses}+ zarar, sembol "
                               f"{datetime.fromtimestamp(until).strftime('%d.%m %H:%M')} saatine kadar beklemede")
            return
        self._paused.pop(symbol, None)
        if len(self.broker.positions(magic)) >= self.cfg.risk.max_open_positions:
            self.event("warn", f"{symbol} {side_txt} sinyali atlandı: maksimum açık pozisyon sayısına ulaşıldı")
            return

        self._open(symbol, signal, df, acc, strat)

    def _open(self, symbol: str, side: int, df, acc: dict, strat: Strategy):
        r = self.cfg.risk
        info = self.broker.symbol_info(symbol)
        atr_value = float(ind.atr(df, r.atr_period).iloc[-1])
        bid, ask = self.broker.price(symbol)
        entry = ask if side > 0 else bid
        sl, tp = stop_levels(side, entry, atr_value, r.sl_atr_mult, r.tp_atr_mult, info)
        side_txt = "AL" if side > 0 else "SAT"
        if info.tick_value <= 0:  # MT4 bazı çapraz kurlarda piyasa kapalıyken 0 döndürür
            self.event("warn", f"{symbol} {side_txt} atlandı: kontrat değeri (tick value) alınamadı, lot hesaplanamıyor")
            return
        volume = position_size(acc["equity"], r.risk_per_trade_pct, abs(entry - sl), info)
        if volume <= 0:
            self.event("warn", f"{symbol} {side_txt} atlandı: risk ayarına göre lot, minimum lottan küçük")
            return
        ticket = self.broker.open_position(symbol, side, volume, sl, tp, self.cfg.trading.magic,
                                           comment=f"gcmbot {strat.name}")
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
            "peak_equity": round(self._peak_equity, 2),
            "drawdown_pct": round(self.drawdown_pct(acc["equity"]), 2),
            "paused_symbols": {s: t for s, t in self._paused.items() if t > time.time()},
            "trading": self.cfg.trading.model_dump(),
            "risk": self.cfg.risk.model_dump(),
            "strategy_title": "Öğrenen bot (sembol başına strateji)" if self.auto else self.strategy.title,
            "active_symbols": self.active_symbols(),
            # Kopya: motor thread'i sözlüğü değiştirirken JSON'a çevrilmesin
            "last_signals": dict(self._last_signal),
            "learning": self.learning_status(),
        }

    def learning_status(self) -> dict:
        lr = self.learned or {}
        return {
            "enabled": self.auto,
            "running": self.learning_running,
            "progress": self.learning_progress,
            "settings": self.cfg.learning.model_dump(),
            "time": lr.get("time"),
            "timeframe": ", ".join(self._learned_timeframes()),
            "summary": lr.get("summary"),
            "symbols_researched": lr.get("symbols_researched"),
            "assignments": lr.get("assignments", {}),
        }
