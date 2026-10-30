"""MetaTrader 4 köprüsü.

MetaTrader5 Python kütüphanesi MT4'e bağlanamaz. Bu yüzden MT4'te çalışan GcmBotBridge
uzman danışmanı (bot/mt4/GcmBotBridge.mq4) ile dosya üzerinden konuşulur: Python req.txt'ye
bir komut yazar, EA 100 ms'de bir bakar, işler ve resp.txt'ye yanıt yazar. Dosyalar MT4'ün
ortak klasöründedir: %APPDATA%\\MetaQuotes\\Terminal\\Common\\Files\\gcmbot
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path

import pandas as pd

from .broker import Broker, BrokerError, Position
from .risk import SymbolInfo

BRIDGE_VERSION = "1"
TIMEFRAMES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
# EA dosyaları ANSI yazar (Türkçe Windows'ta cp1254); "mbcs" sistemin ANSI kod sayfasıdır
ENCODING = "mbcs" if os.name == "nt" else "latin-1"
# EA isteği aldıysa (ör. emir gönderiyor) yanıt bu kadar daha beklenir; vazgeçersek
# aynı emir bir sonraki turda tekrar gönderilebilir
MAX_EXTRA_WAIT = 60.0


def default_bridge_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "gcmbot"


class MT4Broker(Broker):
    name = "mt4"

    def __init__(self, bridge_dir: str = "", timeout: float = 10.0, poll: float = 0.02):
        self.dir = Path(bridge_dir) if bridge_dir else default_bridge_dir()
        self.timeout = timeout
        self.poll = poll
        self._lock = threading.RLock()
        self._prefix = secrets.token_hex(3)
        self._seq = 0

    # ------------------------------------------------------------------ protokol
    def _read(self, path: Path) -> list[str] | None:
        try:
            lines = path.read_text(encoding=ENCODING, errors="replace").splitlines()
        except (FileNotFoundError, PermissionError):  # yok ya da EA şu an taşıyor
            return None
        return lines or None

    def _call(self, cmd: str, *args) -> list[list[str]]:
        with self._lock:
            self._seq += 1
            rid = f"{self._prefix}{self._seq}"
            self.dir.mkdir(parents=True, exist_ok=True)
            req, resp, tmp = self.dir / "req.txt", self.dir / "resp.txt", self.dir / "req.tmp"
            resp.unlink(missing_ok=True)
            # Zaman damgası: EA 30 sn'den eski istekleri reddeder
            fields = [rid, str(int(time.time())), cmd, *map(str, args)]
            tmp.write_text("|".join(fields) + "\n", encoding=ENCODING)
            os.replace(tmp, req)

            started = time.monotonic()
            deadline = started + self.timeout
            while True:
                lines = self._read(resp)
                if lines:
                    head = lines[0].split("|", 2)
                    if head[0] == rid:
                        resp.unlink(missing_ok=True)
                        if head[1:2] != ["OK"]:
                            raise BrokerError(head[2] if len(head) > 2 else f"MT4 hatası: {lines[0]}")
                        return [line.split("|") for line in lines[1:] if line]
                    resp.unlink(missing_ok=True)  # başka (eski) bir isteğin yanıtı
                if time.monotonic() > deadline:
                    try:
                        req.unlink()
                    except FileNotFoundError:
                        # EA isteği aldı ve hâlâ işliyor: yanıtını bekle
                        if time.monotonic() - started < self.timeout + MAX_EXTRA_WAIT:
                            deadline = time.monotonic() + 1.0
                            continue
                        raise BrokerError(f"MT4 '{cmd}' isteğine yanıt vermedi. Açık pozisyonları "
                                          "MT4'te kontrol edin.") from None
                    except PermissionError:
                        deadline = time.monotonic() + 1.0  # EA şu an dosyayı taşıyor
                        continue
                    # İstek geri çekildi, EA onu hiç görmedi: emir gitmediği kesin
                    raise BrokerError("MT4 köprüsü yanıt vermiyor. MT4 açık mı, GcmBotBridge bir "
                                      "grafiğe ekli mi, AutoTrading açık mı?")
                time.sleep(self.poll)

    # ------------------------------------------------------------- Broker arayüzü
    def connect(self):
        # Önceki (çökmüş) bir çalıştırmadan kalan istek işlenmesin
        (self.dir / "req.txt").unlink(missing_ok=True)
        version = self._call("ping")[0][0]
        if version != BRIDGE_VERSION:
            raise BrokerError(f"GcmBotBridge sürümü uyumsuz (EA {version}, bot {BRIDGE_VERSION}). "
                              "bot/mt4/GcmBotBridge.mq4'ü MT4'e yeniden kurun.")

    def reconnect(self):
        self.connect()

    def account(self):
        f = self._call("account")[0]
        # GCM'nin MT4 demo sunucusu hesabı "demo" olarak işaretlemiyor (IsDemo() false döner).
        # GCM'de demo sunucusu "GCM-Demo", gerçek sunucular "GCM-Real..." adlıdır.
        is_demo = f[9] == "1" or "demo" in f[1].lower()
        return {
            "login": int(f[0]), "server": f[1], "name": f[2], "currency": f[3], "leverage": int(f[4]),
            "balance": float(f[5]), "equity": float(f[6]), "margin": float(f[7]),
            "margin_free": float(f[8]), "is_demo": is_demo,
            "hedging": True,  # MT4 her zaman hedging'dir
            "algo_trading_enabled": f[10] == "1",
        }

    def symbol_info(self, symbol):
        f = self._call("symbol_info", symbol)[0]
        return SymbolInfo(
            name=f[0], point=float(f[1]), digits=int(f[2]), tick_size=float(f[3]),
            tick_value=float(f[4]), volume_min=float(f[5]), volume_max=float(f[6]),
            volume_step=float(f[7]), stops_level=int(f[8]),
        )

    def rates(self, symbol, timeframe, count):
        # +1: en sondaki bar henüz kapanmamış olan bardır, onu atıyoruz
        rows = self._call("rates", symbol, TIMEFRAMES[timeframe], count + 1)
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "tick_volume"])
        df = df.astype({"time": "int64", "open": float, "high": float, "low": float, "close": float,
                        "tick_volume": "int64"})
        return df.iloc[:-1].reset_index(drop=True)

    def price(self, symbol):
        bid, ask = self._call("price", symbol)[0]
        return float(bid), float(ask)

    def positions(self, magic):
        return [
            Position(ticket=int(f[0]), symbol=f[1], side=int(f[2]), volume=float(f[3]),
                     open_price=float(f[4]), sl=float(f[5]), tp=float(f[6]), profit=float(f[7]),
                     open_time=int(f[8]), comment=f[9])
            for f in self._call("positions") if int(f[10]) == magic
        ]

    def open_position(self, symbol, side, volume, sl, tp, magic, comment=""):
        comment = comment.replace("|", "/")[:31]
        return int(self._call("open", symbol, side, volume, sl, tp, magic, comment)[0][0])

    def close_position(self, ticket):
        self._call("close", ticket)

    def history(self, magic, days):
        out = [
            {"ticket": int(f[0]), "time": int(f[1]), "symbol": f[2], "side": "buy" if f[3] == "1" else "sell",
             "volume": float(f[4]), "price": float(f[5]), "profit": round(float(f[6]), 2)}
            for f in self._call("history", days) if int(f[7]) == magic
        ]
        return sorted(out, key=lambda x: x["time"], reverse=True)

    def find_symbols(self, text):
        return sorted(f[0] for f in self._call("symbols", text.upper()))
