# GCM Bot – Forex Al-Sat Botu + Mobil Kontrol Uygulaması

GCM Yatırım'ın **MetaTrader 4** forex hesabında (önce **demo**) otomatik al-sat yapan bir bot
ve botu iPhone/Android'den yöneten bir uygulama. Eski KriptoTakip uygulamasının kripto
fiyat takibi de bu uygulamanın **Kripto** sekmesine taşındı.

> GCM forex işlemlerini MT4 ve GCM Trader'da sunar; MT5'i sadece VİOP/Opsiyon için sunar.
> GCM Trader'ın bot arayüzü olmadığı için bot MT4'e, içinde çalışan **GcmBotBridge** uzman
> danışmanı (köprü) üzerinden bağlanır. MT5 hesapları da desteklenir (`"broker": "mt5"`).

```
┌──────────── Windows bilgisayar ─────────────┐          ┌──── iPhone / Android ────┐
│  MetaTrader 4 (GCM forex demo hesabı)        │          │  GCM Bot uygulaması       │
│        ▲  GcmBotBridge EA (dosya köprüsü)    │  HTTP +  │  • Botu başlat/durdur     │
│        │                                     │  token   │  • Hesap, pozisyonlar     │
│  bot/  (Python)                              │◄────────►│  • Strateji & risk ayarı  │
│   • stratejiler + risk yönetimi              │          │  • Backtest/karşılaştırma │
│   • backtest / optimizasyon                  │          │  • Kripto fiyatları       │
│   • REST API (port 8000)                     │          │  • Kayıtlar               │
│   • Telegram bildirimi (opsiyonel)           │          └───────────────────────────┘
│   • kripto fiyatları (CoinGecko, 60 sn önbellek)
└──────────────────────────────────────────────┘
```

> **Neden bot telefonda çalışmıyor?** iOS, bir uygulamanın başka bir uygulamaya (GCM'nin
> uygulamasına) dokunmasına ve arka planda sürekli çalışmasına izin vermez. Bu yüzden bot,
> MT4 ile birlikte bilgisayarda 7/24 çalışır; telefon sadece kumanda görevi görür.

---

## 1. Bilgisayar (Windows) kurulumu

1. **MetaTrader 4'ü kurun.** GCM'nin [MT4 sayfasından](https://www.gcmyatirim.com.tr/islem-platformlari/forex-islem-platformlari/mt4/gcm-meta-trader4)
   indirin ve forex **demo hesabınızla** giriş yapın.
2. **Köprüyü kurun.** `bot\mt4\GcmBotBridge.mq4` dosyasını MT4'te *Dosya → Veri Klasörünü Aç*
   ile açılan klasördeki `MQL4\Experts` içine kopyalayın. MT4'te *Gezgin → Uzman Danışmanlar*'a
   sağ tıklayıp **Yenile** deyin (MT4 dosyayı kendisi derler).
3. **Köprüyü çalıştırın.** Üstteki **AutoTrading** butonunu yeşil yapın. GcmBotBridge'i herhangi
   bir grafiğe sürükleyin, *Ortak* sekmesinde **"Canlı işlemlere izin ver"**i işaretleyin.
   Grafiğin sağ üstünde gülen yüz 🙂 görünmeli. MT4 açık ve EA ekli kaldığı sürece bot çalışır.
   MT4 *Hesap Geçmişi* sekmesine sağ tıklayıp **Tüm Geçmiş**'i seçin (uygulamadaki geçmiş buradan gelir).
   **Köprü güncellendiğinde** (yeni `GcmBotBridge.mq4`) MT4 çalışan EA'yı kendiliğinden
   yenilemez: dosyayı yeniden kopyalayıp derledikten sonra EA'yı grafiğe tekrar sürükleyin
   ve *Tamam*'a basın.
4. **Python 3.11+** kurun ([python.org](https://www.python.org/downloads/)). Kurarken
   "Add to PATH" kutusunu işaretleyin.
5. Bu repoyu indirin ve `bot\start.bat` dosyasına çift tıklayın. İlk seferde Python ortamını
   (`bot\.venv`) kurar, `config.json` oluşturur ve botu başlatır. Sonraki seferlerde sadece başlatır.
6. **Sembol adlarını kontrol edin.** GCM'de semboller `EURUSD` yerine `EURUSD.` gibi ekli
   olabilir. Bot başlarken bulamadığı sembolleri benzer adlarıyla birlikte uyarı olarak yazar.
   Listeyi görmek için: `start.bat symbols EUR` veya `start.bat symbols XAU`.
7. **`config.json`'u düzenleyin** (sonra botu kapatıp yeniden başlatın):
   - `broker`: GCM forex için `"mt4"` (varsayılan). Bot MT4'te açık olan hesabı kullanır;
     şifre hiçbir dosyaya yazılmaz. MT5 hesabı için `"mt5"` yapıp `mt5` bölümünü doldurun.
   - `trading.symbols`: 6. adımda bulduğunuz adlar.
   - `api.token`: boş bırakın, ilk çalıştırmada otomatik üretilir.
   - `allow_live`: **false kalsın.** Bot bu ayarla gerçek hesapta işlem açmayı reddeder.
8. Bot çalışırken konsolda telefona girmeniz gereken **sunucu adresi** ve **token** yazar.
   Bot "durdurulmuş" halde başlar; işlemleri uygulamadan siz başlatırsınız.

> Bilgisayarın uyku moduna geçmesini kapatın: *Ayarlar → Sistem → Güç → Uyku: Hiçbir zaman*.
> Bilgisayar uyursa bot da durur. Windows Güvenlik Duvarı sorarsa Python'a
> "Özel ağlar" için izin verin.

## 2. Telefonu bota bağlamak

| Durum | Adres |
|---|---|
| Telefon ve bilgisayar aynı Wi-Fi'da | Konsolda yazan `http://192.168.x.x:8000` |
| Dışarıdan (mobil veri) erişim | [Tailscale](https://tailscale.com) (ücretsiz): bilgisayara ve telefona kurun, aynı hesapla girin. Bilgisayarın `100.x.x.x` Tailscale IP'sini kullanın: `http://100.x.x.x:8000` |

> Modeminizde port açarak botu internete açmayın. Tailscale çok daha güvenli bir yol.

## 3. Uygulamayı iPhone'a kurmak

**Yol A: Mac gerekmez (önerilen başlangıç).** Uygulamanın web sürümünü botun kendisi sunar.

```bash
cd mobile
flutter build web
```

Bundan sonra `python run.py` çalışırken iPhone'da Safari ile `http://<bilgisayar-ip>:8000`
adresini açın. *Paylaş → Ana Ekrana Ekle* ile uygulama gibi kullanabilirsiniz. Flutter'ı
bilgisayara bir kez kurmanız yeterli: <https://docs.flutter.dev/get-started/install/windows>.

**Yol B: Gerçek iOS uygulaması.** Bunun için Mac ve Xcode gerekir (Apple kuralı).

```bash
cd mobile
flutter pub get
open ios/Runner.xcworkspace   # Xcode'da Signing bölümüne Apple ID'nizi ekleyin
flutter run --release         # iPhone USB ile bağlıyken
```

Ücretsiz Apple ID ile imzalanan uygulama 7 günde bir yeniden yüklenmelidir. Ücretli
geliştirici hesabıyla (yıllık 99$) TestFlight kullanılabilir.

**Android:** `flutter build apk --release` komutu `build/app/outputs/flutter-apk/app-release.apk`
dosyasını üretir.

## 4. En iyi stratejiyi bulmak

Botta 7 strateji var:

| Strateji | Mantık | Uygun piyasa |
|---|---|---|
| `ema_trend` | EMA 20/50 kesişimi, EMA 200 trend filtresi | Trendli |
| `rsi_pullback` | Trend yönünde RSI geri çekilmesinden dönüş | Trendli, dalgalı |
| `donchian_breakout` | 20 barlık kanal kırılımı ("turtle") | Güçlü trend |
| `bollinger_reversion` | Banttan taşıp geri dönüş | Yatay |
| `rsi2_reversion` | Trend yönünde RSI(2) aşırılığından kısa vadeli dönüş | Dalgalı |
| `tsmom` | Son N barın getirisi yönünde işlem (zaman serisi momentumu) | Trendli |
| `ml_boost` | Gradient boosting modeli; sadece geçmiş veriyle düzenli yeniden eğitilir | Hepsi |

Tüm stratejilerde stop-loss ve take-profit ATR'ye göre otomatik konur (varsayılan SL 1.5×ATR,
TP 3×ATR). Lot, her işlemde sermayenin **%1'ini** riske edecek şekilde hesaplanır.

**Önerilen çalışma akışı:**

1. **Karşılaştır:** Uygulamada *Backtest → Karşılaştır* ile tüm stratejileri GCM'nin gerçek
   geçmiş verisinde deneyin. Aynısını bilgisayarda `python run.py backtest --symbol EURUSD --timeframe H1`
   ile de yapabilirsiniz.
2. **Optimize et:** İyi görünen stratejiyi *Optimize* ile tarayın. Parametreler verinin ilk
   %70'inde seçilir ve hiç görülmemiş son %30'unda test edilir. **Test sonucu eğitim sonucuna
   yakın olanı seçin.** Eğitimde parlak görünüp testte çöken parametreler geçmişe aşırı
   uydurulmuştur.
3. Beğendiğiniz sonuçta **Kullan**'a basın, sonra *Panel → Botu başlat*.
4. **Demoda en az 2-4 hafta izleyin.** Demo sonuçlarını backtest ile karşılaştırın, gerekirse
   strateji veya parametre değiştirin.

Backtest spread'i hesaba katar, komisyonu katmaz. Hesabınızda komisyon varsa
`--commission` ile işlem başı maliyeti fiyat cinsinden verin (ör. EURUSD'de lot başı 7$
gidiş-dönüş = `0.00007`). Anlık spread yerine sabit bir değer için `--spread` kullanın. Max
düşüş, açık pozisyonların bar içindeki en kötü fiyattaki zararını da içerir.

Değerlendirirken şunlara bakın: **PF** (kâr faktörü) 1.3'ün üstünde olmalı, **max düşüş**
kaldırabileceğiniz seviyede olmalı ve **işlem sayısı** en az 30-50 olmalı. Az işlemle alınan
sonuçlar şans olabilir.

### Öğrenen bot (tüm sembollerde otomatik strateji seçimi)

Paneldeki **Öğrenen bot** anahtarı açılınca bot elle seçilen strateji yerine şunu yapar:

1. Hesaptaki tüm sembollerin geçmişini `bot\data`'ya indirir (ilk seferde MT4 grafikleri açıp
   kapatarak derin geçmiş yükler; bu sırada MT4'ü kullanmayın).
2. Her sembolde ~60 strateji/parametre adayını spread ve swap dahil dener. Her sembolün **son
   %25'lik verisi saklı tutulur**; seçim sadece ilk %75'te yapılır ve aday bu dönemin 4
   parçasının en az 3'ünde kârlı olmalıdır.
3. Seçilen strateji saklı dönemde de en az 20 işlemde PF ≥ 1.1 tutturursa sembol **aktif** olur.
   Bot sadece aktif sembollerde işlem açar; sonuçlar *Panel → Öğrenen bot* kartında görünür.
   Her sembol için saatlik, 4 saatlik ve günlük grafik (`learning.timeframes`) ayrı ayrı denenir.
4. **Monte Carlo:** saklı test işlemleri 2000 kez yeniden örneklenir. Kartta zarar ihtimali,
   kötü senaryoda (%95) beklenen düşüş ve **hiç üstünlük olmasaydı şans eseri kaç sembolün
   testi geçeceği** görünür. Geçen sembol sayısı bu şans beklentisinden belirgin fazla
   değilse sonuçlar şansla açıklanabilir demektir.
   **Sıkı mod** (kartta anahtar, `learning.max_loss_prob_pct: 10`) yalnızca zarar ihtimali
   %10'un altındaki sembolleri aktif yapar; daha az sembol, ama şansla açıklanması daha zor sonuçlar.
5. Öğrenme `learning.every_days` günde bir (varsayılan 7) kendiliğinden tekrarlanır;
   *Şimdi öğren* ile elle de başlatılabilir.

Aynı işlemler komut satırından da yapılabilir:

```bat
cd bot
.venv\Scripts\python.exe run.py download --timeframes H1     :: tüm sembollerin verisi
.venv\Scripts\python.exe run.py research --timeframe H1      :: araştırma, sonuç: data\research_H1.json
```

Saklı testi geçmek gelecekte kazanacağını garanti etmez: çok sayıda sembol ve aday denendiği
için bazı geçişler şans eseri olabilir. Aktif semboller demoda haftalarca izlenmeden gerçek
hesaba geçilmemelidir. İşlem başı %1 riskle iyi bir sistemden bile beklenebilecek getiri **ayda
birkaç yüzdedir**; "günde %3-5" gibi hedefler hesabı hızla eritecek kadar risk gerektirir.

> ⚠️ Geçmiş performans gelecekteki sonuçları garanti etmez. Kaldıraçlı forex/CFD işlemleri
> sermayenin tamamını kaybettirebilir.

## 5. Güvenlik önlemleri

- **Demo kilidi:** `allow_live: false` iken bot, hesap demo değilse başlamayı reddeder. Kontrol
  her turda tekrarlanır: bot çalışırken MT5'te gerçek hesaba geçilirse bot kendini durdurur.
- **Günlük zarar limiti:** Gün içinde (UTC) varlık %3 (ayarlanabilir) düşerse bot o gün yeni
  işlem açmaz. Gün başı varlık `bot/state.json`'a yazılır, bot yeniden başlatılınca limit sıfırlanmaz.
- **Zirveden düşüş limiti:** Varlık en yüksek değerinden %20 (`max_drawdown_pct`, 0 = kapalı)
  düşerse bot yeni işlem açmaz; *Botu başlat*'a tekrar basılınca zirve sıfırlanır ve devam eder.
- **Üst üste zarar koruması:** Bir sembolde son 5 (`max_consecutive_losses`) işlem zararla
  kapandıysa o sembolde 48 saat (`loss_pause_hours`) yeni işlem açılmaz. Bu kurallar backtest'te
  yoktur; canlı sonuçlar bu yüzden backtest'ten biraz farklı olabilir.
- **Maksimum açık pozisyon** sınırı vardır ve her sembolde en fazla 1 pozisyon açılır.
  "Ters sinyalde kapat" kapalıyken ters sinyal gelirse yeni işlem açılmaz (netting hesapta
  mevcut pozisyonu istemeden kapatmamak için).
- Bot sadece kendi açtığı işlemleri yönetir (`magic` numarası). MT5'te elle açtığınız
  işlemlere dokunmaz; uygulamadan da sadece botun pozisyonları kapatılabilir. `magic`
  uygulamadan değiştirilemez.
- **Hata dayanıklılığı:** Emir gönderilemezse (requote, bağlantı) aynı bar içinde 3 kez denenir.
  MT5 bağlantısı koparsa bot her turda yeniden bağlanmayı dener; düzelince Telegram'a bildirir.
  Bir semboldeki hata diğer sembolleri durdurmaz ve aynı hata tekrar tekrar bildirilmez.
- API, token olmadan hiçbir şey yapmaz. `config.json` dosyası şifre ve token içerir;
  git'e eklenmez (`.gitignore`).
- **Hesap tipi:** Bot başlarken hesabın *hedging* mi *netting* mi olduğunu konsola yazar.
  Bot ikisinde de çalışır, ancak "Ters sinyalde kapat" seçeneğini açık tutmanız backtest ile
  en tutarlı davranışı verir.

## 6. Kripto fiyatları

Uygulamanın **Kripto** sekmesi, seçtiğiniz coinlerin anlık fiyatını ve 24 saatlik değişimini
gösterir (30 sn'de bir ve aşağı çekince yenilenir). Fiyatlar bot üzerinden CoinGecko'nun
ücretsiz API'sinden gelir; bot sonucu 60 sn saklar. CoinGecko'ya ulaşılamazsa son bilinen
fiyatlar uyarıyla gösterilir.

Coinleri `config.json` içinde değiştirebilirsiniz. Ad, coingecko.com'daki coin sayfasının
adresindeki addır (ör. `coingecko.com/en/coins/solana` → `solana`):

```json
"crypto": { "coins": ["bitcoin", "ethereum", "cardano", "solana"], "currency": "usd" }
```

`currency` için `usd`, `eur`, `try` gibi değerler kullanılabilir.

## 7. Telegram bildirimleri (opsiyonel)

İşlem açılıp kapandığında ve hata olduğunda telefonunuza anında bildirim gelir, uygulama
kapalı olsa bile:

1. Telegram'da **@BotFather**'a `/newbot` yazın ve verilen token'ı `telegram.bot_token`'a yazın.
2. Kendi botunuza bir mesaj atın, ardından tarayıcıda
   `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini açın. `chat.id` değerini
   `telegram.chat_id`'ye yazın.

## 8. Geliştirme

```bash
cd bot
pip install -r requirements-dev.txt
python -m pytest                 # testler (MT5 gerekmez)
python run.py --fake             # MT5 olmadan sahte fiyatlarla bot + API (Mac/Linux'ta da çalışır)
python run.py --fake backtest --compare
```

`--fake` modunda rastgele fiyat üretilir. Uygulamayı denemek için kullanılır; buradaki
backtest sonuçlarının gerçek piyasayla ilgisi yoktur.

Yeni strateji eklemek için `bot/gcmbot/strategies.py` dosyasında `Strategy` sınıfından
türetin ve `STRATEGIES` listesine ekleyin. Uygulama yeni stratejiyi otomatik gösterir.

```
bot/
  run.py                 giriş noktası (sunucu + backtest komutları)
  gcmbot/
    broker.py            MT5 bağlantısı + sahte broker
    mt4.py               MT4 köprüsü (GcmBotBridge EA ile)
    strategies.py        stratejiler
    indicators.py        EMA, RSI, ATR, Bollinger
    risk.py              lot hesabı, SL/TP
    engine.py            canlı işlem döngüsü, günlük zarar limiti, Telegram
    backtest.py          backtest, karşılaştırma, optimizasyon
    crypto.py            kripto fiyatları (CoinGecko)
    api.py               mobil uygulamanın REST API'si
  mt4/GcmBotBridge.mq4   MT4 içinde çalışan köprü EA
  tests/
mobile/                  Flutter uygulaması (iOS, Android, web)
  lib/screens/           Panel, Pozisyonlar, Strateji, Backtest, Kripto, Kayıtlar
```
