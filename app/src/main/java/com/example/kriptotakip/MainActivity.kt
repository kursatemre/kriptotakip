package com.example.kriptotakip

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.kriptotakip.ui.theme.KriptoTakipTheme

import androidx.compose.material3.ExperimentalMaterial3Api

// ######################################################################
// 1. ANA ETKİNLİK SINIFI (Temiz, Tek Tanımlı)
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
// MainActivity sınıfı TAM BURADA BİTER.

// ######################################################################
// 2. TÜM @Composable FONKSİYONLAR BURADAN BAŞLAR (SINIFIN DIŞI)
// ######################################################################

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KriptoScreen(viewModel: KriptoViewModel) {
    // ViewModel'deki durumu izle.
    val durum by viewModel.kriptoDurum.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Kripto Takip (Compose)") })
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
            contentAlignment = Alignment.Center
        ) {
            // Durum Kontrolü
            when (durum) {
                is KriptoDurum.Yukleniyor -> YukleniyorEkrani()
                is KriptoDurum.Basarili -> KriptoVeriEkrani((durum as KriptoDurum.Basarili).veriler)
                is KriptoDurum.Hata -> HataEkrani((durum as KriptoDurum.Hata).mesaj, viewModel)
            }
        }
    }
}

// Yükleniyor Ekranı
@Composable
fun YukleniyorEkrani() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        Spacer(modifier = Modifier.height(16.dp))
        Text("Fiyatlar Yükleniyor...")
    }
}

// Hata Ekranı
@Composable
fun HataEkrani(mesaj: String, viewModel: KriptoViewModel) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = "Hata Oluştu:\n$mesaj",
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(16.dp)
        )
        Button(onClick = { viewModel.fetchKriptoFiyatlari() }) {
            Text("Tekrar Dene")
        }
    }
}

// Başarılı Veri Ekranı
@Composable
fun KriptoVeriEkrani(model: KriptoModel) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        KriptoFiyatKarti(isim = "Bitcoin", fiyat = model.bitcoin?.usd)
        Spacer(modifier = Modifier.height(8.dp))
        KriptoFiyatKarti(isim = "Ethereum", fiyat = model.ethereum?.usd)
        Spacer(modifier = Modifier.height(8.dp))
        KriptoFiyatKarti(isim = "Cardano", fiyat = model.cardano?.usd)
    }
}

// Kripto Fiyat Kartı Bileşeni
@Composable
fun KriptoFiyatKarti(isim: String, fiyat: Double?) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(isim, style = MaterialTheme.typography.titleLarge)

            val gosterilecekFiyat = if (fiyat != null) {
                String.format("$%.2f", fiyat)
            } else {
                "Veri Yok"
            }

            Text(gosterilecekFiyat, style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.secondary)
        }
    }
}