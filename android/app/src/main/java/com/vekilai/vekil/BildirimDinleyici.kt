package com.vekilai.vekil

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Bildirimleri okur (Ayarlar > Bildirim erişimi'nden bir kez açılır). Sadece bellekte son 30 bildirimi
 * tutar, diske yazmaz; kullanıcı "bildirimlerime bak" deyince [ozet] sesli okunur.
 */
class BildirimDinleyici : NotificationListenerService() {

    override fun onListenerConnected() {
        super.onListenerConnected()
        // Servis yeniden bağlanınca durum çubuğundakiler kaybolmasın.
        runCatching { activeNotifications }.getOrNull()?.forEach(::ekle)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) = ekle(sbn)

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        synchronized(liste) { liste.removeAll { it.anahtar == sbn.key } }
    }

    private fun ekle(sbn: StatusBarNotification) {
        val n = sbn.notification
        if (sbn.packageName == packageName) return
        if (n.flags and (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT) != 0) return
        val ex = n.extras
        val baslik = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty().trim()
        val satirlar = satirlariCikar(ex).takeLast(10)
        if (baslik.isBlank() && satirlar.isEmpty()) return
        val uygulama = runCatching {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        }.getOrDefault(sbn.packageName)
        synchronized(liste) {
            liste.removeAll { it.anahtar == sbn.key }
            liste.add(Kayit(sbn.key, uygulama, baslik, satirlar, sbn.postTime))
            if (liste.size > 30) liste.removeAt(0)
        }
    }

    /** Sohbet bildiriminde (WhatsApp) tüm mesajlar, yoksa satır listesi, yoksa tek metin. */
    private fun satirlariCikar(ex: android.os.Bundle): List<String> {
        val mesajlar = ex.getParcelableArray(Notification.EXTRA_MESSAGES)
        if (mesajlar != null) {
            val liste = Notification.MessagingStyle.Message.getMessagesFromBundleArray(mesajlar).mapNotNull { m ->
                val metin = temizle(m.text) ?: return@mapNotNull null
                val kim = m.senderPerson?.name?.toString()?.trim().orEmpty()
                if (kim.isBlank()) metin else "$kim: $metin"
            }
            if (liste.isNotEmpty()) return liste
        }
        ex.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.mapNotNull { temizle(it) }
            ?.takeIf { it.isNotEmpty() }?.let { return it }
        return listOfNotNull(temizle(ex.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: ex.getCharSequence(Notification.EXTRA_TEXT)))
    }

    private fun temizle(t: CharSequence?): String? =
        t?.toString()?.replace(Regex("\\s+"), " ")?.trim()?.take(300)?.ifBlank { null }

    private class Kayit(val anahtar: String, val uygulama: String, val baslik: String, val satirlar: List<String>, val zaman: Long)

    companion object {
        private val liste = mutableListOf<Kayit>()

        fun izinVar(ctx: Context): Boolean =
            Settings.Secure.getString(ctx.contentResolver, "enabled_notification_listeners")
                ?.contains(ComponentName(ctx, BildirimDinleyici::class.java).flattenToString()) == true

        /** Okunacak metin: en yeni 8 bildirim, her biri kendi cümlesinde (uygulama, kişi, mesaj sayısı, mesajlar sırayla). */
        fun ozet(ctx: Context): String {
            if (!izinVar(ctx)) return "Bildirim erişimi kapalı efendim, ayarlardan açmanız gerekiyor."
            val son = synchronized(liste) { liste.takeLast(8).reversed() }
            if (son.isEmpty()) return "Bildiriminiz yok efendim."
            val giris = if (son.size == 1) "Bir bildiriminiz var efendim." else "${son.size} bildiriminiz var efendim."
            return giris + " " + son.joinToString(" ") { k ->
                val kim = listOf(k.uygulama, k.baslik).filter(String::isNotBlank).joinToString(", ")
                when (k.satirlar.size) {
                    0 -> "$kim."
                    1 -> "$kim. ${k.satirlar[0].sonaNokta()}"
                    else -> "$kim, ${k.satirlar.size} mesaj. " + k.satirlar.joinToString(" ") { it.sonaNokta() }
                }
            }
        }

        private fun String.sonaNokta() = if (last() in ".!?") this else "$this."
    }
}
