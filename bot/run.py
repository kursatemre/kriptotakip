"""GCM Bot giriş noktası.

  python run.py                         -> botu + API sunucusunu başlatır
  python run.py backtest --compare      -> tüm stratejileri karşılaştırır
  python run.py backtest --strategy ema_trend
  python run.py backtest --optimize rsi_pullback
  python run.py symbols EUR             -> hesapta adında EUR geçen semboller
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gcmbot.backtest import BacktestSettings, compare, optimize, run_backtest
from gcmbot.broker import BrokerError, make_broker
from gcmbot.config import load_config, save_config
from gcmbot.strategies import STRATEGIES, make_strategy

ROOT = Path(__file__).resolve().parent


def local_ips() -> list[str]:
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def check_symbols(broker, symbols) -> bool:
    """Ayarlardaki semboller hesapta var mı? Yoksa benzer adları önerir."""
    ok = True
    for symbol in symbols:
        try:
            broker.symbol_info(symbol)
        except BrokerError:
            ok = False
            matches = broker.find_symbols(symbol.strip(".").upper()[:6])
            hint = f" Hesaptaki benzerleri: {', '.join(matches[:10])}." if matches else ""
            print(f"UYARI: '{symbol}' sembolü bu hesapta bulunamadı.{hint} "
                  f"config.json içindeki trading.symbols'ı düzeltin.")
    return ok


def serve(args):
    import uvicorn

    from gcmbot.api import create_app
    from gcmbot.engine import Engine

    cfg = load_config(args.config)
    if args.fake:
        cfg.broker = "fake"
    broker = make_broker(cfg)
    broker.connect()
    acc = broker.account()
    kind = "DEMO" if acc["is_demo"] else "GERÇEK (CANLI)"
    mode = "hedging" if acc.get("hedging") else "netting"
    print(f"\nBağlandı: {acc['server']} hesap {acc['login']} [{kind}, {mode}]  "
          f"bakiye {acc['balance']} {acc['currency']}")
    if not acc["is_demo"] and not cfg.allow_live:
        print("UYARI: Bu hesap DEMO değil. allow_live=false olduğu için bot işlem AÇMAYACAK.")
    if not acc["algo_trading_enabled"]:
        print("UYARI: Otomatik işlem kapalı (AutoTrading butonu / EA'da 'Canlı işlemlere izin ver'). "
              "Açmadan bot işlem açamaz.")
    check_symbols(broker, cfg.trading.symbols)

    engine = Engine(cfg, broker, on_config_change=lambda c: save_config(c, args.config),
                    state_path=args.config.with_name("state.json"),
                    learned_path=args.config.with_name("learned.json"))
    engine.start_thread()
    engine.event("info", f"Sunucu başladı ({broker.name}, {kind}). Bot durdurulmuş halde, uygulamadan başlatın.")

    port = cfg.api.port
    print("\nMobil uygulamada şu bilgileri girin:")
    for ip in local_ips():
        print(f"  Sunucu adresi : http://{ip}:{port}")
    print(f"  Token         : {cfg.api.token}\n")

    app = create_app(engine, web_dir=ROOT.parent / "mobile" / "build" / "web")
    try:
        uvicorn.run(app, host=cfg.api.host, port=port, log_level="warning")
    finally:
        engine.shutdown()
        broker.shutdown()


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _row(name, m):
    pf = "-" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
    return (f"{name:<38} {m['trades']:>6} {m['win_rate_pct']:>7.1f}% {pf:>6} "
            f"{m['net_return_pct']:>9.2f}% {m['max_drawdown_pct']:>8.2f}%")


HEADER = f"{'':<38} {'İşlem':>6} {'Kazanç':>8} {'PF':>6} {'Getiri':>10} {'MaxDD':>9}"


def backtest(args):
    cfg = load_config(args.config)
    if args.csv:
        df = pd.read_csv(args.csv)
        df.columns = [c.lower() for c in df.columns]
        if not pd.api.types.is_numeric_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"]).astype("int64") // 10**9
        spread = args.spread or 0.0
    else:
        if args.fake:
            cfg.broker = "fake"
        broker = make_broker(cfg)
        broker.connect()
        df = broker.rates(args.symbol, args.timeframe.upper(), args.bars)
        bid, ask = broker.price(args.symbol)
        spread = args.spread if args.spread is not None else max(ask - bid, 0)
        broker.shutdown()

    s = BacktestSettings.from_config(cfg, spread=spread, commission=args.commission)
    print(f"\n{args.symbol} {args.timeframe} | {len(df)} bar | {_fmt_ts(df['time'].iloc[0])} → "
          f"{_fmt_ts(df['time'].iloc[-1])} | spread {spread:.5g} | maliyet {s.commission:.5g} | "
          f"risk %{s.risk_pct}/işlem | "
          f"SL {s.sl_atr_mult}xATR TP {s.tp_atr_mult}xATR\n")

    if args.optimize:
        res = optimize(df, args.optimize, s)
        print(f"Optimizasyon: {args.optimize} (eğitim {res['train_bars']} bar, test {res['test_bars']} bar)\n")
        print("EĞİTİM (ilk %70)".ljust(38) + HEADER[38:])
        for r in res["results"]:
            print(_row(str(r["params"]), r["train"]))
        print("\nTEST (son %30, görülmemiş veri)".ljust(38) + HEADER[38:])
        for r in res["results"]:
            print(_row(str(r["params"]), r["test"]))
        print("\nİpucu: Test sonuçları eğitim sonuçlarına yakın olan parametreleri tercih edin.")
    elif args.strategy:
        res = run_backtest(df, make_strategy(args.strategy), s)
        print(HEADER)
        print(_row(args.strategy, res["metrics"]))
    else:
        print(HEADER)
        for r in compare(df, s):
            print(_row(r["strategy"], r["metrics"]))
    print("\nNOT: Geçmiş performans gelecekteki sonuçları garanti etmez. Önce demoda deneyin.\n")


def symbols(args):
    cfg = load_config(args.config)
    if args.fake:
        cfg.broker = "fake"
    broker = make_broker(cfg)
    broker.connect()
    names = broker.find_symbols(args.filter.upper())
    broker.shutdown()
    print("\n".join(names) if names else "Eşleşen sembol yok.")


def download_cmd(args):
    from gcmbot import data

    cfg = load_config(args.config)
    if args.fake:
        cfg.broker = "fake"
    broker = make_broker(cfg)
    broker.connect()
    names = args.symbols or broker.find_symbols("")
    for tf in args.timeframes:
        data.download(broker, names, tf.upper(), deep=not args.quick)
    broker.shutdown()


def research_cmd(args):
    from gcmbot import data, research

    names = args.symbols or sorted(data.load_symbols())
    rep = research.run(names, args.timeframe.upper(), include_ml=not args.no_ml, max_cost_ratio=args.max_cost,
                       max_loss_prob=args.max_loss_prob)
    s = rep["summary"]
    print(f"\n{s['symbols']} sembol araştırıldı ({rep['candidates']} aday/sembol), "
          f"{len(rep['skipped'])} sembol atlandı (veri yok / maliyet yüksek).")
    print(f"Seçim yapılabilen: {s['with_selection']} | saklı testte artıda: {s['holdout_positive']} | "
          f"saklı test ortalaması {s['holdout_avg_r']:+.4f}R ({s['holdout_trades']} işlem)")
    print(f"Saklı testi GEÇEN semboller: {', '.join(s['passed']) or 'yok'}")
    for sym in s["passed"]:
        b = rep["results"][sym]["best"]
        print(f"  {sym:<10} {b['strategy']} {b['params']} | geliştirme {b['dev']['trades']} işlem "
              f"{b['dev']['avg_r']:+.3f}R | saklı {b['holdout']['trades']} işlem PF {b['holdout']['pf']} "
              f"{b['holdout']['avg_r']:+.3f}R")
    print(f"\nAyrıntılar: {data.DATA_DIR / f'research_{rep['timeframe']}.json'}")


def main():
    p = argparse.ArgumentParser(description="GCM al-sat botu")
    p.add_argument("--config", type=Path, default=ROOT / "config.json")
    p.add_argument("--fake", action="store_true", help="MT5 yerine sahte broker kullan (deneme)")
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser("backtest", help="Stratejileri geçmiş veride dene")
    b.add_argument("--symbol", default="EURUSD")
    b.add_argument("--timeframe", default="H1")
    b.add_argument("--bars", type=int, default=5000)
    b.add_argument("--spread", type=float, default=None, help="fiyat cinsinden spread (varsayılan: anlık spread)")
    b.add_argument("--commission", type=float, default=0.0,
                   help="işlem başı komisyon+swap, fiyat cinsinden (ör. EURUSD'de lot başı 7$ = 0.00007)")
    b.add_argument("--csv", help="MT5 yerine CSV dosyasından veri oku (time,open,high,low,close)")
    g = b.add_mutually_exclusive_group()
    g.add_argument("--compare", action="store_true", help="tüm stratejileri karşılaştır (varsayılan)")
    g.add_argument("--strategy", choices=list(STRATEGIES))
    g.add_argument("--optimize", choices=list(STRATEGIES), help="parametre taraması yap")
    sym = sub.add_parser("symbols", help="hesaptaki sembol adlarını listele (ör. symbols EUR)")
    sym.add_argument("filter", nargs="?", default="")
    d = sub.add_parser("download", help="sembollerin geçmiş verisini bot/data'ya indir")
    d.add_argument("--symbols", nargs="*", help="varsayılan: hesaptaki tüm semboller")
    d.add_argument("--timeframes", nargs="+", default=["H1"])
    d.add_argument("--quick", action="store_true", help="grafiği geriye kaydırıp derin geçmiş indirme")
    r = sub.add_parser("research", help="indirilen veride tüm sembollerde strateji araştırması")
    r.add_argument("--symbols", nargs="*", help="varsayılan: indirilen tüm semboller")
    r.add_argument("--timeframe", default="H1")
    r.add_argument("--no-ml", action="store_true", help="makine öğrenmesi stratejisini atla (hızlı)")
    r.add_argument("--max-cost", type=float, default=0.2, help="en fazla spread/ATR oranı")
    r.add_argument("--max-loss-prob", type=float, default=100.0,
                   help="saklı test Monte Carlo zarar ihtimali üst sınırı (%%, 100 = kapalı)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        commands = {"backtest": backtest, "symbols": symbols, "download": download_cmd, "research": research_cmd}
        commands.get(args.cmd, serve)(args)
    except BrokerError as e:
        print(f"\nHATA: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
