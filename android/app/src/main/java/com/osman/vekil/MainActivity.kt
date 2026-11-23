package com.osman.vekil

import android.Manifest
import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.android.material.textfield.TextInputEditText

class MainActivity : AppCompatActivity() {

    private lateinit var tvStatus: TextView
    private lateinit var swServis: androidx.appcompat.widget.SwitchCompat
    private var anahtarKodla = false  // anahtarı kod çevirirken dinleyici servisi tekrar oynatmasın
    private lateinit var tvGecmis: TextView
    private lateinit var svGecmis: android.widget.ScrollView
    private lateinit var btnMic: KaraDelik

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Kapatma tuşu / gezinme çubuğu uzun basış (dijital asistan): panel aç, ekran gösterme.
        if (intent?.action == Intent.ACTION_ASSIST) {
            simdiDinle()
            finish()
            return
        }
        setContentView(R.layout.activity_main)

        tvStatus = findViewById(R.id.tvStatus)
        swServis = findViewById(R.id.swServis)
        swServis.setOnCheckedChangeListener { _, acik ->
            if (anahtarKodla) return@setOnCheckedChangeListener
            val kapali = VekilService.durum == VekilService.Durum.KAPALI
            if (acik == kapali) servisToggle()
        }
        tvGecmis = findViewById(R.id.tvGecmis)
        svGecmis = findViewById(R.id.svGecmis)
        btnMic = findViewById(R.id.btnMic)

        VekilService.durumCallback = { durum -> runOnUiThread { durumGuncelle(durum) } }
        VekilService.gecmisCallback = { runOnUiThread { gecmisGuncelle() } }

        // Gemini gibi: dokun = şimdi dinle. Basılı tut = Vekil'i kapat/aç.
        btnMic.setOnClickListener { btnMic.tetikle(); simdiDinle() }
        btnMic.setOnLongClickListener { servisToggle(); true }
        findViewById<TextView>(R.id.tvAyarlar).setOnClickListener { ayarlarGoster() }
        findViewById<TextView>(R.id.tvTemizle).setOnClickListener {
            VekilService.gecmis.clear()
            gecmisGuncelle()
        }
        findViewById<TextView>(R.id.tvTelegram).setOnClickListener { telegramiAc() }
        findViewById<TextView>(R.id.tvErisim).setOnClickListener {
            startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }

        gecmisGuncelle()

        if (!Config.tamam(this)) {
            ayarlarGoster()
        } else {
            durumGuncelle(VekilService.durum)
            pilMuafiyetiIste()
            // Hep açık: uygulama açılınca servis kapalıysa kendi kalkar (anahtarla kapatılmadıysa).
            if (VekilService.durum == VekilService.Durum.KAPALI && !Config.kapatildi(this)) servisToggle()
        }
    }

    override fun onResume() {
        super.onResume()
        // Telefonu kullanma izni (erişilebilirlik) kapalıysa göster; ayardan dönünce güncellenir.
        findViewById<TextView>(R.id.tvErisim).visibility =
            if (VekilErisim.aktif == null) View.VISIBLE else View.GONE
    }

    override fun onDestroy() {
        VekilService.durumCallback = null
        VekilService.gecmisCallback = null
        super.onDestroy()
    }

    /** Vekil'in Telegram sohbeti: Telegram yüklüyse orada, değilse tarayıcıda açılır. */
    private fun telegramiAc() {
        val uygulamada = Intent(Intent.ACTION_VIEW, android.net.Uri.parse("tg://resolve?domain=$TELEGRAM_BOT"))
        try {
            startActivity(uygulamada)
        } catch (_: android.content.ActivityNotFoundException) {
            startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://t.me/$TELEGRAM_BOT")))
        }
    }

    companion object {
        private const val TELEGRAM_BOT = "VekiL00_bot"
    }

    private fun gecmisGuncelle() {
        tvGecmis.text = VekilService.gecmis.joinToString("\n\n") { (soru, cevap) ->
            "> $soru\n$cevap"
        }
        svGecmis.post { svGecmis.fullScroll(View.FOCUS_DOWN) }
    }

    /** Gemini tarzı alt panel için "diğer uygulamaların üzerinde göster" izni. */
    private fun panelIzniIste(): Boolean {
        if (android.provider.Settings.canDrawOverlays(this)) return false
        startActivity(Intent(
            android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            android.net.Uri.parse("package:$packageName")
        ))
        return true
    }

    /** Servisin uyutulmaması için pil optimizasyonundan muafiyet ister (bir kez). */
    private fun pilMuafiyetiIste() {
        if (panelIzniIste()) return  // iki ayar ekranı üst üste açılmasın; dönünce sıradaki
        val pm = getSystemService(android.os.PowerManager::class.java)
        if (pm.isIgnoringBatteryOptimizations(packageName)) return
        try {
            startActivity(Intent(
                android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                android.net.Uri.parse("package:$packageName")
            ))
        } catch (_: Exception) {
            // Bazı ROM'larda bu ekran yok; kullanıcı elle ayarlar.
        }
    }

    private fun simdiDinle() {
        if (VekilService.durum == VekilService.Durum.KAPALI) {
            servisToggle()
            return
        }
        startService(Intent(this, VekilService::class.java).setAction(VekilService.ACTION_DINLE))
    }

    private fun servisToggle() {
        if (VekilService.durum == VekilService.Durum.KAPALI) {
            if (!izinKontrol()) {
                durumGuncelle(VekilService.Durum.KAPALI)  // anahtar geri kapalıya dönsün
                return
            }
            Config.kapatildiYaz(this, false)
            val intent = Intent(this, VekilService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
        } else {
            Config.kapatildiYaz(this, true)
            stopService(Intent(this, VekilService::class.java))
            durumGuncelle(VekilService.Durum.KAPALI)
        }
    }

    private fun durumGuncelle(durum: VekilService.Durum) {
        val (statusMetin, servisMetin, pulse) = when (durum) {
            VekilService.Durum.KAPALI       -> Triple("> KAPALI — ACMAK ICIN DOKUN", "KAPALI", false)
            VekilService.Durum.BASLATILIYOR -> Triple("> VEKIL", "AKTIF", false)
            VekilService.Durum.BEKLIYOR     -> Triple("> VEKIL", "AKTIF", false)  // bekleme: kara delik sakin
            VekilService.Durum.DINLIYOR     -> Triple("> DINLENIYOR...", "AKTIF", true)
            VekilService.Durum.ISLIYOR      -> Triple("> ISLIYOR...", "AKTIF", true)
            VekilService.Durum.OYNATILIYOR  -> Triple("> YANITLIYOR...", "AKTIF", true)
            VekilService.Durum.CALISIYOR    -> Triple("> TELEFONDA CALISIYOR...", "AKTIF", true)
            VekilService.Durum.HATA         -> Triple("> HATA", "HATA", false)
        }

        tvStatus.text = statusMetin
        anahtarKodla = true
        swServis.isChecked = durum != VekilService.Durum.KAPALI && durum != VekilService.Durum.HATA
        anahtarKodla = false
        swServis.text = servisMetin
        swServis.setTextColor(getColor(if (swServis.isChecked) R.color.accent else R.color.fg2))
        // Başlarken yuvarlak soluk kırmızı; hazır olunca tam kırmızı (renk seçicideki "açık" rengi).
        swServis.thumbTintList = if (durum == VekilService.Durum.BASLATILIYOR)
            android.content.res.ColorStateList.valueOf(getColor(R.color.accent_dim))
        else
            getColorStateList(R.color.anahtar_ibre)

    }

    private fun ayarlarGoster() {
        val dialog = layoutInflater.inflate(android.R.layout.simple_list_item_2, null)
        AlertDialog.Builder(this)
            .setTitle("Vekil — Bağlantı Ayarları")
            .setMessage("Render URL ve token gir:")
            .apply {
                // İki EditText için basit dialog
                val layout = android.widget.LinearLayout(this@MainActivity).apply {
                    orientation = android.widget.LinearLayout.VERTICAL
                    setPadding(48, 16, 48, 0)
                }
                val etUrl = android.widget.EditText(this@MainActivity).apply {
                    hint = "https://vekil.onrender.com"
                    setText(Config.renderUrl(this@MainActivity))
                    setTextColor(getColor(R.color.fg))
                    setHintTextColor(getColor(R.color.fg2))
                }
                val etToken = android.widget.EditText(this@MainActivity).apply {
                    hint = "sesli token (40 karakter)"
                    setText(Config.sesliToken(this@MainActivity))
                    setTextColor(getColor(R.color.fg))
                    setHintTextColor(getColor(R.color.fg2))
                }
                layout.addView(etUrl)
                layout.addView(etToken)
                setView(layout)
                setPositiveButton("Kaydet") { _, _ ->
                    if (!Config.kaydet(this@MainActivity, etUrl.text.toString(), etToken.text.toString())) {
                        android.widget.Toast.makeText(this@MainActivity, "Adres https:// ile başlamalı, kaydedilmedi.",
                            android.widget.Toast.LENGTH_LONG).show()
                    }
                }
                setNegativeButton("İptal", null)
            }
            .show()
    }

    // Dinleme için şart olan sadece mikrofon. Bildirim izni BİLEREK istenmiyor (Kullanıcı: "üstte bildirim simgesi
    // durmasın"): Android 13+ izinsiz de hep açık servise izin veriyor, bildirim sadece görünmüyor.
    // Rehber ve arama sadece "annemi ara" için (verilmese de Vekil çalışır).
    private val gerekliIzinler: List<String> = listOf(Manifest.permission.RECORD_AUDIO)
    private val istegeBagliIzinler = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE)

    private fun izinVar(izin: String) =
        ContextCompat.checkSelfPermission(this, izin) == PackageManager.PERMISSION_GRANTED

    private fun izinKontrol(): Boolean {
        val eksik = (gerekliIzinler + istegeBagliIzinler).filterNot(::izinVar)
        if (eksik.isNotEmpty()) ActivityCompat.requestPermissions(this, eksik.toTypedArray(), 1)
        return gerekliIzinler.all(::izinVar)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && gerekliIzinler.all(::izinVar) &&
            VekilService.durum == VekilService.Durum.KAPALI) {
            servisToggle()
        }
    }
}
