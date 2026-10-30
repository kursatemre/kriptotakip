import os
import threading
import time

import pytest

from gcmbot.broker import BrokerError
from gcmbot.mt4 import ENCODING, MT4Broker

MAGIC = 20261030


class FakeEA(threading.Thread):
    """GcmBotBridge.mq4'ün dosya protokolünü taklit eder (MT4 olmadan test için)."""

    def __init__(self, folder, delay=0.0):
        super().__init__(daemon=True)
        self.dir = folder
        self.delay = delay
        self.seen = []
        self.stop = threading.Event()
        self.server, self.demo_flag = "GCM-Demo", "1"

    def handle(self, cmd, args):
        if cmd == "ping":
            return ["1"]
        if cmd == "account":
            return [f"104250115|{self.server}|Deneme|USD|100|10000.00|9990.50|12.00|9978.50|{self.demo_flag}|1"]
        if cmd == "symbol_info":
            return [f"{args[0]}|0.00001|5|0.00001|1.0|0.01|100|0.01|10"]
        if cmd == "rates":
            return [f"{3600 * i}|1.1|1.2|1.0|1.15|10" for i in range(int(args[2]))]
        if cmd == "price":
            return ["1.08000|1.08012"]
        if cmd == "positions":
            return [f"7|EURUSD|1|0.10|1.1|1.0|1.2|5.5|100|gcmbot|{MAGIC}",
                    "8|EURUSD|-1|0.20|1.1|1.2|1.0|-1.0|100|elle|0"]
        if cmd == "open":
            return ["12345"]
        if cmd == "history":
            return [f"5|200|EURUSD|1|0.10|1.15|12.345|{MAGIC}", "6|300|EURUSD|1|0.10|1.15|1|0"]
        if cmd == "symbols":
            return ["EURUSD", "EURUSDm"]
        raise ValueError(f"#{args[0]} numarali acik pozisyon bulunamadi")

    def run(self):
        req, work = self.dir / "req.txt", self.dir / "work.txt"
        resp, tmp = self.dir / "resp.txt", self.dir / "resp.tmp"
        while not self.stop.is_set():
            try:
                os.replace(req, work)  # EA de önce taşır
            except (FileNotFoundError, PermissionError):
                time.sleep(0.005)
                continue
            f = work.read_text(encoding=ENCODING).strip().split("|")
            work.unlink()
            self.seen.append(f[2:])
            time.sleep(self.delay)
            try:
                lines, head = self.handle(f[2], f[3:]), f"{f[0]}|OK"
            except ValueError as e:
                lines, head = [], f"{f[0]}|ERR|{e}"
            tmp.write_text("\n".join([head, *lines]) + "\n", encoding=ENCODING)
            os.replace(tmp, resp)


@pytest.fixture
def ea(tmp_path):
    t = FakeEA(tmp_path)
    t.start()
    yield t
    t.stop.set()


def make(tmp_path, timeout=2.0):
    return MT4Broker(str(tmp_path), timeout=timeout, poll=0.005)


def test_account_and_symbol_info(tmp_path, ea):
    b = make(tmp_path)
    b.connect()
    acc = b.account()
    assert acc["login"] == 104250115 and acc["is_demo"] and acc["algo_trading_enabled"] and acc["hedging"]
    assert acc["equity"] == pytest.approx(9990.5)
    info = b.symbol_info("EURUSD")
    assert info.digits == 5 and info.tick_value == 1.0 and info.volume_step == 0.01 and info.stops_level == 10


def test_demo_detected_from_server_name(tmp_path, ea):
    b = make(tmp_path)
    ea.demo_flag = "0"  # GCM-Demo, MT4'e demo bayrağı göndermiyor
    assert b.account()["is_demo"] is True
    ea.server = "GCM-Real2"
    assert b.account()["is_demo"] is False


def test_rates_drop_forming_bar(tmp_path, ea):
    df = make(tmp_path).rates("EURUSD", "H1", 50)
    assert ea.seen[-1] == ["rates", "EURUSD", "60", "51"]
    assert len(df) == 50 and df["close"].dtype == float and df["time"].iloc[-1] == 49 * 3600


def test_positions_and_history_filtered_by_magic(tmp_path, ea):
    b = make(tmp_path)
    ps = b.positions(MAGIC)
    assert [(p.ticket, p.side, p.profit) for p in ps] == [(7, 1, 5.5)]
    assert [d["ticket"] for d in b.history(MAGIC, 30)] == [5]


def test_open_sends_order_and_returns_ticket(tmp_path, ea):
    ticket = make(tmp_path).open_position("EURUSD", -1, 0.1, 1.2, 1.0, MAGIC, "gcmbot|ema_trend")
    assert ticket == 12345
    assert ea.seen[-1] == ["open", "EURUSD", "-1", "0.1", "1.2", "1.0", str(MAGIC), "gcmbot/ema_trend"]


def test_ea_error_is_raised(tmp_path, ea):
    with pytest.raises(BrokerError, match="#9 numarali"):
        make(tmp_path).close_position(9)


def test_no_ea_withdraws_request(tmp_path):
    b = make(tmp_path, timeout=0.2)
    with pytest.raises(BrokerError, match="yanıt vermiyor"):
        b.open_position("EURUSD", 1, 0.1, 1.0, 1.2, MAGIC)
    # İstek geri çekildi: EA sonradan açılsa bile bu emri görmez
    assert not (tmp_path / "req.txt").exists()


def test_waits_while_ea_is_processing(tmp_path):
    slow = FakeEA(tmp_path, delay=0.5)  # zaman aşımından uzun süren emir
    slow.start()
    try:
        assert make(tmp_path, timeout=0.2).open_position("EURUSD", 1, 0.1, 1.0, 1.2, MAGIC) == 12345
    finally:
        slow.stop.set()


def test_connect_discards_stale_request(tmp_path):
    (tmp_path / "req.txt").write_text("eski|0|open|EURUSD|1|1|0|0|1|x\n")
    b = make(tmp_path)
    b._call = lambda *a: [["1"]]
    b.connect()
    assert not (tmp_path / "req.txt").exists()


def test_find_symbols(tmp_path, ea):
    assert make(tmp_path).find_symbols("eur") == ["EURUSD", "EURUSDm"]
    assert ea.seen[-1] == ["symbols", "EUR"]
