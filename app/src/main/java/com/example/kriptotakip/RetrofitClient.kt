package com.example.kriptotakip

// RetrofitClient.kt

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

// Base URL: API'nin kök adresi.
private const val BASE_URL = "https://api.coingecko.com/api/v3/"

// 1. Retrofit nesnesini sadece bir kez oluştur (val retrofit)
val retrofit: Retrofit by lazy {
    Retrofit.Builder()
        .baseUrl(BASE_URL)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
}

// 2. Uygulama genelinde kullanacağımız API hizmeti (OBJECT)
object RetrofitClient {
    // apiService, bu object'in içinde bir değişkendir
    val apiService: KriptoAPI by lazy {
        retrofit.create(KriptoAPI::class.java)
    }
}