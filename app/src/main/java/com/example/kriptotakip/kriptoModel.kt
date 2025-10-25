// KriptoModel.kt

package com.example.kriptotakip

data class KriptoModel(
    val bitcoin: KriptoFiyat?,
    val ethereum: KriptoFiyat?,
    val cardano: KriptoFiyat?
)

data class KriptoFiyat(
    val usd: Double?
)

sealed class KriptoDurum {
    object Yukleniyor : KriptoDurum()
    data class Basarili(val veriler: KriptoModel) : KriptoDurum()
    data class Hata(val mesaj: String) : KriptoDurum()
}