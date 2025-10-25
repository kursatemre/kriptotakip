// KriptoViewModel.kt

package com.example.kriptotakip

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

class KriptoViewModel : ViewModel() {

    private val REFRESH_INTERVAL_MS = TimeUnit.SECONDS.toMillis(15) // 15 Saniye

    // Mevcut durum akışları
    private val _kriptoDurum = MutableStateFlow<KriptoDurum>(KriptoDurum.Yukleniyor)
    val kriptoDurum: StateFlow<KriptoDurum> = _kriptoDurum

    // Yenileme Durumu (Pull-to-Refresh çubuğu için)
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    // Başarıyla çekilmiş son veriyi (önceki veriyi) saklayacak değişken
    var sonBasariliVeri: KriptoModel? = null

    private var autoRefreshJob: Job? = null

    init {
        // ViewModel ilk oluşturulduğunda otomatik yenilemeyi başlat
        startAutoRefresh()
    }

    private fun startAutoRefresh() {
        // Eğer zaten bir iş çalışıyorsa durdur
        autoRefreshJob?.cancel()

        autoRefreshJob = viewModelScope.launch {
            while (true) {
                // Her döngüde fiyatları çek
                fetchKriptoFiyatlari(isAutoRefresh = true)

                // 15 saniye bekle
                delay(REFRESH_INTERVAL_MS)
            }
        }
    }

    // Uygulama kapatılınca job iptal edilir
    override fun onCleared() {
        super.onCleared()
        autoRefreshJob?.cancel()
    }

    // Manuel çekme (Pull-to-Refresh) ve Otomatik çekme için tek bir fonksiyon
    fun fetchKriptoFiyatlari(isAutoRefresh: Boolean = false) {
        // Otomatik yenilemede, çubuğu döndürmek istemeyebiliriz.
        // Ancak bu senaryoda hem manuel hem de otomatik yenilemede çubuğu gösteriyoruz.
        _isRefreshing.value = true

        viewModelScope.launch {
            try {
                val response = RetrofitClient.apiService.getKriptoFiyatlari()

                // Başarılı olursa:
                // 1. Yeni veriyi, bir sonraki güncelleme için 'önceki' veri olarak kaydet
                // Not: sonBasariliVeri zaten bir önceki veriyi tuttuğu için bu satır gereksizdir.
                // Yeni veriyi direkt _kriptoDurum'a atayarak mantığı basitleştiriyoruz.

                // 2. Durumu yeni veriyle güncelle
                _kriptoDurum.value = KriptoDurum.Basarili(response)

                // 3. Mevcut yeni veriyi, bir sonraki çekim için "önceki veri" olarak sakla
                sonBasariliVeri = response

            } catch (e: Exception) {
                // Hata oluşursa, son başarılı veriyi ekranda tutarak sadece hata mesajı gösteririz
                val hataMesaji = "Veri çekilemedi: ${e.localizedMessage}"

                // Sadece veriler boşken hata durumu göstermek daha iyi kullanıcı deneyimidir.
                if (sonBasariliVeri == null) {
                    _kriptoDurum.value = KriptoDurum.Hata(hataMesaji)
                } else {
                    // Veri varsa, hata oluştu ama önceki veriyi gösteriyoruz
                }

            } finally {
                // İşlem bittiğinde, yenileniyor durumunu KAPAT
                _isRefreshing.value = false
            }
        }
    }

    // Pull-to-Refresh (Manuel) için ayrı bir çağrı fonksiyonu
    fun refreshManually() {
        // Yenileme işlemini yap
        fetchKriptoFiyatlari(isAutoRefresh = false)

        // Otomatik yenileme döngüsünün kesintiye uğramaması için ekstra işlem gerekmez.
        // fetchKriptoFiyatlari çağrısı zaten otomatik yenileme job'ının dışında çalışacaktır.
    }
}