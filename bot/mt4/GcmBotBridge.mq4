//+------------------------------------------------------------------+
//| GcmBotBridge.mq4                                                 |
//| Python botu (bot/gcmbot/mt4.py) ile MT4 arasindaki kopru.        |
//|                                                                  |
//| Her Python istemcisi MT4'un ortak klasorune (Common\Files\gcmbot)|
//| kendi req_<istemci>.txt dosyasini yazar. Bu EA 100 ms'de bir     |
//| bakar, istegi once work_<istemci>.txt'ye tasir (boylece Python   |
//| zaman asiminda istegi geri cekebilir), isler ve yaniti           |
//| resp_<istemci>.txt'ye yazar. Herhangi bir grafige bir kez ekleyin|
//|                                                                  |
//| Istek : <id>|<utc unix zamani>|<komut>|<arg1>|<arg2>...          |
//|         30 sn'den eski istekler reddedilir (bot cokerse yarim    |
//|         kalan bir emir istegi sonradan islenmesin)               |
//| Yanit : <id>|OK  veya  <id>|ERR|<mesaj>, ardindan veri satirlari |
//+------------------------------------------------------------------+
#property copyright "gcmbot"
#property version   "1.00"
#property strict

#include <stdlib.mqh>

#define BRIDGE_VERSION "2"
#define BRIDGE_DIR     "gcmbot\\"

input int Slippage = 20;   // Izin verilen kayma (point)

string g_lines[];
int    g_count = 0;

int OnInit()
{
   FolderCreate("gcmbot", FILE_COMMON);
   if(!EventSetMillisecondTimer(100))
      return INIT_FAILED;
   Print("GcmBotBridge v", BRIDGE_VERSION, " basladi: ",
         TerminalInfoString(TERMINAL_COMMONDATA_PATH), "\\Files\\gcmbot");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTick()
{
}

void OnTimer()
{
   // Bekleyen istekleri topla (her istemcinin kendi dosyasi var)
   string found[];
   int count = 0;
   string name;
   long fh = FileFindFirst(BRIDGE_DIR + "req_*.txt", name, FILE_COMMON);
   if(fh == INVALID_HANDLE)
      return;
   do
   {
      ArrayResize(found, count + 1);
      found[count++] = name;
   }
   while(FileFindNext(fh, name));
   FileFindClose(fh);

   for(int i = 0; i < count; i++)
   {
      // "req_<istemci>.txt" -> "<istemci>"
      string client = StringSubstr(found[i], 4, StringLen(found[i]) - 8);
      Process(client);
   }
}

void Process(string client)
{
   string req = BRIDGE_DIR + "req_" + client + ".txt";
   string work = BRIDGE_DIR + "work_" + client + ".txt";
   // Once tasi: Python zaman asiminda req dosyasini silebildiyse istegin islenmedigi kesindir
   if(!FileMove(req, FILE_COMMON, work, FILE_COMMON | FILE_REWRITE))
      return;
   int h = FileOpen(work, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;
   string line = FileReadString(h);
   FileClose(h);
   FileDelete(work, FILE_COMMON);

   string f[];
   int n = StringSplit(line, '|', f);
   if(n < 3)
      return;

   g_count = 0;
   string err = "";
   long age = (long)TimeGMT() - StringToInteger(f[1]);
   if(age > 30 || age < -30)
      err = "Istek eski (" + IntegerToString(age) + " sn), islenmedi. Bilgisayar saatini kontrol edin.";
   else
      Handle(f, n, err);
   WriteResponse(client, f[0] + (err == "" ? "|OK" : "|ERR|" + Clean(err)));
}

//--- yardimcilar ---------------------------------------------------
void AddLine(string s)
{
   if(g_count >= ArraySize(g_lines))
      ArrayResize(g_lines, g_count + 1, 10000);
   g_lines[g_count++] = s;
}

string Clean(string s)
{
   StringReplace(s, "|", "/");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   return s;
}

string Arg(string &f[], int n, int i)
{
   return i < n ? f[i] : "";
}

string Num(double v)
{
   return DoubleToString(v, 8);
}

string ErrText(int code)
{
   return IntegerToString(code) + " " + ErrorDescription(code);
}

void WriteResponse(string client, string head)
{
   string tmp = BRIDGE_DIR + "resp_" + client + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Print("GcmBotBridge: yanit yazilamadi, hata ", GetLastError());
      return;
   }
   FileWriteString(h, head + "\n");
   for(int i = 0; i < g_count; i++)
      FileWriteString(h, g_lines[i] + "\n");
   FileClose(h);
   if(!FileMove(tmp, FILE_COMMON, BRIDGE_DIR + "resp_" + client + ".txt", FILE_COMMON | FILE_REWRITE))
      Print("GcmBotBridge: yanit tasinamadi, hata ", GetLastError());
}

bool Select(string sym, string &err)
{
   if(SymbolSelect(sym, true))
      return true;
   err = "'" + sym + "' sembolu bulunamadi (Piyasa Gozlemi'ndeki adi kontrol edin)";
   return false;
}

bool WaitContext()
{
   for(int i = 0; i < 50 && IsTradeContextBusy(); i++)
      Sleep(100);
   return !IsTradeContextBusy();
}

bool Retryable(int code)
{
   return code == ERR_PRICE_CHANGED || code == ERR_OFF_QUOTES || code == ERR_REQUOTE
          || code == ERR_TRADE_CONTEXT_BUSY || code == ERR_SERVER_BUSY;
}

//--- komutlar ------------------------------------------------------
void Handle(string &f[], int n, string &err)
{
   string cmd = f[2];   // f[0] = id, f[1] = zaman, argumanlar f[3]'ten itibaren
   if(cmd == "ping")
      AddLine(BRIDGE_VERSION);
   else if(cmd == "account")
      CmdAccount();
   else if(cmd == "symbol_info")
      CmdSymbolInfo(Arg(f, n, 3), err);
   else if(cmd == "rates")
      CmdRates(Arg(f, n, 3), (int)StringToInteger(Arg(f, n, 4)), (int)StringToInteger(Arg(f, n, 5)), err);
   else if(cmd == "price")
      CmdPrice(Arg(f, n, 3), err);
   else if(cmd == "positions")
      CmdPositions();
   else if(cmd == "open")
      CmdOpen(Arg(f, n, 3), (int)StringToInteger(Arg(f, n, 4)), StringToDouble(Arg(f, n, 5)),
              StringToDouble(Arg(f, n, 6)), StringToDouble(Arg(f, n, 7)),
              (int)StringToInteger(Arg(f, n, 8)), Arg(f, n, 9), err);
   else if(cmd == "close")
      CloseTicket((int)StringToInteger(Arg(f, n, 3)), err);
   else if(cmd == "history")
      CmdHistory((int)StringToInteger(Arg(f, n, 3)));
   else if(cmd == "symbols")
      CmdSymbols(Arg(f, n, 3));
   else if(cmd == "load_history")
      CmdLoadHistory(Arg(f, n, 3), (int)StringToInteger(Arg(f, n, 4)), err);
   else
      err = "Bilinmeyen komut: " + cmd;
}

void CmdAccount()
{
   bool algo = TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0
               && MQLInfoInteger(MQL_TRADE_ALLOWED) != 0
               && AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0;
   AddLine(IntegerToString(AccountNumber()) + "|" + AccountServer() + "|" + Clean(AccountName()) + "|"
           + AccountCurrency() + "|" + IntegerToString(AccountLeverage()) + "|"
           + Num(AccountBalance()) + "|" + Num(AccountEquity()) + "|" + Num(AccountMargin()) + "|"
           + Num(AccountFreeMargin()) + "|" + (IsDemo() ? "1" : "0") + "|" + (algo ? "1" : "0"));
}

void CmdSymbolInfo(string sym, string &err)
{
   if(!Select(sym, err))
      return;
   AddLine(sym + "|" + Num(MarketInfo(sym, MODE_POINT)) + "|" + IntegerToString((int)MarketInfo(sym, MODE_DIGITS))
           + "|" + Num(MarketInfo(sym, MODE_TICKSIZE)) + "|" + Num(MarketInfo(sym, MODE_TICKVALUE))
           + "|" + Num(MarketInfo(sym, MODE_MINLOT)) + "|" + Num(MarketInfo(sym, MODE_MAXLOT))
           + "|" + Num(MarketInfo(sym, MODE_LOTSTEP)) + "|" + IntegerToString((int)MarketInfo(sym, MODE_STOPLEVEL))
           + "|" + Num(MarketInfo(sym, MODE_SWAPLONG)) + "|" + Num(MarketInfo(sym, MODE_SWAPSHORT))
           + "|" + IntegerToString((int)MarketInfo(sym, MODE_SWAPTYPE)));
}

// Grafigi acip en basa kaydirir (Home tusu gibi): MT4 sunucudan eski barlari indirir
void CmdLoadHistory(string sym, int tf, string &err)
{
   if(!Select(sym, err))
      return;
   long chart = ChartOpen(sym, tf);
   if(chart == 0)
   {
      err = "Grafik acilamadi: " + ErrText(GetLastError());
      return;
   }
   int last = -1, stable = 0;
   for(int i = 0; i < 40 && stable < 4; i++)
   {
      ChartNavigate(chart, CHART_BEGIN, 0);
      Sleep(400);
      int bars = iBars(sym, tf);
      stable = bars == last ? stable + 1 : 0;
      last = bars;
   }
   ChartClose(chart);
   AddLine(IntegerToString(last));
}

void CmdRates(string sym, int tf, int count, string &err)
{
   if(!Select(sym, err))
      return;
   MqlRates r[];
   ArraySetAsSeries(r, false);   // 0 = en eski bar
   int got = CopyRates(sym, tf, 0, count, r);
   if(got <= 0)
   {
      err = "'" + sym + "' fiyat verisi alinamadi (" + ErrText(GetLastError()) + "), gecmis yukleniyor olabilir";
      return;
   }
   int dg = (int)MarketInfo(sym, MODE_DIGITS);
   for(int i = 0; i < got; i++)
      AddLine(IntegerToString((long)r[i].time) + "|" + DoubleToString(r[i].open, dg) + "|"
              + DoubleToString(r[i].high, dg) + "|" + DoubleToString(r[i].low, dg) + "|"
              + DoubleToString(r[i].close, dg) + "|" + IntegerToString(r[i].tick_volume));
}

void CmdPrice(string sym, string &err)
{
   if(!Select(sym, err))
      return;
   RefreshRates();
   double bid = MarketInfo(sym, MODE_BID), ask = MarketInfo(sym, MODE_ASK);
   if(bid <= 0 || ask <= 0)
   {
      err = "'" + sym + "' fiyati alinamadi";
      return;
   }
   AddLine(Num(bid) + "|" + Num(ask));
}

void CmdPositions()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      int t = OrderType();
      if(t != OP_BUY && t != OP_SELL)
         continue;
      AddLine(IntegerToString(OrderTicket()) + "|" + OrderSymbol() + "|" + (t == OP_BUY ? "1" : "-1") + "|"
              + Num(OrderLots()) + "|" + Num(OrderOpenPrice()) + "|" + Num(OrderStopLoss()) + "|"
              + Num(OrderTakeProfit()) + "|" + Num(OrderProfit() + OrderSwap() + OrderCommission()) + "|"
              + IntegerToString((long)OrderOpenTime()) + "|" + Clean(OrderComment()) + "|"
              + IntegerToString(OrderMagicNumber()));
   }
}

void CmdHistory(int days)
{
   // Not: MT4 sadece "Hesap Gecmisi" sekmesinde secili donemdeki islemleri verir
   datetime since = TimeCurrent() - days * 86400;
   for(int i = OrdersHistoryTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      int t = OrderType();
      if((t != OP_BUY && t != OP_SELL) || OrderCloseTime() < since)
         continue;
      AddLine(IntegerToString(OrderTicket()) + "|" + IntegerToString((long)OrderCloseTime()) + "|"
              + OrderSymbol() + "|" + (t == OP_BUY ? "1" : "-1") + "|" + Num(OrderLots()) + "|"
              + Num(OrderClosePrice()) + "|" + Num(OrderProfit() + OrderSwap() + OrderCommission()) + "|"
              + IntegerToString(OrderMagicNumber()));
   }
}

void CmdSymbols(string text)
{
   for(int i = 0; i < SymbolsTotal(false); i++)
   {
      string s = SymbolName(i, false);
      string u = s;
      StringToUpper(u);
      if(text == "" || StringFind(u, text) >= 0)
         AddLine(s);
   }
}

void CmdOpen(string sym, int side, double vol, double sl, double tp, int magic, string comment, string &err)
{
   if(!Select(sym, err))
      return;
   int dg = (int)MarketInfo(sym, MODE_DIGITS);
   sl = NormalizeDouble(sl, dg);
   tp = NormalizeDouble(tp, dg);
   // "Piyasa yurutme" hesaplarda SL/TP emirle birlikte gonderilemez; once ac, sonra ekle
   bool market = SymbolInfoInteger(sym, SYMBOL_TRADE_EXEMODE) == SYMBOL_TRADE_EXECUTION_MARKET;
   int type = side > 0 ? OP_BUY : OP_SELL;
   int ticket = -1, code = 0;
   for(int attempt = 0; attempt < 3 && ticket < 0; attempt++)
   {
      if(!WaitContext())
      {
         err = "Islem baglami mesgul";
         return;
      }
      RefreshRates();
      double price = side > 0 ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
      ticket = OrderSend(sym, type, vol, price, Slippage, market ? 0 : sl, market ? 0 : tp,
                         comment, magic, 0, clrNONE);
      if(ticket < 0)
      {
         code = GetLastError();
         if(!Retryable(code))
            break;
         Sleep(300);
      }
   }
   if(ticket < 0)
   {
      err = sym + " emri gonderilemedi: " + ErrText(code);
      return;
   }
   if(market && (sl > 0 || tp > 0))
   {
      bool ok = OrderSelect(ticket, SELECT_BY_TICKET) && OrderModify(ticket, OrderOpenPrice(), sl, tp, 0, clrNONE);
      if(!ok)
      {
         int mcode = GetLastError();
         string cerr = "";
         // Stopsuz pozisyon birakma
         bool closed = CloseTicket(ticket, cerr);
         err = "#" + IntegerToString(ticket) + " SL/TP konamadi (" + ErrText(mcode) + "), "
               + (closed ? "pozisyon kapatildi" : "POZISYON ACIK KALDI, MT4'te elle kapatin: " + cerr);
         return;
      }
   }
   AddLine(IntegerToString(ticket));
}

bool CloseTicket(int ticket, string &err)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET) || OrderCloseTime() != 0
      || (OrderType() != OP_BUY && OrderType() != OP_SELL))
   {
      err = "#" + IntegerToString(ticket) + " numarali acik pozisyon bulunamadi";
      return false;
   }
   int code = 0;
   for(int attempt = 0; attempt < 3; attempt++)
   {
      if(!WaitContext())
      {
         err = "Islem baglami mesgul";
         return false;
      }
      RefreshRates();
      if(!OrderSelect(ticket, SELECT_BY_TICKET))
         break;
      double price = OrderType() == OP_BUY ? MarketInfo(OrderSymbol(), MODE_BID) : MarketInfo(OrderSymbol(), MODE_ASK);
      if(OrderClose(ticket, OrderLots(), price, Slippage, clrNONE))
         return true;
      code = GetLastError();
      if(!Retryable(code))
         break;
      Sleep(300);
   }
   err = "#" + IntegerToString(ticket) + " kapatilamadi: " + ErrText(code);
   return false;
}
//+------------------------------------------------------------------+
