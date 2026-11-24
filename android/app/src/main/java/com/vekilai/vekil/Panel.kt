package com.vekilai.vekil

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.animation.ValueAnimator
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.animation.AccelerateInterpolator
import android.view.animation.DecelerateInterpolator
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.TextView

/**
 * Gemini tarzı alt panel: hangi uygulama açık olursa olsun alttan kayarak açılır.
 * Ekran kapalı ya da kilitliyken ekranı yakar ve kilit ekranının üstünde açılır ([KilitEkrani]).
 *
 * Sesli ya da yazılı: klavye düğmesiyle yazı moduna geçilir (Gemini gibi). Mikrofon düğmesi duruma göre:
 * dinlerken "durdur ve gönder", Vekil konuşurken "sesi kes", telefonda iş yaparken "durdur", iş bitince
 * "tekrar konuş"; yazı modunda "gönder". X her şeyi iptal edip kapatır. Kararı servis verir.
 *
 * Herkese açık metotlar her thread'den çağrılabilir; iş ana thread'de yürür. Panelin hali
 * (durum, yazılar) alanlarda tutulur: kilit ekranı geç açılsa da kaldığı yerden çizer.
 * Kilitsiz ekranda "diğer uygulamaların üzerinde göster" izni yoksa panel açılmaz, akış sürer.
 */
class Panel(
    private val ctx: Context,
    private val mic: () -> Unit,
    private val kapatildi: () -> Unit,
    private val yaziyaGec: () -> Unit,
    private val yaziGonder: (String) -> Unit,
    private val sesEkle: (String) -> Unit,
) {
    enum class Hal { DINLIYOR, DUSUNUYOR, KONUSUYOR, CALISIYOR, BOSTA }

    private val ana = Handler(Looper.getMainLooper())
    private val wm = ctx.getSystemService(WindowManager::class.java)
    private val kilit = ctx.getSystemService(KeyguardManager::class.java)
    private val guc = ctx.getSystemService(PowerManager::class.java)
    private val dp = ctx.resources.displayMetrics.density

    private var kok: View? = null            // panel görünümü: overlay'de ya da kilit ekranında
    private var ekran: KilitEkrani? = null   // panel kilit ekranındaysa o ekran, overlay'deyse null
    private var pencere: WindowManager.LayoutParams? = null  // overlay penceresinin ayarları
    private var ekranBekleniyor = false      // kilit ekranı açılıyor; gelince yerleşecek
    private var acikOlmali = false           // servis paneli açık istiyor mu
    private var kapaniyor = false

    // Çizilecek hal: görünüm yokken de güncel kalır.
    private var hal = Hal.BOSTA
    private var soruYazi = ""
    private var soruKesin = false            // soru Whisper'dan/yazıdan mı (kesin) yoksa canlı tahmin mi
    private var cevapYazi = ""
    private var cizilenDurum = ""

    /** Yazı modunda mı (servis ses thread'inden okur: soruya cevabı sesle dinlemesin). */
    @Volatile var yaziModunda = false
        private set

    private var nabiz: ObjectAnimator? = null

    private val otomatikKapat = Runnable { kullaniciKapatti() }
    private val ekranGelmedi = Runnable {
        if (ekranBekleniyor) {
            ekranBekleniyor = false
            Log.w(TAG, "Kilit ekrani zamaninda acilmadi")
        }
    }

    init { aktif = this }

    /** [devam]: Vekil'in sorusuna cevap dinleniyor; soru panelde kalır. */
    fun dinliyor(devam: Boolean = false) = ana.post {
        soruYazi = ""
        soruKesin = false
        if (!devam) cevapYazi = ""
        hal = Hal.DINLIYOR
        if (!ac()) return@post
        halUygula()
    }

    fun canliYazi(metin: String) = ana.post {
        if (!acikOlmali || hal != Hal.DINLIYOR) return@post
        soruYazi = metin
        kok?.findViewById<TextView>(R.id.pSoru)?.text = metin
    }

    fun seviye(rms: Int) = ana.post {
        val v = kok ?: return@post
        if (hal != Hal.DINLIYOR) return@post
        v.findViewById<Dalga>(R.id.pDalga).seviye(rms)
        v.findViewById<Isilti>(R.id.pKart).guc = 0.3f + 0.7f * (rms / 2500f).coerceAtMost(1f)
    }

    /** [kesin]: yazılı soru; canlı tahmin değil, olduğu gibi parlak gösterilir. */
    fun dusunuyor(metin: String, kesin: Boolean = false) = ana.post {
        if (!acikOlmali && !kesin) return@post
        if (kesin && !ac()) return@post  // yazılı soru panel kapalıyken de gelebilir
        if (metin.isNotBlank()) {
            soruYazi = metin
            soruKesin = kesin
        }
        if (kesin) cevapYazi = ""
        hal = Hal.DUSUNUYOR
        halUygula()
    }

    fun konusuyor(soruMetni: String, cevapMetni: String) = ana.post {
        if (!acikOlmali) return@post
        if (soruMetni.isNotBlank()) {
            soruYazi = soruMetni
            soruKesin = true  // Whisper'ın duyduğu: canlı tahminden doğru
        }
        cevapYazi = cevapMetni
        hal = Hal.KONUSUYOR
        halUygula()
    }

    /** Vekil telefonda ekrandan iş yapıyor; [adim] o an ne yaptığı. Mikrofon düğmesi "durdur" olur. */
    fun calisiyor(adim: String) = ana.post {
        if (!acikOlmali) return@post
        cevapYazi = adim
        hal = Hal.CALISIYOR
        halUygula()
    }

    /** İş bitti ya da hata: panel açık kalır, mikrofonla devam edilebilir, sonra kendi kapanır. */
    fun bosta(mesaj: String? = null) = ana.post {
        if (!acikOlmali) return@post
        if (mesaj != null) cevapYazi = mesaj
        hal = Hal.BOSTA
        halUygula()
    }

    /** Yazıdan sese geçişte dinlenen devam servisten geldi: yazıya ekleyip tekrar yazı moduna döner. */
    fun sesEkiSonucu(metin: String) = ana.post {
        val v = kok ?: return@post
        yaziModu(true)
        v.findViewById<EditText>(R.id.pYazi).apply {
            setText(metin)
            setSelection(text?.length ?: 0)
        }
    }

    fun kapat() = ana.post { kaldir() }

    /** Servis kapanıyor: paneli kaldır, kilit ekranını bırak. */
    fun birak() = ana.post {
        kaldir()
        if (aktif === this) aktif = null
    }

    /** Kilit ekranından bir uygulama açıldı: kilidi açmasını iste (uygulama kilit altında kalmasın). */
    fun kilidiAcIste() = ana.post {
        val e = ekran ?: return@post
        if (!kilit.isKeyguardLocked) return@post
        kilit.requestDismissKeyguard(e, null)
        // Kayıtlı PIN varsa tuş takımına kendisi girer (uygulama açma, ekran işleri: hepsi bu yoldan geçer).
        val pin = Config.pin(ctx)
        val erisim = VekilErisim.aktif
        if (pin != null && erisim != null && !pinGiriliyor) {
            pinGiriliyor = true
            CoroutineScope(Dispatchers.Main).launch {
                try { erisim.pinGir(pin) } finally { pinGiriliyor = false }
            }
        }
    }

    private var pinGiriliyor = false

    /** Kilit açıldı: panel kilit ekranından uygulamaların üstüne taşınır (Vekil ekranı kullanacak). */
    fun overlayaGec() = ana.post {
        val e = ekran ?: return@post
        val v = kok
        ekran = null
        kok = null
        kapaniyor = false
        if (v != null) (v.parent as? ViewGroup)?.removeView(v)
        e.finish()
        if (acikOlmali && ac()) halUygula()
    }

    /** Vekil ekrana parmakla dokunurken panel dokunmayı altındaki uygulamaya geçirir. */
    fun dokunmaGecir(gecir: Boolean) = ana.post {
        val v = kok ?: return@post
        val p = pencere ?: return@post
        if (ekran != null) return@post
        p.flags = if (gecir) p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            else p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
        try { wm.updateViewLayout(v, p) } catch (_: Exception) {}
    }

    // ---------- KilitEkrani buradan haber verir (ana thread) ----------

    fun ekranaYerles(e: KilitEkrani) {
        ana.removeCallbacks(ekranGelmedi)
        ekranBekleniyor = false
        if (ekran === e && kok != null) {
            ciz()
            return
        }
        if (!acikOlmali || kok != null) {  // bu arada iş bitti ya da panel başka yerde açık
            e.finish()
            return
        }
        val v = olustur(e, e.kap)
        e.kap.addView(v, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM))
        kok = v
        ekran = e
        kapaniyor = false
        cizilenDurum = ""
        ciz()
        acilisAnimasyonu(v)
    }

    /** Kilit ekranı kendiliğinden kapandı (geri tuşu, sistem...): X'e basılmış gibi. */
    fun ekrandanAyrildi(e: KilitEkrani) {
        if (ekran !== e) return
        ekran = null
        kok = null
        kapaniyor = false
        nabziDurdur()
        if (acikOlmali) {
            acikOlmali = false
            yaziModunda = false
            hal = Hal.BOSTA
            ana.removeCallbacks(otomatikKapat)
            kapatildi()
        }
    }

    /** Panelin dışına dokunuldu: X'e basmış gibi kapat (yanlış uyanmada da çalışsın). */
    fun disariDokunuldu() = kullaniciKapatti()

    fun kullaniciKapatti() {
        kaldir()
        kapatildi()
    }

    // ---------- Yazı modu ----------

    private fun yaziModu(ac: Boolean) {
        val v = kok ?: return
        if (yaziModunda == ac) return
        yaziModunda = ac
        val alan = v.findViewById<EditText>(R.id.pYazi)
        val dalga = v.findViewById<View>(R.id.pDalga)
        val imm = ctx.getSystemService(InputMethodManager::class.java)
        odaklanabilir(ac)
        if (ac) {
            yaziyaGec()
            // Sesle söylenen o ana kadar yazıya geçsin: baştan yazmak zorunda kalmasın.
            if (hal == Hal.DINLIYOR && soruYazi.isNotBlank()) alan.setText(soruYazi)
            if (hal == Hal.DINLIYOR) hal = Hal.BOSTA
            gecisAnimasyonu(cikan = dalga, giren = alan)
            alan.postDelayed({
                alan.requestFocus()
                alan.setSelection(alan.text?.length ?: 0)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    alan.windowInsetsController?.show(WindowInsets.Type.ime())
                } else {
                    imm.showSoftInput(alan, InputMethodManager.SHOW_IMPLICIT)
                }
            }, 150)
        } else {
            imm.hideSoftInputFromWindow(alan.windowToken, 0)
            alan.clearFocus()
            gecisAnimasyonu(cikan = alan, giren = dalga)
        }
        halUygula()
    }

    private fun yaziyiGonder() {
        val alan = kok?.findViewById<EditText>(R.id.pYazi) ?: return
        val metin = alan.text.toString().trim()
        if (metin.isEmpty()) return
        alan.setText("")
        soruYazi = metin
        soruKesin = true
        cevapYazi = ""
        hal = Hal.DUSUNUYOR
        halUygula()
        yaziGonder(metin)
    }

    /** Yazıdan sese dönüş: yazılan korunur, servise verilip devamı dinlenir (Gemini gibi). */
    private fun sesliyeGec() {
        val metin = kok?.findViewById<EditText>(R.id.pYazi)?.text?.toString().orEmpty()
        yaziModu(false)
        sesEkle(metin)
    }

    /** Yazı modunda klavye için overlay odak alabilmeli; sesli modda alttaki uygulamanın odağını çalmaz. */
    private fun odaklanabilir(evet: Boolean) {
        val v = kok ?: return
        val p = pencere ?: return
        if (ekran != null) return
        p.flags = if (evet) p.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
            else p.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        try { wm.updateViewLayout(v, p) } catch (_: Exception) {}
    }

    // ---------- Çizim ----------

    private fun halUygula() {
        ana.removeCallbacks(otomatikKapat)
        if (hal == Hal.BOSTA && acikOlmali && !yaziModunda) ana.postDelayed(otomatikKapat, BOSTA_KAPANMA_MS)
        ciz()
    }

    private fun ciz() {
        val v = kok ?: return
        val soru = v.findViewById<TextView>(R.id.pSoru)
        soru.text = soruYazi
        // Dinlerken akan yazı canlı tahmin (soluk); sunucunun duyduğu ya da yazılan kesin (parlak).
        soru.alpha = if (soruKesin || soruYazi.isEmpty()) 1f else 0.62f
        soru.hint = when {
            yaziModunda -> "Sor ya da bir iş ver"
            hal == Hal.DINLIYOR -> "Dinliyorum, konuşabilirsin"
            else -> ""
        }

        val cevap = v.findViewById<TextView>(R.id.pCevap)
        if (cevap.text.toString() != cevapYazi) {
            cevap.text = cevapYazi
            cevap.scrollTo(0, 0)
            if (cevapYazi.isNotBlank()) belirAnimasyonu(cevap)
        }
        cevap.visibility = if (cevapYazi.isBlank()) View.GONE else View.VISIBLE

        val (yazi, mod, parlaklik) = when (hal) {
            Hal.DINLIYOR -> Triple("DINLIYORUM", Dalga.Mod.DINLE, 0.45f)
            Hal.DUSUNUYOR -> Triple("DUSUNUYORUM", Dalga.Mod.DUSUN, 0.6f)
            Hal.KONUSUYOR -> Triple("VEKIL", Dalga.Mod.KONUS, 0.65f)
            Hal.CALISIYOR -> Triple("TELEFONDA CALISIYORUM", Dalga.Mod.DUSUN, 0.7f)
            Hal.BOSTA -> Triple(if (yaziModunda) "YAZ" else "VEKIL", Dalga.Mod.DUR, 0.25f)
        }
        val durum = v.findViewById<TextView>(R.id.pDurum)
        if (yazi != cizilenDurum) {
            cizilenDurum = yazi
            durum.text = yazi
            durum.alpha = 0f
            durum.animate().alpha(1f).setDuration(200).start()
        }
        v.findViewById<Dalga>(R.id.pDalga).mod = mod
        v.findViewById<Isilti>(R.id.pKart).guc = parlaklik

        // Mikrofon düğmesi: yazı modunda gönder; dinlerken/konuşurken/çalışırken durdur; boşta mikrofon.
        val micBtn = v.findViewById<View>(R.id.pMic)
        val micIkon = v.findViewById<ImageView>(R.id.pMicIkon)
        val durdur = hal == Hal.DINLIYOR || hal == Hal.KONUSUYOR || hal == Hal.CALISIYOR
        val gonder = yaziModunda && !durdur
        micIkon.setImageResource(when {
            gonder -> R.drawable.ic_gonder
            durdur -> R.drawable.ic_stop
            else -> R.drawable.ic_mic
        })
        micBtn.setBackgroundResource(if (hal == Hal.BOSTA && !gonder) R.drawable.mic_bos else R.drawable.mic_dolu)
        micBtn.isEnabled = hal != Hal.DUSUNUYOR
        micBtn.alpha = if (hal == Hal.DUSUNUYOR) 0.35f else 1f
        micBtn.contentDescription = when {
            gonder -> "Gönder"
            durdur -> "Durdur"
            else -> "Konuş"
        }
        v.findViewById<ImageView>(R.id.pKlavye).setImageResource(
            if (yaziModunda) R.drawable.ic_mic else R.drawable.ic_klavye)
        if (hal == Hal.DINLIYOR) nabziBaslat(micBtn) else nabziDurdur()
    }

    // ---------- Animasyonlar ----------

    /** Dinlerken mikrofon düğmesi hafifçe nefes alır: "şu an seni dinliyorum". */
    private fun nabziBaslat(hedef: View) {
        if (nabiz?.target === hedef && nabiz?.isRunning == true) return
        nabziDurdur()
        nabiz = ObjectAnimator.ofPropertyValuesHolder(
            hedef,
            PropertyValuesHolder.ofFloat(View.SCALE_X, 1f, 1.08f),
            PropertyValuesHolder.ofFloat(View.SCALE_Y, 1f, 1.08f)
        ).apply {
            duration = 650
            repeatCount = ValueAnimator.INFINITE
            repeatMode = ValueAnimator.REVERSE
            start()
        }
    }

    private fun nabziDurdur() {
        val n = nabiz ?: return
        nabiz = null
        n.cancel()
        (n.target as? View)?.let { it.scaleX = 1f; it.scaleY = 1f }
    }

    private fun belirAnimasyonu(v: View) {
        v.alpha = 0f
        v.translationY = 10 * dp
        v.animate().alpha(1f).translationY(0f).setDuration(260)
            .setInterpolator(DecelerateInterpolator()).start()
    }

    private fun gecisAnimasyonu(cikan: View, giren: View) {
        cikan.animate().alpha(0f).setDuration(120).withEndAction { cikan.visibility = View.GONE }.start()
        giren.alpha = 0f
        giren.visibility = View.VISIBLE
        giren.animate().alpha(1f).setDuration(180).start()
    }

    private fun acilisAnimasyonu(v: View) {
        if (v.translationY == 0f && v.alpha == 1f) v.translationY = 280 * dp
        if (v.alpha == 1f) v.alpha = 0f
        v.animate().translationY(0f).alpha(1f)
            .setDuration(340).setInterpolator(DecelerateInterpolator(2.2f))
            .start()
    }

    // ---------- Açma / kapama ----------

    private fun kilitliMi(): Boolean = kilit.isKeyguardLocked || !guc.isInteractive

    /** Paneli açar ya da açık tutar. Görünüm hazırsa ya da kilit ekranı yoldaysa true. */
    private fun ac(): Boolean {
        acikOlmali = true
        val mevcut = kok
        if (mevcut != null && ekran == null && kilitliMi()) {
            // Overlay kilit ekranının altında kaldı (konuşurken telefon kilitlendi): kilit ekranına taşı.
            mevcut.animate().cancel()
            try { wm.removeView(mevcut) } catch (_: Exception) {}
            kok = null
            kapaniyor = false
            yaziModunda = false
            nabziDurdur()
        } else if (mevcut != null) {
            if (kapaniyor) {  // kapanırken yeniden çağrıldı: animasyonu çevir, aynı görünümü kullan
                kapaniyor = false
                mevcut.animate().cancel()
                acilisAnimasyonu(mevcut)
            }
            return true
        }
        if (ekranBekleniyor) return true
        if (kilitliMi()) return kilitEkraniniAc()

        if (!Settings.canDrawOverlays(ctx)) {
            acikOlmali = false
            return false
        }
        val v = olustur(ctx, null)
        v.setOnTouchListener { _, e ->
            if (e.action == MotionEvent.ACTION_OUTSIDE) disariDokunuldu()
            false
        }
        val p = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.BOTTOM
            windowAnimations = 0  // kendi kayma animasyonumuz var
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }
        return try {
            wm.addView(v, p)
            kok = v
            pencere = p
            kapaniyor = false
            cizilenDurum = ""
            acilisAnimasyonu(v)
            true
        } catch (e: Exception) {
            Log.w(TAG, "Panel acilamadi: $e")
            acikOlmali = false
            false
        }
    }

    /** Ekranı yakıp kilit ekranının üstünde paneli açacak ekranı başlatır; ekran gelince panel yerleşir. */
    private fun kilitEkraniniAc(): Boolean {
        ekraniYak()
        return try {
            ctx.startActivity(Intent(ctx, KilitEkrani::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            ekranBekleniyor = true
            ana.postDelayed(ekranGelmedi, EKRAN_BEKLEME_MS)
            true
        } catch (e: Exception) {
            Log.w(TAG, "Kilit ekrani baslatilamadi: $e")
            acikOlmali = false
            false
        }
    }

    /** Ekran kapalıysa kısa süre yakar; kilit ekranı açılınca ekranı kendisi açık tutar. */
    @Suppress("DEPRECATION")  // servisten ekranı yakmanın yolu bu bayrak; KilitEkrani ayrıca setTurnScreenOn kullanır
    private fun ekraniYak() {
        if (guc.isInteractive) return
        try {
            guc.newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "vekil:panel"
            ).acquire(EKRAN_BEKLEME_MS)
        } catch (e: Exception) {
            Log.w(TAG, "Ekran yakilamadi: $e")
        }
    }

    private fun olustur(c: Context, ust: ViewGroup?): View {
        val v = LayoutInflater.from(c).inflate(R.layout.panel, ust, false)
        v.findViewById<TextView>(R.id.pCevap).setTextIsSelectable(true)
        v.findViewById<View>(R.id.pKapat).setOnClickListener { kullaniciKapatti() }
        v.findViewById<View>(R.id.pMic).setOnClickListener {
            if (yaziModunda && hal != Hal.KONUSUYOR && hal != Hal.CALISIYOR) yaziyiGonder() else mic()
        }
        v.findViewById<View>(R.id.pKlavye).setOnClickListener {
            if (yaziModunda) sesliyeGec() else yaziModu(true)
        }
        v.findViewById<EditText>(R.id.pYazi).apply {
            // Çok satıra kayar ama klavyenin tuşu "gönder" olur.
            setRawInputType(InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES)
            imeOptions = EditorInfo.IME_ACTION_SEND
            setHorizontallyScrolling(false)
            maxLines = 4
            setOnEditorActionListener { _, eylem, _ ->
                if (eylem == EditorInfo.IME_ACTION_SEND) { yaziyiGonder(); true } else false
            }
        }
        // Klavye açılınca panel klavyenin üstüne çıksın.
        val altBosluk = v.paddingBottom
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            v.setOnApplyWindowInsetsListener { gorunum, ic ->
                val klavye = ic.getInsets(WindowInsets.Type.ime()).bottom
                gorunum.setPadding(gorunum.paddingLeft, gorunum.paddingTop, gorunum.paddingRight, altBosluk + klavye)
                ic
            }
        }
        yaziModunda = false
        return v
    }

    private fun kaldir() {
        acikOlmali = false
        hal = Hal.BOSTA
        ana.removeCallbacks(otomatikKapat)
        nabziDurdur()
        val v = kok ?: return  // kilit ekranı yoldaysa gelince kendini kapatır (ekranaYerles)
        if (kapaniyor) return
        kapaniyor = true
        if (yaziModunda) {  // bir sonraki açılış sesli başlar
            ctx.getSystemService(InputMethodManager::class.java)
                .hideSoftInputFromWindow(v.windowToken, 0)
            odaklanabilir(false)
            yaziModunda = false
            v.findViewById<View>(R.id.pYazi).visibility = View.GONE
            v.findViewById<View>(R.id.pDalga).apply { visibility = View.VISIBLE; alpha = 1f }
        }
        v.animate().translationY(v.height + 40 * dp).alpha(0f)
            .setDuration(220).setInterpolator(AccelerateInterpolator(1.6f))
            .withEndAction {
                if (!kapaniyor) return@withEndAction  // bu arada yeniden açıldı
                kapaniyor = false
                kok = null
                pencere = null
                val e = ekran
                ekran = null
                if (e != null) {
                    (v.parent as? ViewGroup)?.removeView(v)
                    e.finish()
                } else {
                    try { wm.removeView(v) } catch (_: Exception) {}
                }
            }.start()
    }

    companion object {
        private const val TAG = "VekilPanel"
        private const val BOSTA_KAPANMA_MS = 12_000L
        private const val EKRAN_BEKLEME_MS = 4_000L

        /** Kilit ekranı, erişim servisi ve telefon eylemleri servisteki paneli buradan bulur. */
        @Volatile var aktif: Panel? = null
            private set
    }
}
