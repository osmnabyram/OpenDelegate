package com.vekilai.vekil

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Vekil'in telefonu ekrandan kullanması (Kullanıcı 21.11: "her şeye erişsin"): ekranı okur, öğelere dokunur,
 * yazar, kaydırır. Ayarlar > Erişilebilirlik'ten bir kez açılır. Şifre alanlarının içeriği okunmaz.
 * Ekran metni ve eylemler ana thread'de çağrılır.
 */
class VekilErisim : AccessibilityService() {

    private var ogeler: List<AccessibilityNodeInfo> = emptyList()

    override fun onServiceConnected() {
        aktif = this
    }

    override fun onUnbind(intent: Intent?): Boolean {
        if (aktif === this) aktif = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        if (aktif === this) aktif = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    /** Ekranı modelin okuyacağı numaralı metne çevirir; numaralar sonraki eylemlerde kullanılır. */
    fun ekranMetni(): String {
        val kok = rootInActiveWindow ?: return "(ekran okunamadı)"
        val liste = mutableListOf<AccessibilityNodeInfo>()
        val sb = StringBuilder("Uygulama: ").append(uygulamaAdi(kok.packageName?.toString())).append('\n')
        gez(kok, 0, liste, sb)
        ogeler = liste
        if (liste.isEmpty()) sb.append("(ekranda okunabilir öğe yok)\n")
        return sb.toString().take(MAKS_EKRAN)
    }

    private fun gez(d: AccessibilityNodeInfo, derinlik: Int, liste: MutableList<AccessibilityNodeInfo>, sb: StringBuilder) {
        if (liste.size >= MAKS_OGE || !d.isVisibleToUser) return
        val yazi = yaziOf(d)
        val ilgili = d.isClickable || d.isLongClickable || d.isEditable || d.isScrollable || d.isCheckable ||
            yazi.isNotEmpty()
        var alt = derinlik
        if (ilgili) {
            sb.append("  ".repeat(derinlik.coerceAtMost(6))).append('[').append(liste.size).append("] ").append(tur(d))
            if (yazi.isNotEmpty()) sb.append(" \"").append(yazi).append('"')
            val oz = ozellikler(d)
            if (oz.isNotEmpty()) sb.append(" (").append(oz).append(')')
            sb.append('\n')
            liste += d
            alt = derinlik + 1
        }
        for (i in 0 until d.childCount) d.getChild(i)?.let { gez(it, alt, liste, sb) }
    }

    private fun yaziOf(d: AccessibilityNodeInfo): String {
        if (d.isPassword) return if (d.text.isNullOrEmpty()) "şifre alanı" else "şifre alanı (dolu)"
        val parca = mutableListOf<String>()
        d.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let { parca += it }
        d.contentDescription?.toString()?.trim()?.takeIf { it.isNotEmpty() && it !in parca }?.let { parca += it }
        if (parca.isEmpty() && d.isEditable) {
            d.hintText?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let { parca += "ipucu: $it" }
        }
        return parca.joinToString(" / ").replace('\n', ' ').take(120)
    }

    private fun tur(d: AccessibilityNodeInfo): String =
        d.className?.toString()?.substringAfterLast('.')?.ifBlank { null } ?: "Öğe"

    private fun ozellikler(d: AccessibilityNodeInfo): String = buildList {
        if (d.isClickable) add("tıklanır")
        if (d.isLongClickable) add("uzun basılır")
        if (d.isEditable) add("yazılır")
        if (d.isScrollable) add("kaydırılır")
        if (d.isCheckable) add(if (d.isChecked) "açık" else "kapalı")
        if (d.isSelected) add("seçili")
        if (!d.isEnabled) add("pasif")
    }.joinToString(", ")

    private fun uygulamaAdi(paket: String?): String {
        if (paket.isNullOrEmpty()) return "?"
        return try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(paket, 0)).toString()
        } catch (_: Exception) {
            paket
        }
    }

    // ---------- Eylemler ----------

    /** Tek eylemi yapar; ne olduğunu kısa yazar (modelin "yapılanlar" listesi için). */
    suspend fun yap(e: JSONObject, ctx: Context): String = when (e.optString("tur")) {
        "tikla" -> oge(e)?.let { tikla(it, uzun = false) } ?: "öğe ${e.optInt("no")} ekranda yok"
        "uzun_bas" -> oge(e)?.let { tikla(it, uzun = true) } ?: "öğe ${e.optInt("no")} ekranda yok"
        "yaz" -> oge(e)?.let { yaz(it, e.optString("metin")) } ?: "öğe ${e.optInt("no")} ekranda yok"
        "kaydir" -> kaydir(oge(e), e.optString("yon", "asagi"))
        "geri" -> { performGlobalAction(GLOBAL_ACTION_BACK); "geri tuşu" }
        "ana_ekran" -> { performGlobalAction(GLOBAL_ACTION_HOME); "ana ekran" }
        "uygulama_ac" -> e.optString("uygulama").let { ad -> Eylem.uygulamaAc(ctx, ad) ?: "$ad açıldı" }
        "bekle" -> { delay(1500); "beklendi" }
        else -> "bilinmeyen eylem"
    }

    /** Yan tuşa basmak gibi: ekranı kapatıp kilitler (telefon kapanmaz). Olduysa null, olmadıysa söylenecek cümle. */
    fun ekraniKilitle(): String? =
        if (performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)) null else "Ekranı kilitleyemedim efendim."

    private fun oge(e: JSONObject): AccessibilityNodeInfo? =
        if (e.has("no")) ogeler.getOrNull(e.optInt("no", -1)) else null

    private fun etiket(d: AccessibilityNodeInfo): String =
        "[${ogeler.indexOf(d)}] " + yaziOf(d).ifEmpty { tur(d) }.take(40)

    private suspend fun tikla(d: AccessibilityNodeInfo, uzun: Boolean): String {
        val islem = if (uzun) AccessibilityNodeInfo.ACTION_LONG_CLICK else AccessibilityNodeInfo.ACTION_CLICK
        val ne = if (uzun) "uzun basıldı" else "tıklandı"
        var n: AccessibilityNodeInfo? = d
        while (n != null) {  // yazının kendisi değil, satırı/düğmesi tıklanır olabilir
            if ((if (uzun) n.isLongClickable else n.isClickable) && n.performAction(islem)) return "${etiket(d)} $ne"
            n = n.parent
        }
        val r = Rect().also { d.getBoundsInScreen(it) }
        if (r.isEmpty) return "${etiket(d)} görünmüyor"
        val oldu = hareket(Path().apply { moveTo(r.exactCenterX(), r.exactCenterY()) }, if (uzun) 700L else 60L)
        return if (oldu) "${etiket(d)} $ne (dokunarak)" else "${etiket(d)} dokunulamadı"
    }

    private fun yaz(d: AccessibilityNodeInfo, metin: String): String {
        val alan = if (d.isEditable) d else duzenlenirBul(d) ?: return "${etiket(d)} yazılabilir bir alan değil"
        if (alan.isPassword) return "Şifre alanına yazmam, bunu siz yapın"  // güvenlik: model ele geçirilse bile
        alan.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val arg = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, metin)
        }
        return if (alan.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arg)) {
            "${etiket(d)} alanına \"${metin.take(40)}\" yazıldı"
        } else {
            "${etiket(d)} alanına yazılamadı"
        }
    }

    private fun duzenlenirBul(d: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val kuyruk = ArrayDeque(listOf(d))
        while (kuyruk.isNotEmpty()) {
            val n = kuyruk.removeFirst()
            if (n.isEditable) return n
            for (i in 0 until n.childCount) n.getChild(i)?.let { kuyruk.addLast(it) }
        }
        return null
    }

    private suspend fun kaydir(d: AccessibilityNodeInfo?, yon: String): String {
        val ileri = yon == "asagi" || yon == "saga"
        var n: AccessibilityNodeInfo? = d ?: kaydirilirBul(rootInActiveWindow)
        while (n != null && !n.isScrollable) n = n.parent
        val islem = if (ileri) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        if (n != null && n.performAction(islem)) return "kaydırıldı ($yon)"
        // Kaydırılır öğe bulunamadı: parmakla kaydır.
        val dm = resources.displayMetrics
        val w = dm.widthPixels.toFloat()
        val h = dm.heightPixels.toFloat()
        val yol = Path().apply {
            when (yon) {
                "yukari" -> { moveTo(w / 2, h * 0.3f); lineTo(w / 2, h * 0.7f) }
                "saga" -> { moveTo(w * 0.8f, h / 2); lineTo(w * 0.2f, h / 2) }
                "sola" -> { moveTo(w * 0.2f, h / 2); lineTo(w * 0.8f, h / 2) }
                else -> { moveTo(w / 2, h * 0.7f); lineTo(w / 2, h * 0.3f) }
            }
        }
        return if (hareket(yol, 350)) "parmakla kaydırıldı ($yon)" else "kaydırılamadı"
    }

    private fun kaydirilirBul(kok: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        val kuyruk = ArrayDeque(listOfNotNull(kok))
        while (kuyruk.isNotEmpty()) {
            val n = kuyruk.removeFirst()
            if (n.isScrollable && n.isVisibleToUser) return n
            for (i in 0 until n.childCount) n.getChild(i)?.let { kuyruk.addLast(it) }
        }
        return null
    }

    /** Ekrana parmak hareketi; panel o an dokunmayı geçirir ki altında kalan yere de dokunulabilsin. */
    private suspend fun hareket(yol: Path, sure: Long): Boolean {
        val bitti = CompletableDeferred<Boolean>()
        val hareket = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(yol, 0, sure)).build()
        Panel.aktif?.dokunmaGecir(true)
        try {
            delay(80)
            val basladi = dispatchGesture(hareket, object : GestureResultCallback() {
                override fun onCompleted(g: GestureDescription?) { bitti.complete(true) }
                override fun onCancelled(g: GestureDescription?) { bitti.complete(false) }
            }, null)
            return basladi && withTimeoutOrNull(sure + 2_000) { bitti.await() } == true
        } finally {
            Panel.aktif?.dokunmaGecir(false)
        }
    }

    /**
     * Kilit ekranındaki PIN tuş takımına kayıtlı PIN'i girer (Samsung/AOSP: systemui key0..key9).
     * Tuş takımı ~4 sn içinde çıkmazsa ya da bir tuş bulunamazsa false (kullanıcı kendi açar). Tek deneme.
     */
    suspend fun pinGir(pin: String): Boolean {
        fun tus(c: Char) = rootInActiveWindow?.findAccessibilityNodeInfosByViewId("$SYSTEMUI:id/key$c")?.firstOrNull()
        var hazir = false
        for (i in 0 until 14) { if (tus('0') != null) { hazir = true; break }; delay(300) }
        if (!hazir) return false
        delay(250)  // tuş takımı animasyonu otursun
        for (c in pin) {
            val t = tus(c) ?: return false
            if (!t.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return false
            delay(120)
        }
        delay(300)
        // 4 haneli PIN'de Samsung kendiliğinden açar; açmadıysa OK'a bas.
        rootInActiveWindow?.findAccessibilityNodeInfosByViewId("$SYSTEMUI:id/key_enter_text")?.firstOrNull()
            ?.let { tikla(it, uzun = false) }
        return true
    }

    /** WhatsApp sohbetinde mesaj yazılı halde açıkken Gönder'e basar. Bulamazsa false. */
    fun whatsappGonder(): Boolean {
        val kok = rootInActiveWindow ?: return false
        val kimlikle = WHATSAPP.flatMap { kok.findAccessibilityNodeInfosByViewId("$it:id/send") }
        // Yazıyla ararken sadece adı tam "Gönder"/"Send" olan düğme: mesajın içinde "gönder" geçse yazı alanı da
        // bulunur, ona basmak "gönderdim" yanılgısı olurdu.
        val yaziyla = (kok.findAccessibilityNodeInfosByText("Gönder") + kok.findAccessibilityNodeInfosByText("Send"))
            .filter { n ->
                !n.isEditable && n.contentDescription?.toString()?.trim()?.lowercase() in setOf("gönder", "send")
            }
        return (kimlikle + yaziyla).any {
            it.isVisibleToUser && it.isEnabled && it.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        }
    }

    /** Gönder'den sonra yazı alanı boşaldıysa mesaj gitmiştir. Alan bulunamazsa (sohbet kapandı) true. */
    fun whatsappGirisBos(): Boolean {
        val kok = rootInActiveWindow ?: return true
        val alan = WHATSAPP.flatMap { kok.findAccessibilityNodeInfosByViewId("$it:id/entry") }.firstOrNull()
            ?: return true
        val yazi = alan.text?.toString().orEmpty()
        return yazi.isBlank() || yazi == alan.hintText?.toString()
    }

    companion object {
        private const val SYSTEMUI = "com.android.systemui"
        private const val MAKS_OGE = 250
        private const val MAKS_EKRAN = 12_000
        val WHATSAPP = listOf("com.whatsapp", "com.whatsapp.w4b")

        /** Erişilebilirlikten açıkken servisin kendisi; kapalıyken null. */
        @Volatile var aktif: VekilErisim? = null
            private set
    }
}
