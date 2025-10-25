package com.example.kriptotakip

// KriptoAPI.kt

import retrofit2.http.GET // Bu satır, package'dan hemen sonra gelmeli!

interface KriptoAPI {

    // API çağrısının yolu ve parametreleri
    @GET("simple/price?ids=bitcoin,ethereum,cardano&vs_currencies=usd")
    suspend fun getKriptoFiyatlari(): KriptoModel
}