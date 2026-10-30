"""Kripto fiyatları (eski KriptoTakip uygulaması): CoinGecko'nun ücretsiz API'si.

CoinGecko ücretsiz uç noktada fiyatları ~60 sn önbellekte tutar ve dakikalık istek
sınırı vardır. Bu yüzden sonuç burada da 60 sn saklanır: uygulama ne sıklıkla sorarsa
sorsun CoinGecko'ya dakikada en fazla bir istek gider.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

API_URL = "https://api.coingecko.com/api/v3/simple/price"
CACHE_SECONDS = 60


class CryptoError(Exception):
    pass


def fetch_coingecko(coins: list[str], currency: str) -> dict:
    query = urllib.parse.urlencode({
        "ids": ",".join(coins), "vs_currencies": currency, "include_24hr_change": "true",
    })
    req = urllib.request.Request(f"{API_URL}?{query}",
                                 headers={"Accept": "application/json", "User-Agent": "gcmbot"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


class CryptoPrices:
    def __init__(self, fetch=fetch_coingecko):
        self._fetch = fetch
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._time = 0.0
        self._data: dict | None = None

    def get(self, coins: list[str], currency: str) -> dict:
        key = (tuple(coins), currency)
        with self._lock:
            cached = self._data if self._key == key else None
            if cached and time.time() - self._time < CACHE_SECONDS:
                return cached
            try:
                raw = self._fetch(coins, currency)
            except Exception as e:
                if not cached:
                    raise CryptoError(f"Kripto fiyatları alınamadı: {e}") from e
                # Eski veri hiç veri olmamasından iyidir; 60 sn sonra tekrar denenir
                self._time, self._data = time.time(), {**cached, "stale": True}
                return self._data
            self._key, self._time = key, time.time()
            self._data = {
                "currency": currency,
                "updated": int(self._time),
                "stale": False,
                "coins": [
                    {
                        "id": c,
                        "price": raw.get(c, {}).get(currency),
                        "change_24h_pct": raw.get(c, {}).get(f"{currency}_24h_change"),
                    }
                    for c in coins
                ],
            }
            return self._data
