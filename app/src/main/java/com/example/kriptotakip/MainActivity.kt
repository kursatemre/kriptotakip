// MainActivity.kt

package com.example.kriptotakip

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.material3.pullrefresh.PullRefreshIndicator
import androidx.compose.material3.pullrefresh.pullRefresh
import androidx.compose.material3.pullrefresh.rememberPullRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.kriptotakip.ui.theme.KriptoTakipTheme
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward

// ######################################################################
// 1. ANA ETKİNLİK SINIFI
// ######################################################################

@OptIn(ExperimentalMaterial3Api::class)
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            KriptoTakipTheme {
                // ViewModel'i oluştur
                val viewModel: KriptoViewModel = viewModel()
                // KriptoScreen'i çağır
                KriptoScreen(viewModel = viewModel)
            }
        }
    }
}

// ######################################################################
// 2. COMPOSABLE FONKSİYONLAR
// ######################################################################

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KriptoScreen(viewModel: KriptoViewModel) {
    val durum by viewModel.kriptoDurum.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()

    // Yenileme durumunu yöneten state (Manuel çekme için)
    val pullRefreshState = rememberPullRefreshState(
        refreshing = isRefreshing,
        onRefresh = { viewModel.refreshManually() } // Manuel çekme fonksiyonunu çağır
    )

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Kripto Takip (Compose)") })
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .pullRefresh(pullRefreshState),
            contentAlignment = Alignment.Center
        ) {
            // Durum Kontrolü
            when (durum) {
                is KriptoDurum.Yukleniyor -> YukleniyorEkrani()
                is KriptoDurum.Basarili -> KriptoVeriEkrani((durum as KriptoDurum.Basarili).veriler, viewModel)
                is KriptoDurum.Hata -> HataEkrani((durum as KriptoDurum.Hata).mesaj, viewModel)
            }

            // Yenileme çubuğunu en üste yerleştir
            PullRefreshIndicator(
                refreshing = isRefreshing,
                state = pullRefreshState,
                modifier = Modifier.align(Alignment.TopCenter),
                contentColor = MaterialTheme.colorScheme.primary // Rengi ana renk yap
            )
        }
    }
}

// ... (YukleniyorEkrani ve HataEkrani fonksiyonları değişmedi, ancak tutarlılık için eklenmiştir)
@Composable
fun YukleniyorEkrani() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        Spacer(modifier = Modifier.height(16.dp))
        Text("Fiyatlar Yükleniyor...")
    }
}

@Composable
fun HataEkrani(mesaj: String, viewModel: KriptoViewModel) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = "Hata Oluştu:\n$mesaj",
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(16.dp)
        )
        // Otomatik yenileme çalıştığı için manuel "Tekrar Dene" butonunu kaldırmak daha doğru olabilir
        // Ama kullanıcıya kontrol vermek için tutalım:
        Button(onClick = { viewModel.refreshManually() }) {
            Text("Tekrar Dene")
        }
    }
}


@Composable
fun KriptoVeriEkrani(model: KriptoModel, viewModel: KriptoViewModel) {
    // ViewModel'den son başarılı veriyi çek (Bu, bir önceki 15 saniyedeki fiyattır)
    val oncekiVeri = viewModel.sonBasariliVeri

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        KriptoFiyatKarti(
            isim = "Bitcoin",
            mevcutFiyat = model.bitcoin?.usd,
            oncekiFiyat = oncekiVeri?.bitcoin?.usd // Önceki fiyatı gönderiyoruz
        )
        Spacer(modifier = Modifier.height(8.dp))

        KriptoFiyatKarti(
            isim = "Ethereum",
            mevcutFiyat = model.ethereum?.usd,
            oncekiFiyat = oncekiVeri?.ethereum?.usd
        )
        Spacer(modifier = Modifier.height(8.dp))

        KriptoFiyatKarti(
            isim = "Cardano",
            mevcutFiyat = model.cardano?.usd,
            oncekiFiyat = oncekiVeri?.cardano?.usd
        )
    }
}

@Composable
fun KriptoFiyatKarti(isim: String, mevcutFiyat: Double?, oncekiFiyat: Double?) {

    // Fiyat farkını hesapla
    val fark = if (mevcutFiyat != null && oncekiFiyat != null) {
        mevcutFiyat - oncekiFiyat
    } else {
        null
    }

    // Fiyat değişimine göre rengi ve oku belirle
    val farkRenk = when {
        fark == null || fark == 0.0 -> MaterialTheme.colorScheme.onSurfaceVariant // Değişim yok veya ilk yükleme
        fark > 0 -> Color.Green.copy(alpha = 0.8f) // Yükseldi
        else -> Color.Red.copy(alpha = 0.8f)   // Düştü
    }

    val arrowIcon = when {
        fark == null || fark == 0.0 -> null
        fark > 0 -> Icons.Default.ArrowUpward // Yeşil ok
        else -> Icons.Default.ArrowDownward  // Kırmızı ok
    }

    val gosterilecekFiyat = if (mevcutFiyat != null) {
        String.format("$%.2f", mevcutFiyat)
    } else {
        "Veri Yok"
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Column(modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp))
        {
            // 1. Kripto Adı
            Text(isim, style = MaterialTheme.typography.titleLarge)
            Spacer(modifier = Modifier.height(8.dp))

            // 2. Fiyat ve Fark Bilgisi (Yan yana)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Mevcut Fiyat
                Text(
                    gosterilecekFiyat,
                    style = MaterialTheme.typography.headlineSmall,
                    color = MaterialTheme.colorScheme.primary
                )

                // Fiyat Farkı ve Ok
                if (fark != null && fark != 0.0) {
                    val gosterilecekFark = String.format("%s%.2f", if (fark > 0) "+" else "", fark)

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        // Ok Simgesi
                        arrowIcon?.let {
                            Icon(
                                imageVector = it,
                                contentDescription = null,
                                tint = farkRenk,
                                modifier = Modifier.size(24.dp)
                            )
                        }

                        // Fark Değeri
                        Text(
                            gosterilecekFark,
                            style = MaterialTheme.typography.bodyLarge,
                            color = farkRenk
                        )
                    }
                } else if (mevcutFiyat != null) {
                    Text(
                        "Değişim Yok",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}