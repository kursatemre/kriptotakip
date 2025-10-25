package com.example.kriptotakip

class kriptomodel// KriptoModel.kt

// 1. Dış Katman Sınıfı (JSON'daki en dıştaki süslü parantezler)
// Retrofit ve Gson, JSON'ı haritalayarak buraya otomatik dolduracak.
data class KriptoModel(
    val bitcoin: Fiyat?,
    val ethereum: Fiyat?,
    val cardano: Fiyat?
    // İleride buraya daha fazla kripto ekleyebilirsiniz.
)

// 2. Fiyat Sınıfı (JSON'daki her kriptonun içindeki "usd" değerini tutar)
data class Fiyat(
    val usd: Double // Fiyatı Double (ondalıklı sayı) olarak alıyoruz
) {
}