package com.opendelegate.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.drawable.Icon
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.media.ToneGenerator
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.*
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * Hep açık dinleme servisi. Akış (OK Google gibi):
 *   "delegate bir bakar mısın" → bip + alt panel → konuşma canlı yazıya dökülür →
 *   susunca ya da durdur'a basınca sunucuya gider → cevap panelde yazılır ve okunur.
 *
 * Paneldeki butonlar ana thread'den [panelMic] / [panelKapandi] ile gelir;
 * ses döngüsü IO thread'inde bu bayrakları okur. Tek kaynak: [durum].
 */
class VekilService : Service() {

    companion object {
        private const val TAG = "VekilService"
        private const val KANAL_ID = "vekil_sessiz"
        private const val BILDIRIM_ID = 1
        private const val ORNEKLEME = 16000
        private const val BUFFER = 4096          // uyanma dinlemesi: 256 ms'lik parçalar
        private const val PARCA = 1024           // komut dinlemesi: 64 ms, panel akıcı tepki versin
        private const val MAKS_KAYIT_MS = 20_000L
        private const val SESSIZLIK_ESIK = 300   // RMS; sessiz ortamda altı sessizlik sayılır
        private const val SESSIZLIK_TAVAN = 1_500 // gürültülü ortamda eşik en çok buraya çıkar
        private const val UYKU_ESIK_MIN = 140      // bundan sessiz parçada Vosk çalışmaz (pil)
        private const val ACIK_PARCA = 7           // seste sonra ~1,8 sn daha beslenir
        private const val GURULTU_PENCERE = 20   // son ~5 sn (20 x 256 ms) uyanma dinlemesinden ortam sesi
        private const val SESSIZLIK_SURE_MS = 1_500L
        private const val ILK_SES_BEKLEME_MS = 5_000L  // panel açılıp konuşulmazsa kapanır
        private const val KUYRUK_MS = 800L  // sesle uyanınca bu süredeki ses uyanma cümlesinin sonu sayılır

        // Uyanma cümlesi: "delegate bir bakar mısın". Vosk Türkçe modelinde "delegate" yok (sözlükte olmayan kelime
        // gramerden sessizce düşer), "delege" var; Türkçe konuşan "delegate"i buna yakın söyler. Dört kelime birden
        // aranır: tek kelimeye göre çok daha az yanlış uyanır.
        private const val UYANMA_GRAMERI = "[\"delege bir bakar mısın\", \"[unk]\"]"
        // Tanıyıcının yazabileceği ad biçimleri ("vekil": eski sürümle uyum).
        private val UYANMA_ADLARI = listOf("delege", "delegat", "vekil")

        const val ACTION_DINLE = "com.opendelegate.app.DINLE"   // "delegate bir bakar mısın" demekle aynı
        const val ACTION_KAPAT = "com.opendelegate.app.KAPAT"   // dinlemeyi tamamen kapat
        const val EXTRA_DENEME_WAV = "deneme_wav"          // sadece adb denemesi: mikrofon yerine bu ses
        // Sunucu buna göre telefonda iş yaptırır: 2 = alarm, fener...; 3 = ekranı da kullanır (mesaj, her iş).
        const val SURUM = 4  // 4: "kapat" komutu (panel_kapat) ve sohbetten telefona iş (uzun yoklama + sonuç)
        private const val AJAN_MAKS_ADIM = 25  // ekrandan iş: en çok bu kadar adım (sunucu da sınırlar)
        private const val TELEFON_UZUN_YOKLAMA_SN = 25  // sunucu iş yoksa bu kadar bekletir (okuma zaman aşımı 60 sn)
        private const val TELEFON_GOREV_ARALIK_MS = 20_000L  // uzun yoklamayı bilmeyen sunucuda yoklama sıklığı
        private const val TELEFON_GOREV_HATA_BEKLE_MS = 15_000L

        @Volatile var durum: Durum = Durum.KAPALI
            private set

        var durumCallback: ((Durum) -> Unit)? = null

        /** Son mikrofon seviyesi (RMS); ana ekrandaki kara delik konuşmaya tepki versin diye. */
        @Volatile var sonSeviye = 0

        // Konuşma dökümü: (soru, cevap). MainActivity yazı olarak gösterir.
        val gecmis = mutableListOf<Pair<String, String>>()
        var gecmisCallback: (() -> Unit)? = null
    }

    enum class Durum { KAPALI, BASLATILIYOR, BEKLIYOR, DINLIYOR, ISLIYOR, OYNATILIYOR, CALISIYOR, HATA }

    /** Sunucunun cevabı: okunacak ses, yapılamayan telefon işi (varsa), cevabın yazısı. */
    private class Cevap(val mp3: ByteArray, val sorun: String?, val metin: String)

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private var model: Model? = null
    @Volatile private var calisiyor = false
    private var uyanik: android.os.PowerManager.WakeLock? = null
    private lateinit var panel: Panel

    // Oturum bayrakları: ana thread yazar, ses thread'i okur.
    @Volatile private var elleTetik = false     // panel/bildirim/uygulama butonu: dinlemeye başla
    @Volatile private var konusmaBitti = false  // durdur'a basıldı: dinlemeyi bitir, gönder
    @Volatile private var iptal = false         // X'e basıldı: her şeyi bırak

    @Volatile private var denemeSesi: Pair<ByteArray, String>? = null  // DenemeAlici: sonraki tur bu sesle (veri, tür)
    @Volatile private var bekleyenMedya: List<String> = emptyList()  // cevap okununca yapılacak müzik komutları
    @Volatile private var bekleyenIsler: List<JSONObject> = emptyList()  // cevap okununca: mesaj, ekranda
    @Volatile private var devamDinle = false  // OpenDelegate soru sordu: cevabı uyanma cümlesi beklemeden dinle
    @Volatile private var panelKapatIstendi = false  // efendim "kapat" dedi: panel kapansın, tekrar dinlenmesin
    @Volatile private var ajanDur = false     // ekrandan iş yaparken durdur'a basıldı
    @Volatile private var bekleyenYazi: String? = null  // panelden yazılan soru: sıradaki tur bununla
    @Volatile private var bekleyenSesEki: String? = null  // yazıdan sese geçildi: bu metne devam dinlenecek
    @Volatile private var yaziyaGecildi = false  // dinlerken klavyeye geçildi: kaydı bırak, gönderme
    private var uyanmaKuyrugu = false  // bu tur sesle uyanıldı: kaydın başı uyanma cümlesinin sonu (ses thread'i)

    // Ortam gürültüsü: uyanma dinlemesindeki en sessiz parçalar. Dışarıda (yol, kalabalık) sabit
    // eşik hep "konuşuyor" sanıp 20 sn kaydediyordu; eşik ortama göre ayarlanır.
    private val gurultu = IntArray(GURULTU_PENCERE) { SESSIZLIK_ESIK }
    private var gurultuSira = 0

    private val sesYoneticisi by lazy { getSystemService(AudioManager::class.java) }
    // Dinlerken ve konuşurken müzik/video dursun (Gemini gibi); bitince kendiliğinden devam eder.
    private val sesOdagi by lazy {
        AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build())
            .build()
    }

    @Volatile private var aktifCagri: Call? = null
    private var oynatici: MediaPlayer? = null              // sadece ana thread
    private var oynatmaBitti: CompletableDeferred<Unit>? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        kanalOlustur()
        panel = Panel(this, mic = ::panelMic, kapatildi = ::panelKapandi,
            yaziyaGec = ::panelYaziyaGec, yaziGonder = ::panelYaziGonder, sesEkle = ::panelSesEkle,
            servisiKapat = ::servisiKapat)
        startForeground(BILDIRIM_ID, bildirimOlustur("> BASLATILIYOR..."))
        // Ekran kapalıyken işlemci uyumasın; yoksa mikrofon döngüsü ve HTTP isteği duruyor.
        uyanik = getSystemService(android.os.PowerManager::class.java)
            .newWakeLock(android.os.PowerManager.PARTIAL_WAKE_LOCK, "vekil:dinleme")
            .apply { setReferenceCounted(false); acquire() }
        guncelle(Durum.BASLATILIYOR)
        scope.launch { modeli_yukle() }
        scope.launch { telefonGoreviDongusu() }
    }

    // Sistem servisi öldürürse yeniden başlatsın (hep açık kalsın).
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_DINLE -> if (durum == Durum.BEKLIYOR) {
                intent.getStringExtra(EXTRA_DENEME_WAV)?.let { denemeSesi = denemeSesiOku(it) }
                elleTetik = true
            }
            ACTION_KAPAT -> {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        calisiyor = false
        iptal = true
        aktifCagri?.cancel()
        sesiKes()
        scope.cancel()
        model?.close()
        uyanik?.let { if (it.isHeld) it.release() }
        uyanik = null
        panel.birak()
        durum = Durum.KAPALI
        durumCallback?.invoke(Durum.KAPALI)
        super.onDestroy()
    }

    // ---------- Panel butonları (ana thread) ----------

    private fun panelMic() {
        when (durum) {
            Durum.DINLIYOR -> konusmaBitti = true
            Durum.OYNATILIYOR -> sesiKes()
            Durum.BEKLIYOR -> elleTetik = true
            Durum.CALISIYOR -> {
                ajanDur = true
                aktifCagri?.cancel()
            }
            else -> {}
        }
    }

    /** Panelde klavyeye geçildi: dinliyorsa kaydı bırak (gönderme), OpenDelegate konuşuyorsa sustur. */
    private fun panelYaziyaGec() {
        when (durum) {
            Durum.DINLIYOR -> yaziyaGecildi = true
            Durum.OYNATILIYOR -> sesiKes()
            else -> {}
        }
    }

    /** Panelden yazılı soru: sıradaki tur bu yazıyla (iş sürüyorsa bitince) başlar. */
    private fun panelYaziGonder(metin: String) {
        bekleyenYazi = metin
        elleTetik = true
    }

    /** Panelde yazarken mikrofona dönüldü: [onEk] korunur, konuşulan buna eklenip panele geri yazılır. */
    private fun panelSesEkle(onEk: String) {
        bekleyenSesEki = onEk
        elleTetik = true
    }

    private fun panelKapandi() {
        iptal = true
        ajanDur = true
        aktifCagri?.cancel()
        sesiKes()
    }

    /** Paneldeki güç düğmesi: uygulamadaki AKTİF/KAPALI anahtarını kapatmakla aynı (kendiliğinden açılmaz). */
    private fun servisiKapat() {
        Log.i(TAG, "Panelden kapatıldı")
        Config.kapatildiYaz(this, true)
        android.widget.Toast.makeText(this, "OpenDelegate kapatıldı. Açmak için uygulamaya girin.",
            android.widget.Toast.LENGTH_SHORT).show()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun sesiKes() {
        oynatici?.let { p ->
            runCatching { p.stop() }
            p.release()
        }
        oynatici = null
        oynatmaBitti?.complete(Unit)
        oynatmaBitti = null
    }

    // ---------- Model ----------

    private suspend fun modeli_yukle() {
        try {
            val modelYolu = modelYoluHazirla()
            model = Model(modelYolu)
            Log.i(TAG, "Vosk modeli yüklendi: $modelYolu")
            calisiyor = true
            dinleme_dongusu()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "Model yüklenemedi: $e")
            guncelle(Durum.HATA)
            bildirimGuncelle("> HATA: model yüklenemedi")
        }
    }

    private fun modelKlasoru(): java.io.File? =
        filesDir.listFiles()?.firstOrNull {
            it.isDirectory && it.name.startsWith("vosk-model") && java.io.File(it, "final.mdl").exists()
        }

    private suspend fun modelYoluHazirla(): String = withContext(Dispatchers.IO) {
        modelKlasoru()?.let { return@withContext it.absolutePath }

        bildirimGuncelle("> MODEL INDIRILIYOR...")
        val url = "https://alphacephei.com/vosk/models/vosk-model-small-tr-0.3.zip"
        val zip = java.io.File(cacheDir, "vosk-tr.zip")

        http.newCall(Request.Builder().url(url).build()).execute().use { yanit ->
            if (!yanit.isSuccessful) throw RuntimeException("Model indirme hatası: ${yanit.code}")
            zip.outputStream().use { out -> yanit.body!!.byteStream().copyTo(out) }
        }

        bildirimGuncelle("> MODEL ACILIYOR...")
        val kok = filesDir.canonicalPath + java.io.File.separator
        java.util.zip.ZipInputStream(zip.inputStream()).use { zis ->
            var entry = zis.nextEntry
            while (entry != null) {
                val dosya = java.io.File(filesDir, entry.name)
                // Zip içindeki "../" yollar uygulama klasörünün dışına yazamasın.
                if (!dosya.canonicalPath.startsWith(kok)) throw SecurityException("Zip yolu dışarı taşıyor")
                if (entry.isDirectory) {
                    dosya.mkdirs()
                } else {
                    dosya.parentFile?.mkdirs()
                    dosya.outputStream().use { out -> zis.copyTo(out) }
                }
                entry = zis.nextEntry
            }
        }
        zip.delete()

        modelKlasoru()?.absolutePath ?: throw RuntimeException("Model klasörü bulunamadı")
    }

    // ---------- Dinleme ----------

    private fun bayta_cevir(buf: ShortArray, n: Int): ByteArray {
        val bytes = ByteArray(n * 2)
        for (i in 0 until n) {
            bytes[i * 2] = (buf[i].toInt() and 0xFF).toByte()
            bytes[i * 2 + 1] = (buf[i].toInt() shr 8 and 0xFF).toByte()
        }
        return bytes
    }

    private suspend fun dinleme_dongusu() = withContext(Dispatchers.IO) {
        val mdl = model ?: return@withContext

        val rec = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            ORNEKLEME,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            BUFFER * 4
        )
        val taniyici = Recognizer(mdl, ORNEKLEME.toFloat(), UYANMA_GRAMERI)
        // Gramersiz tanıyıcı: sadece komut sırasında beslenir, paneldeki canlı yazı için.
        val serbest = Recognizer(mdl, ORNEKLEME.toFloat())
        val pcmBuf = ShortArray(BUFFER)
        var hazirlik = GURULTU_PENCERE
        var acikKalan = 0
        var beslendi = false
        var onceki: ByteArray? = null

        rec.startRecording()
        bekliyor()
        Log.i(TAG, "Dinleme başladı")

        try {
            while (calisiyor) {
                val n = rec.read(pcmBuf, 0, BUFFER)
                if (n <= 0) continue
                val bytes = bayta_cevir(pcmBuf, n)
                val rms = rmsHesapla(pcmBuf, n)  // tek sefer: eskiden iki kez hesaplanıyordu
                gurultu[gurultuSira] = rms
                gurultuSira = (gurultuSira + 1) % GURULTU_PENCERE

                // Sohbetten gelen iş ekranda sürerken uyanma yok: sesli tur paneli devralıp "boşta"ya düşürüyor,
                // uygulamanın sonraki tıklaması paneli kapatıp işi yarıda bırakıyordu. Durdurmak: panel düğmesi.
                if (durum == Durum.CALISIYOR) {
                    if (beslendi) { taniyici.reset(); beslendi = false }
                    acikKalan = 0
                    onceki = null
                    continue
                }

                // Pil: sessiz ortamda Vosk'u boşuna çalıştırma. Ortam sesinin 2 katını aşan ses varken ve
                // sonrasında ~2,5 sn beslenir; ses başlarken bir önceki parça da verilir ki "vekil"in başı
                // kaçmasın. İlk ~5 sn (ortam sesi öğrenilirken) ve elle tetiklemede hep beslenir.
                val sesVar = rms > maxOf(UYKU_ESIK_MIN, gurultu.min() * 5 / 2)  // ortamın 2,5 katı
                if (hazirlik > 0) hazirlik--
                if (sesVar) {
                    if (acikKalan == 0) onceki?.let { taniyici.acceptWaveForm(it, it.size) }
                    acikKalan = ACIK_PARCA
                }
                if (!elleTetik && hazirlik == 0 && acikKalan == 0) {
                    if (beslendi) { taniyici.reset(); beslendi = false }  // yarım kalan ara sonuç birikmesin
                    onceki = bytes
                    continue
                }
                if (acikKalan > 0) acikKalan--
                beslendi = true

                // Cümle bitmesini beklemeden de uyanır (ara sonuçta dört kelime birden duyulunca):
                // "delegate bir bakar mısın, hava nasıl" tek nefeste söylenince sorunun başı kaçmasın.
                val tam = taniyici.acceptWaveForm(bytes, bytes.size)
                // Ham metinde uyanma adı yoksa JSON ayrıştırmaya gerek yok (uyanma cümlesi şart koşar).
                val ham = if (tam) taniyici.result else taniyici.partialResult
                if (!elleTetik && UYANMA_ADLARI.none { ham.contains(it) }) continue
                val duyulan = JSONObject(ham).optString(if (tam) "text" else "partial")
                val sesle = !elleTetik && uyanmaCumlesi(duyulan)
                if (!elleTetik && !sesle) continue

                val devam = devamDinle
                devamDinle = false
                elleTetik = false
                konusmaBitti = false
                iptal = false
                ajanDur = false
                Log.i(TAG, if (sesle) "Uyandı: $duyulan" else if (devam) "Soruya cevap dinleniyor" else "Uyandı (elle)")
                taniyici.reset()

                // Kayıt hiç durmadan sürer: bip/bekleme boşluğunda sorunun başı kaçıyordu. Bip yerine kısa
                // titreşim (bip kayda girip ilk kelimeyi bozuyordu). Uyanma parçası sunucuda ayıklanır.
                val yazi = bekleyenYazi  // panelden yazılı soru: dinleme yok
                bekleyenYazi = null
                val sesEki = bekleyenSesEki  // yazıdan sese dönüldü: bu metne devam dinlenecek
                bekleyenSesEki = null
                uyanmaKuyrugu = sesle
                if (yazi == null) {
                    titret(hafif = devam)
                    panel.dinliyor(devam)
                }
                if (yazi == null) sesYoneticisi.requestAudioFocus(sesOdagi)  // yazılıda müzik durmasın
                try {
                    oturum(rec, serbest, bytes, yazi, sesEki)
                } finally {
                    // Müzik komutları cevap okunduktan sonra: "duraklat" odak bırakılmadan (müzik
                    // kendiliğinden geri gelmesin), diğerleri bırakıldıktan sonra.
                    val medya = bekleyenMedya
                    bekleyenMedya = emptyList()
                    medya.filter { it == "duraklat" }.forEach { Eylem.medya(this@VekilService, it) }
                    sesYoneticisi.abandonAudioFocusRequest(sesOdagi)
                    medya.filter { it != "duraklat" }.forEach { Eylem.medya(this@VekilService, it) }
                }

                // Kendi cevabını duymasın: mikrofon tamponunu boşalt, tanıyıcıları sıfırla.
                serbest.reset()
                taniyici.reset()
                acikKalan = 0
                beslendi = false
                onceki = null
                hazirlik = GURULTU_PENCERE  // cevap sesinden sonra ortam sesini yeniden öğren
                rec.stop()
                rec.startRecording()
                bekliyor()
                // OpenDelegate soru sorduysa ("gönderelim mi?") cevap uyanma cümlesi beklenmeden dinlenir;
                // panel yazı modundaysa kullanıcı yazarak cevaplar.
                if (devamDinle && !panel.yaziModunda) elleTetik = true else devamDinle = false
            }
        } finally {
            rec.stop()
            rec.release()
            taniyici.close()
            serbest.close()
        }
    }

    private fun uyanmaCumlesi(metin: String): Boolean {
        // Üçü de duyulmalı: "delegate ... bakar" sık yanlış uyanıyordu, "mısın/misin" şart.
        if (UYANMA_ADLARI.none { metin.contains(it) } || !metin.contains("bakar")) return false
        return metin.contains("mısın") || metin.contains("misin")
    }

    @Suppress("DEPRECATION")  // VibratorManager API 31+; bu yol 26+ hepsinde çalışıyor
    private fun titret(hafif: Boolean) {
        val v = getSystemService(android.os.Vibrator::class.java) ?: return
        if (!v.hasVibrator()) return
        v.vibrate(android.os.VibrationEffect.createOneShot(
            if (hafif) 20L else 45L, android.os.VibrationEffect.DEFAULT_AMPLITUDE))
    }

    private fun bekliyor() {
        guncelle(Durum.BEKLIYOR)
        bildirimGuncelle("> 'delegate bir bakar mısın' de")
    }

    /**
     * Bir soru-cevap turu: sesli (mikrofon), yazılı (panelden) ya da adb denemesi.
     * Hata verse de panel ve durum tutarlı kalır.
     */
    private suspend fun oturum(rec: AudioRecord, serbest: Recognizer, onSes: ByteArray, yazi: String?, sesEki: String? = null) {
        if (sesEki != null) {
            // Server'a gitmez: yazılana eklenecek kısa parça için yerel (Vosk) metin yeter.
            val sonuc = komut_kaydet(rec, serbest, onSes, konusulmadiysaKapat = false)
            // iptal: X'e basıldı. yaziyaGecildi: tekrar klavyeye geçti; o an söyleneni panel kendisi yazmıştı.
            if (iptal || yaziyaGecildi) return
            panel.sesEkiSonucu(listOf(sesEki, sonuc?.second.orEmpty()).filter { it.isNotBlank() }.joinToString(" ").trim())
            return
        }
        val deneme = denemeSesi
        denemeSesi = null
        bekleyenIsler = emptyList()  // yarıda kalmış eski turun işi bu turda çalışmasın
        // Yazılı soruya cevap yazılı gelir, okunmaz (Gemini gibi: toplantıda yazınca telefon konuşmasın).
        val sessiz = yazi != null
        val cevap = when {
            yazi != null -> {
                panel.dusunuyor(yazi, kesin = true)
                val govde = JSONObject().put("metin", yazi).put("sessiz", true).toString().toByteArray()
                istek_at("sor", govde, "application/json")
            }
            deneme != null -> {
                guncelle(Durum.DINLIYOR)
                delay(600)  // panel açılsın
                panel.dusunuyor("")
                istek_at("dinle", deneme.first, deneme.second)
            }
            else -> {
                val (pcm, canli) = komut_kaydet(rec, serbest, onSes) ?: return
                if (iptal) return
                panel.dusunuyor(canli)
                istek_at("dinle", pcm_to_wav(pcm, ORNEKLEME), "audio/wav")
            }
        } ?: return
        if (iptal) return
        if (panelKapatIstendi) {
            // "kapat": panel kapanır; OpenDelegate soru sormuş olsa bile tekrar dinlemeye açılmaz (uyanma kelimesi bekler).
            panelKapatIstendi = false
            devamDinle = false
            panel.kapat()
            return
        }
        if (cevap.sorun != null) {
            // Telefondaki iş yapılamadı: "kurdum" diyen cevabı okuma, neyin olmadığını göster.
            panel.bosta(cevap.sorun)
            hataSesi()
            devamDinle = cevap.sorun.trimEnd().endsWith("?")  // "birden fazla kişi var, hangisi?"
            return
        }
        if (!sessiz && cevap.mp3.isNotEmpty()) mp3_oynat(cevap.mp3)
        if (iptal) return

        val isler = bekleyenIsler
        bekleyenIsler = emptyList()
        if (isler.isNotEmpty()) {
            val sonuc = ekranIsleriniYap(isler)
            if (iptal) return
            gecmise_ekle("(telefonda iş)", sonuc)
            panel.konusuyor("", sonuc)
            if (!sessiz) seslendir(sonuc)
            if (!iptal) panel.bosta()
            devamDinle = sonuc.trimEnd().endsWith("?")
            return
        }
        panel.bosta()
        devamDinle = cevap.metin.trimEnd().endsWith("?")
    }

    /** Cevap okunduktan sonra ekrandan yapılacak işler (WhatsApp mesajı, "ekranda" görevleri); sonuç cümlesi. */
    private suspend fun ekranIsleriniYap(isler: List<JSONObject>): String {
        guncelle(Durum.CALISIYOR)  // panelin durdur düğmesi bu işi durdursun
        val sonuclar = mutableListOf<String>()
        for (is_ in isler) {
            if (iptal || ajanDur) break
            kilidiAcBekle()?.let { return it }
            sonuclar += if (is_.optString("eylem") == "bildirim_oku") {
                BildirimDinleyici.ozet(this)
            } else if (is_.optString("eylem") == "mesaj") {
                guncelle(Durum.CALISIYOR)
                panel.calisiyor("WhatsApp'ta mesaj yazılıyor")
                Eylem.mesajGonder(this, is_.optString("kisi"), is_.optString("metin"))
            } else {
                ekranAjani(is_.optString("gorev"))
            }
        }
        return sonuclar.joinToString(" ").ifBlank { "Durdurdum efendim." }
    }

    /** Telefon kilitliyse kilidi açtırır (en çok 30 sn). Açıksa null, açılmadıysa söylenecek cümle. */
    private suspend fun kilidiAcBekle(): String? {
        val kilit = getSystemService(android.app.KeyguardManager::class.java)
        if (!kilit.isKeyguardLocked) return null
        panel.calisiyor("Devam etmem için kilidi aç")
        panel.kilidiAcIste()
        val acildi = withTimeoutOrNull(30_000L) {
            while (kilit.isKeyguardLocked) {
                if (iptal || ajanDur) return@withTimeoutOrNull false
                delay(300)
            }
            true
        } ?: false
        if (!acildi) return if (iptal || ajanDur) "Durdurdum efendim." else "Kilit açılmadığı için yapamadım efendim."
        panel.overlayaGec()  // kilit ekranındaki panel uygulamaların üstüne taşınır
        delay(600)
        return null
    }

    /**
     * OpenDelegate telefonu ekrandan kullanır: ekranı okur, sunucudaki model bir sonraki 1-3 eylemi seçer
     * (tıkla, yaz, kaydır...), erişilebilirlik servisi yapar; iş bitene kadar. Sonuç cümlesi döner.
     */
    private suspend fun ekranAjani(gorev: String): String {
        val erisim = VekilErisim.aktif
            ?: return "Telefonu kullanmam için izin gerekli efendim: OpenDelegate uygulamasındaki TELEFONU KULLANMA düğmesine bas."
        guncelle(Durum.CALISIYOR)
        bildirimGuncelle("> TELEFONDA CALISIYOR...")
        panel.calisiyor("Başlıyorum")
        val yapilanlar = mutableListOf<String>()
        for (adim in 0 until AJAN_MAKS_ADIM) {
            if (iptal || ajanDur) return "Durdurdum efendim."
            delay(if (adim == 0) 300L else 900L)  // önceki eylemden sonra ekran otursun
            val ekran = withContext(Dispatchers.Main) { erisim.ekranMetni() }
            val cevap = ajanIstegi(gorev, ekran, yapilanlar, adim)
                ?: return if (iptal || ajanDur) "Durdurdum efendim." else "Sunucuya ulaşamadım efendim, iş yarıda kaldı."
            if (cevap.optBoolean("bitti")) return cevap.optString("sonuc").ifBlank { "Bitti efendim." }
            cevap.optString("dusunce").takeIf { it.isNotBlank() }?.let { panel.calisiyor(it) }
            val eylemler = cevap.optJSONArray("eylemler") ?: JSONArray()
            for (i in 0 until eylemler.length()) {
                if (iptal || ajanDur) return "Durdurdum efendim."
                val e = eylemler.optJSONObject(i) ?: continue
                val ne = withContext(Dispatchers.Main) { erisim.yap(e, this@VekilService) }
                Log.i(TAG, "Ekranda: $ne")
                yapilanlar += "${adim + 1}. adım: $ne"
                delay(350)
            }
        }
        return "Çok uzun sürdü efendim, yarıda bıraktım."
    }

    /**
     * Sunucudaki bekleyen işleri UZUN YOKLAMAYLA sorar (sunucu en çok TELEFON_UZUN_YOKLAMA_SN bekletir,
     * iş gelince hemen döner): sohbetteki OpenDelegate'in telefona verdiği işler (alarm, fener, ekranda iş...).
     * Sadece boştayken alır: efendimle konuşurken araya girmez.
     */
    private suspend fun telefonGoreviDongusu() {
        while (true) {
            if (durum != Durum.BEKLIYOR) { delay(2_000L); continue }
            val bas = android.os.SystemClock.elapsedRealtime()
            val is_ = telefonGoreviSor()
            if (is_ == null) { delay(TELEFON_GOREV_HATA_BEKLE_MS); continue }  // ağ/sunucu hatası
            val id = is_.optString("id")
            val eylem = is_.optJSONObject("eylem")
            if (id.isNotBlank() && eylem != null) { sohbetIsi(id, eylem); continue }
            // Uzun yoklamayı bilmeyen eski sunucu hemen boş döner: o zaman seyrek sor (döngü dönmesin).
            if (android.os.SystemClock.elapsedRealtime() - bas < 3_000L) delay(TELEFON_GOREV_ARALIK_MS)
        }
    }

    /** Sohbetteki OpenDelegate'in telefona verdiği iş: yapar, sonucu sunucuya yollar (sohbette efendime o yazar). */
    private suspend fun sohbetIsi(id: String, eylem: JSONObject) {
        while (durum != Durum.BEKLIYOR) delay(500L)  // tam o an konuşma başladıysa bitsin
        val tur = eylem.optString("eylem")
        Log.i(TAG, "Sohbetten telefon işi: $tur")
        iptal = false
        ajanDur = false
        val panelli = tur in setOf("ekranda", "mesaj", "uygulama_ac")  // kilit açma ve durdur düğmesi panelde
        guncelle(Durum.CALISIYOR)
        bildirimGuncelle("> TELEFONDA CALISIYOR...")
        if (panelli) panel.calisiyorAc("Sohbetten gelen iş")
        val sonuc = try {
            when (tur) {
                "ekranda" -> kilidiAcBekle() ?: ekranAjani(eylem.optString("gorev"))
                "mesaj" -> kilidiAcBekle() ?: Eylem.mesajGonder(this, eylem.optString("kisi"), eylem.optString("metin"))
                "bildirim_oku" -> BildirimDinleyici.ozet(this)
                "medya" -> { Eylem.medya(this, eylem.optString("komut")); "Yaptım efendim." }
                else -> {
                    val json = JSONArray().put(eylem).toString()
                    val kilitSorun = if (Eylem.uygulamaAcilacak(json)) kilidiAcBekle() else null
                    kilitSorun ?: Eylem.yap(applicationContext, json) ?: "Yaptım efendim."
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Sohbet işi hatası: $e")
            "Telefonda bunu yaparken bir hata oldu efendim."
        }
        sonucGonder(id, sonuc)
        if (panelli) panel.bosta(sonuc)
        bekliyor()
    }

    /** Sonuç kaybolursa sohbetteki OpenDelegate 5 dk boşuna bekler: ağ bir anlık koptuysa bir kez daha dener. */
    private suspend fun sonucGonder(id: String, sonuc: String) {
        val ctx = applicationContext
        val govde = JSONObject().put("id", id).put("sonuc", sonuc.take(3000))
        val istek = Request.Builder().url("${Config.renderUrl(ctx)}/telefon/sonuc/${Config.sesliToken(ctx)}")
            .post(govde.toString().toRequestBody("application/json".toMediaType()))
            .build()
        for (deneme in 1..2) {
            try {
                http.newCall(istek).execute().use { y -> if (y.isSuccessful) return }
            } catch (e: Exception) {
                Log.e(TAG, "Telefon işinin sonucu gönderilemedi ($deneme/2): $e")
            }
            if (deneme == 1) delay(2_000L)
        }
    }

    /** Bekleyen iş: {"id", "eylem": {...}}; yoksa {}. Hata: null. */
    private fun telefonGoreviSor(): JSONObject? {
        val ctx = applicationContext
        if (!Config.tamam(ctx)) return null
        val istek = Request.Builder()
            .url("${Config.renderUrl(ctx)}/telefon/gorev/${Config.sesliToken(ctx)}?bekle=$TELEFON_UZUN_YOKLAMA_SN")
            .header("X-Vekil-Surum", SURUM.toString())
            .build()
        return try {
            http.newCall(istek).execute().use { y ->
                if (!y.isSuccessful) null else JSONObject(y.body?.string().orEmpty())
            }
        } catch (e: Exception) {
            Log.e(TAG, "Telefon görevi sorgu hatası: $e")
            null
        }
    }

    private fun ajanIstegi(gorev: String, ekran: String, yapilanlar: List<String>, adim: Int): JSONObject? {
        val ctx = applicationContext
        val govde = JSONObject()
            .put("gorev", gorev).put("ekran", ekran).put("adim", adim)
            .put("gecmis", JSONArray(yapilanlar.takeLast(15)))
        val istek = Request.Builder().url("${Config.renderUrl(ctx)}/telefon/${Config.sesliToken(ctx)}")
            .post(govde.toString().toRequestBody("application/json".toMediaType()))
            .build()
        val cagri = http.newCall(istek)
        aktifCagri = cagri
        return try {
            cagri.execute().use { y ->
                if (!y.isSuccessful) {
                    Log.e(TAG, "Ekran işi sunucu hatası: ${y.code}")
                    null
                } else {
                    JSONObject(y.body?.string().orEmpty())
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Ekran işi istek hatası: $e")
            null
        } finally {
            aktifCagri = null
        }
    }

    /** Ekrandan yapılan işin sonucunu OpenDelegate'in sesiyle söyler; ses gelmezse yazı panelde kalır. */
    private suspend fun seslendir(metin: String) {
        val ctx = applicationContext
        val istek = Request.Builder().url("${Config.renderUrl(ctx)}/seslendir/${Config.sesliToken(ctx)}")
            .post(JSONObject().put("metin", metin).toString().toRequestBody("application/json".toMediaType()))
            .build()
        val mp3 = try {
            http.newCall(istek).execute().use { y -> if (y.isSuccessful) y.body?.bytes() else null }
        } catch (e: Exception) {
            Log.e(TAG, "Seslendirme hatası: $e")
            null
        }
        if (mp3 != null && mp3.isNotEmpty() && !iptal) mp3_oynat(mp3)
    }

    private suspend fun hataSesi() {
        val ton = ToneGenerator(AudioManager.STREAM_MUSIC, 70)
        ton.startTone(ToneGenerator.TONE_PROP_NACK, 250)
        delay(350)
        ton.release()
    }

    /**
     * Konuşmayı kaydeder; konuşulmadıysa, iptal edildiyse ya da yazmaya geçildiyse null.
     * [onSes]: uyanma anındaki parça; sorunun başı da olabilir (kayda girer, "konuştu" sayılmaz).
     */
    private suspend fun komut_kaydet(
        rec: AudioRecord, serbest: Recognizer, onSes: ByteArray, konusulmadiysaKapat: Boolean = true
    ): Pair<ByteArray, String>? {
        guncelle(Durum.DINLIYOR)
        bildirimGuncelle("> DINLIYORUM...")

        val pcm = ByteArrayOutputStream()
        var konustu = false

        // Canlı yazı: biten cümleler + o an söylenen kısım.
        val biten = StringBuilder()
        var anlik = ""
        // true dönerse: "delegate ... bakar mısın" yeniden duyuldu, kullanıcı yarıda kesip yeniden başladı.
        fun canli(bytes: ByteArray): Boolean {
            var yeniden = false
            anlik = if (serbest.acceptWaveForm(bytes, bytes.size)) {
                val t = JSONObject(serbest.result).optString("text")
                if (t.isNotBlank()) {
                    if (uyanmaCumlesi(t)) yeniden = true
                    biten.append(t).append(' ')
                }
                ""
            } else {
                JSONObject(serbest.partialResult).optString("partial").also {
                    if (uyanmaCumlesi(it)) yeniden = true
                }
            }
            panel.canliYazi((biten.toString() + anlik).trim())
            return yeniden
        }
        yaziyaGecildi = false
        pcm.write(onSes)
        canli(onSes)

        val buf = ShortArray(PARCA)
        val baslangic = System.currentTimeMillis()
        var sonSesZamani = baslangic
        // Sessiz odada 300; gürültülü yerde ortamın 2.5 katı (en çok 1500): konuşma yine aşar, gürültü aşmaz.
        val esik = (gurultu.min() * 5 / 2).coerceIn(SESSIZLIK_ESIK, SESSIZLIK_TAVAN)

        while (System.currentTimeMillis() - baslangic < MAKS_KAYIT_MS) {
            if (iptal || konusmaBitti || yaziyaGecildi || !calisiyor) break
            val n = rec.read(buf, 0, PARCA)
            if (n <= 0) continue

            val rms = rmsHesapla(buf, n)
            panel.seviye(rms)
            sonSeviye = rms

            val bytes = bayta_cevir(buf, n)
            val simdi = System.currentTimeMillis()
            val yenidenUyandi = canli(bytes)
            if (konustu && yenidenUyandi) {
                // Baştan: öncekini at, bu andan itibaren yeniden dinle.
                pcm.reset()
                biten.clear()
                konustu = false
                sonSesZamani = simdi
            }
            pcm.write(bytes)

            // Sesle uyanınca ilk anlar uyanma cümlesinin kuyruğu ("...mısın"): konuşma sayılmaz. Sayılınca
            // Kullanıcı soruya başlamadan susma süresi doluyor, sadece "mısın" gidip "anlayamadım" dönüyordu.
            if (rms > esik && (!uyanmaKuyrugu || simdi - baslangic > KUYRUK_MS)) {
                sonSesZamani = simdi
                konustu = true
            }
            if (konustu && simdi - sonSesZamani > SESSIZLIK_SURE_MS) break
            if (!konustu && simdi - baslangic > ILK_SES_BEKLEME_MS) break
        }

        if (iptal || yaziyaGecildi) return null  // yazıya geçildiyse panel açık kalır, kullanıcı yazar
        val pcmBytes = pcm.toByteArray()
        Log.i(TAG, "Kayıt bitti: ${pcmBytes.size} bayt, konuştu=$konustu, eşik=$esik")

        // Hiç konuşulmadı: Gemini gibi sessizce kapan.
        if (!konustu || pcmBytes.size < ORNEKLEME / 2) {
            if (konusulmadiysaKapat) panel.kapat()
            return null
        }
        return pcmBytes to (biten.toString() + anlik).trim()
    }

    /**
     * Sunucuya gönderir (yol: "dinle" ses, "sor" yazı); cevabı panele yazar, telefondaki işleri
     * (alarm, fener...) yapar, ekrandan yapılacakları sıraya koyar. Hata panelde gösterilir, null döner.
     */
    private suspend fun istek_at(yol: String, govde: ByteArray, tur: String): Cevap? {
        guncelle(Durum.ISLIYOR)
        bildirimGuncelle("> DUSUNUYORUM...")

        val ctx = applicationContext
        if (!Config.tamam(ctx)) {
            panel.bosta("Bağlantı ayarları girilmemiş. Uygulamadan AYARLAR'a gir.")
            return null
        }

        val url = "${Config.renderUrl(ctx)}/$yol/${Config.sesliToken(ctx)}"
        val istek = Request.Builder().url(url)
            .header("X-Vekil-Surum", SURUM.toString())
            .post(govde.toRequestBody(tur.toMediaType()))
            .build()
        val cagri = http.newCall(istek)
        aktifCagri = cagri

        try {
            cagri.execute().use { yanit ->
                if (iptal) return null
                if (!yanit.isSuccessful) {
                    Log.e(TAG, "Sunucu hatası: ${yanit.code}")
                    panel.bosta(when (yanit.code) {
                        422 -> "Anlayamadım, bir daha söyler misin?"
                        401 -> "Token yanlış. AYARLAR'dan kontrol et."
                        else -> "OpenDelegate şu an cevap veremedi (${yanit.code})."
                    })
                    return null
                }
                val soru = basligi_coz(yanit.header("X-Metin"))
                val cevap = basligi_coz(yanit.header("X-Cevap"))
                val eylemler = basligi_coz(yanit.header("X-Eylem"))
                val mp3 = yanit.body?.bytes()
                Log.i(TAG, "Soru: $soru | Cevap: $cevap | Eylem: $eylemler")
                panelKapatIstendi = eylemler.isNotEmpty() && Eylem.panelKapat(eylemler)
                if (panelKapatIstendi) return Cevap(ByteArray(0), null, "")  // "kapat": gösterme, okuma
                if (soru.isNotEmpty() || cevap.isNotEmpty()) gecmise_ekle(soru, cevap)
                panel.konusuyor(soru, cevap)
                // Cevap okunmadan yap: "alarmı kurdum" dendiğinde kurulmuş olsun.
                // Uygulama açmadan ÖNCE kilit PIN ile açılır; yoksa uygulama kilit ekranının arkasında kalır.
                val kilitSorun = if (Eylem.uygulamaAcilacak(eylemler)) kilidiAcBekle() else null
                val sorun = kilitSorun
                    ?: if (eylemler.isNotEmpty()) Eylem.yap(applicationContext, eylemler) else null
                if (sorun == null && eylemler.isNotEmpty()) {
                    bekleyenMedya = Eylem.medyaKomutlari(eylemler)
                    bekleyenIsler = Eylem.ekranIsleri(eylemler)
                }
                return Cevap(mp3 ?: ByteArray(0), sorun, cevap)  // yazılı soruda ses yok, boş gelir
            }
        } catch (e: Exception) {
            if (iptal) return null
            Log.e(TAG, "İstek hatası: $e")
            panel.bosta("İnternete ulaşamadım.")
            return null
        } finally {
            aktifCagri = null
        }
    }

    private fun rmsHesapla(buf: ShortArray, n: Int): Int {
        var toplam = 0.0
        for (i in 0 until n) toplam += buf[i].toLong() * buf[i].toLong()
        return Math.sqrt(toplam / n).toInt()
    }

    /** adb denemesi: uygulamanın kendi klasöründeki MP3/WAV, olduğu gibi gönderilir (dışarıdan yol kabul edilmez). */
    private fun denemeSesiOku(ad: String): Pair<ByteArray, String>? = try {
        val kok = filesDir.canonicalFile
        val dosya = java.io.File(kok, ad).canonicalFile
        require(dosya.parentFile == kok) { "deneme sesi uygulama klasöründe olmalı" }
        dosya.readBytes() to if (ad.endsWith(".mp3")) "audio/mpeg" else "audio/wav"
    } catch (e: Exception) {
        Log.e(TAG, "Deneme sesi okunamadı: $e")
        null
    }

    private fun basligi_coz(ham: String?): String =
        if (ham.isNullOrEmpty()) "" else java.net.URLDecoder.decode(ham, "UTF-8")

    private fun gecmise_ekle(soru: String, cevap: String) {
        scope.launch(Dispatchers.Main) {
            gecmis.add(soru to cevap)
            if (gecmis.size > 50) gecmis.removeAt(0)
            gecmisCallback?.invoke()
        }
    }

    /** Oynatma bitene ya da durdur/X'e basılana kadar bekler (mikrofon kendi sesini duymasın). */
    private suspend fun mp3_oynat(mp3: ByteArray) {
        guncelle(Durum.OYNATILIYOR)
        bildirimGuncelle("> OPENDELEGATE KONUSUYOR...")

        val gecici = java.io.File(cacheDir, "vekil_cevap.mp3")
        gecici.writeBytes(mp3)

        val bitti = CompletableDeferred<Unit>()
        withContext(Dispatchers.Main) {
            if (iptal) { bitti.complete(Unit); return@withContext }
            try {
                val p = MediaPlayer().apply {
                    setAudioAttributes(
                        AudioAttributes.Builder()
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .setUsage(AudioAttributes.USAGE_ASSISTANT)
                            .build()
                    )
                    setDataSource(gecici.absolutePath)
                    prepare()
                }
                oynatici = p
                oynatmaBitti = bitti
                p.setOnCompletionListener { sesiKes() }
                p.setOnErrorListener { _, _, _ -> sesiKes(); true }
                p.start()
            } catch (e: Exception) {
                Log.e(TAG, "Oynatma hatası: $e")
                sesiKes()
                bitti.complete(Unit)
            }
        }
        bitti.await()
        gecici.delete()
    }

    private fun pcm_to_wav(pcm: ByteArray, hz: Int): ByteArray {
        val dataSize = pcm.size
        val totalSize = dataSize + 44
        val out = ByteArrayOutputStream(totalSize)

        fun int32le(v: Int) {
            out.write(v and 0xFF); out.write(v shr 8 and 0xFF)
            out.write(v shr 16 and 0xFF); out.write(v shr 24 and 0xFF)
        }
        fun int16le(v: Int) { out.write(v and 0xFF); out.write(v shr 8 and 0xFF) }

        out.write("RIFF".toByteArray())
        int32le(totalSize - 8)
        out.write("WAVEfmt ".toByteArray())
        int32le(16); int16le(1); int16le(1)
        int32le(hz); int32le(hz * 2); int16le(2); int16le(16)
        out.write("data".toByteArray())
        int32le(dataSize)
        out.write(pcm)

        return out.toByteArray()
    }

    // ---------- Durum + bildirim ----------

    private fun guncelle(d: Durum) {
        durum = d
        scope.launch(Dispatchers.Main) { durumCallback?.invoke(d) }
    }

    private fun bildirimGuncelle(metin: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(BILDIRIM_ID, bildirimOlustur(metin))
    }

    private fun servisIntenti(istekKodu: Int, eylem: String): PendingIntent =
        PendingIntent.getService(
            this, istekKodu,
            Intent(this, VekilService::class.java).setAction(eylem),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

    private fun bildirimOlustur(metin: String): Notification {
        val ac = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        val konus = Notification.Action.Builder(
            Icon.createWithResource(this, R.drawable.ic_mic), "Konuş", servisIntenti(1, ACTION_DINLE)
        ).build()
        val kapat = Notification.Action.Builder(
            Icon.createWithResource(this, R.drawable.ic_kapat), "OpenDelegate'i kapat", servisIntenti(2, ACTION_KAPAT)
        ).build()
        return Notification.Builder(this, KANAL_ID)
            .setContentTitle("OpenDelegate")
            .setContentText(metin)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentIntent(ac)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(konus)
            .addAction(kapat)
            .build()
    }

    private fun kanalOlustur() {
        // Android hep açık dinleme için bildirimi şart koşuyor; en düşük önemde üst çubukta simge çıkmaz,
        // bildirim perdesinin en altında küçük durur (Kullanıcı: "üstte bildirim ikonu durmasın").
        // Önem sonradan değiştirilemediği için yeni kanal; eski (simgeli) kanal silinir.
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.deleteNotificationChannel("vekil_dinleme")
        val kanal = NotificationChannel(
            KANAL_ID,
            getString(R.string.channel_name),
            NotificationManager.IMPORTANCE_MIN
        ).apply {
            description = "OpenDelegate arka planda dinliyor"
            setShowBadge(false)
        }
        nm.createNotificationChannel(kanal)
    }
}
