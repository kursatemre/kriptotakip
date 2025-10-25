package com.example.kriptotakip

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import com.example.kriptotakip.RetrofitClient


// Veri Durumu Sınıfı
sealed class KriptoDurum {
    object Yukleniyor : KriptoDurum()
    data class Basarili(val veriler: KriptoModel) : KriptoDurum()
    data class Hata(val mesaj: String) : KriptoDurum()
}

// ViewModel Sınıfı (YALNIZCA BİR KEZ TANIMLANDI)
class KriptoViewModel : ViewModel() {

    private val _kriptoDurum = MutableStateFlow<KriptoDurum>(KriptoDurum.Yukleniyor)
    val kriptoDurum: StateFlow<KriptoDurum> = _kriptoDurum

    // ViewModel oluşturulur oluşturulmaz veriyi çekmeye başla
    init {
        fetchKriptoFiyatlari()
    }

    // Coroutines ile Asenkron Veri Çekme Fonksiyonu
    fun fetchKriptoFiyatlari() {
        viewModelScope.launch {
            try {
                // API Servisi ile veriyi çek
                val response = RetrofitClient.apiService.getKriptoFiyatlari()

                // Başarılı: Durumu güncelleyerek arayüze bildir
                _kriptoDurum.value = KriptoDurum.Basarili(response)

            } catch (e: Exception) {
                // Hata oluştu: Durumu 'Hata' olarak güncelleyerek arayüze bildir
                _kriptoDurum.value = KriptoDurum.Hata("Veri çekilemedi: ${e.localizedMessage}")
            }
        }
    }
}