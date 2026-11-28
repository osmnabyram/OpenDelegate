package com.opendelegate.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.telecom.TelecomManager
import android.util.Log
import android.view.KeyEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer
import java.util.Locale

/**
 * OpenDelegate'in telefonda yaptığı işler. Sunucu ne yapılacağını X-Eylem başlığında
 * JSON listesi olarak söyler (arama.telefon_eylemi); burada uygulanır.
 * [yap] hemen yapılanları yapar ve yapılamayanların kısa açıklamasını döner (hepsi olduysa null).
 * Müzik komutları cevap okunduktan sonra yapılır ([medyaKomutlari], [medya]).
 */
object Eylem {
    private const val TAG = "VekilEylem"

    fun yap(ctx: Context, json: String): String? {
        val sorunlar = mutableListOf<String>()
        for (e in liste(json)) {
            val sorun = try { tek(ctx, e) } catch (ex: Exception) {
                Log.e(TAG, "Eylem hatası ($e): $ex")
                "Telefonda bunu yapamadım."
            }
            if (sorun != null) sorunlar += sorun
        }
        return sorunlar.distinct().joinToString(" ").ifBlank { null }
    }

    /** Uygulama açılacaksa true: açmadan ÖNCE telefonun kilidi açılmış olmalı (VekilService bekler). */
    fun uygulamaAcilacak(json: String): Boolean = liste(json).any { it.optString("eylem") == "uygulama_ac" }

    /** Sunucu "kapat" komutunu tanıdı: panel kapansın, soru sorulmuş olsa bile tekrar dinlenmesin. */
    fun panelKapat(json: String): Boolean = liste(json).any { it.optString("eylem") == "panel_kapat" }

    fun medyaKomutlari(json: String): List<String> =
        liste(json).filter { it.optString("eylem") == "medya" }.map { it.optString("komut") }

    /** Cevap okunduktan sonra ekrandan yapılacak işler: WhatsApp mesajı ve "ekranda" görevleri. */
    fun ekranIsleri(json: String): List<JSONObject> =
        liste(json).filter { it.optString("eylem") in setOf("mesaj", "ekranda", "bildirim_oku") }

    /**
     * WhatsApp'ta kişinin sohbetini mesaj yazılı açar ve Gönder'e basar (erişim izniyle).
     * Kullanıcıya söylenecek sonuç cümlesini döner.
     */
    suspend fun mesajGonder(ctx: Context, kisi: String, metin: String): String {
        val (numara, sorun) = kisiBul(ctx, kisi)
        if (numara == null) return sorun ?: "Rehberde \"$kisi\" bulunamadı efendim."
        val adres = Uri.parse("https://api.whatsapp.com/send?phone=${whatsappNumarasi(numara)}&text=${Uri.encode(metin)}")
        val acilis = VekilErisim.WHATSAPP.map { Intent(Intent.ACTION_VIEW, adres).setPackage(it) }
            .firstOrNull { it.resolveActivity(ctx.packageManager) != null }
            ?: return "Telefonda WhatsApp bulamadım efendim."
        ctx.startActivity(acilis.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        Panel.aktif?.kilidiAcIste()
        val erisim = VekilErisim.aktif
            ?: return "Mesajı WhatsApp'ta yazdım efendim; telefonu kullanma izni kapalı olduğu için Gönder'e sen bas."
        repeat(20) {  // sohbet açılana kadar en çok 10 sn
            delay(500)
            if (withContext(Dispatchers.Main) { erisim.whatsappGonder() }) {
                delay(800)
                return if (withContext(Dispatchers.Main) { erisim.whatsappGirisBos() }) "Mesajı gönderdim efendim."
                else "Gönder'e bastım ama mesaj yazı alanında duruyor efendim, bir bakar mısın?"
            }
        }
        return "WhatsApp'ta Gönder düğmesini bulamadım efendim; mesaj yazılı duruyor."
    }

    /** Rehberdeki numarayı WhatsApp'ın istediği ülke kodlu biçime çevirir (0555... -> 90555...). */
    fun whatsappNumarasi(ham: String): String {
        val r = ham.filter { it.isDigit() || it == '+' }
        return when {
            r.startsWith("+") -> r.drop(1)
            r.startsWith("00") -> r.drop(2)
            r.startsWith("0") -> "90" + r.drop(1)
            r.length == 10 -> "90$r"
            else -> r
        }
    }

    /** Çalan müziğe/videoya kumanda tuşu gönderir (Spotify, YouTube Music... hangisi çalıyorsa). */
    fun medya(ctx: Context, komut: String) {
        val tus = when (komut) {
            "oynat" -> KeyEvent.KEYCODE_MEDIA_PLAY
            "duraklat" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "sonraki" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "onceki" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            else -> return
        }
        val am = ctx.getSystemService(AudioManager::class.java)
        am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, tus))
        am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, tus))
    }

    private fun liste(json: String): List<JSONObject> = try {
        val dizi = JSONArray(json)
        (0 until dizi.length()).mapNotNull { dizi.optJSONObject(it) }
    } catch (e: Exception) {
        Log.e(TAG, "Eylem listesi bozuk: $e")
        emptyList()
    }

    private fun tek(ctx: Context, e: JSONObject): String? = when (e.optString("eylem")) {
        "alarm" -> baslat(ctx, Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_HOUR, e.optInt("saat"))
            .putExtra(AlarmClock.EXTRA_MINUTES, e.optInt("dakika"))
            .putExtra(AlarmClock.EXTRA_MESSAGE, e.optString("etiket").ifBlank { "OpenDelegate" })
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true), "Alarm kurulamadı.")
        "zamanlayici" -> baslat(ctx, Intent(AlarmClock.ACTION_SET_TIMER)
            .putExtra(AlarmClock.EXTRA_LENGTH, e.optInt("sure_sn"))
            .putExtra(AlarmClock.EXTRA_MESSAGE, e.optString("etiket").ifBlank { "OpenDelegate" })
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true), "Zamanlayıcı kurulamadı.")
        "uygulama_ac" -> uygulamaAc(ctx, e.optString("uygulama"))
        "fener" -> fener(ctx, e.optBoolean("acik", true))
        "ekran_kilitle" -> VekilErisim.aktif?.ekraniKilitle()
            ?: "Telefonu kullanma izni kapalı efendim, ekranı kilitleyemedim."
        "ara" -> ara(ctx, e.optString("kisi"))
        "ses" -> ses(ctx, e.optString("yon"))
        "medya", "mesaj", "ekranda", "bildirim_oku", "panel_kapat" -> null  // cevap okunduktan sonra (VekilService)
        else -> null     // yeni sunucu, eski uygulama: bilmediğini sessizce geç
    }

    private fun baslat(ctx: Context, intent: Intent, sorun: String): String? {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (intent.resolveActivity(ctx.packageManager) == null) return sorun
        ctx.startActivity(intent)
        return null
    }

    /** "whatsapp", "WhatsApp'ı" gibi adları karşılaştırılabilir yapar (Türkçe harfler sadeleşir). */
    fun sadelestir(ad: String): String {
        val kucuk = ad.lowercase(Locale("tr")).replace('ı', 'i')
        val asciiye = Normalizer.normalize(kucuk, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "")
        return asciiye.replace(Regex("[^a-z0-9]"), "")
    }

    /**
     * Ada en iyi uyanlar: önce birebir, yoksa baştan eşleşen, yoksa içinde geçen (en az 3 harf).
     * En iyi düzeydeki tüm adayların sırası döner; boşsa uyan yok.
     */
    fun uyanlar(hedef: String, adlar: List<String>): List<Int> {
        val h = sadelestir(hedef)
        if (h.isEmpty()) return emptyList()
        val s = adlar.map(::sadelestir)
        val birebir = s.indices.filter { s[it] == h }
        if (birebir.isNotEmpty() || h.length < 3) return birebir
        val bastan = s.indices.filter { s[it].length >= 3 && (s[it].startsWith(h) || h.startsWith(s[it])) }
        if (bastan.isNotEmpty()) return bastan
        return s.indices.filter { s[it].contains(h) }
    }

    /** Adı söylenen uygulamayı açar; açamazsa nedenini döner. */
    fun uygulamaAc(ctx: Context, ad: String): String? {
        val pm = ctx.packageManager
        val adaylar = pm.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0
        ).filter { it.activityInfo.packageName != ctx.packageName }
        val i = uyanlar(ad, adaylar.map { it.loadLabel(pm).toString() }).firstOrNull()
            ?: return "\"$ad\" adında bir uygulama bulamadım."
        val hedef = adaylar[i].activityInfo
        ctx.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            .setClassName(hedef.packageName, hedef.name)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
        Panel.aktif?.kilidiAcIste()  // telefon kilitliyse uygulama kilidin altında kalmasın
        return null
    }

    private fun fener(ctx: Context, acik: Boolean): String? {
        val cm = ctx.getSystemService(CameraManager::class.java)
        val id = cm.cameraIdList.firstOrNull {
            cm.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
        } ?: return "Bu telefonda fener bulamadım."
        cm.setTorchMode(id, acik)
        return null
    }

    /** Rehberde ada tek bir kişi uyuyorsa onu arar; birden fazlaysa ya da yoksa aramaz, söyler. */
    private fun ara(ctx: Context, kisi: String): String? {
        if (ctx.checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            return "Arama izni gerekli; OpenDelegate uygulamasını açıp izin ver."
        }
        val (numara, sorun) = kisiBul(ctx, kisi)
        if (numara == null) return sorun
        ctx.getSystemService(TelecomManager::class.java)
            .placeCall(Uri.fromParts("tel", numara, null), null)
        return null
    }

    /** Rehberde ada tek bir kişi uyuyorsa (numara, null); yoksa ya da birden fazlaysa (null, neden). */
    fun kisiBul(ctx: Context, kisi: String): Pair<String?, String?> {
        if (ctx.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return null to "Rehber izni gerekli; OpenDelegate uygulamasını açıp izin ver."
        }
        val kayitlar = mutableListOf<Pair<String, String>>()  // (ad, numara)
        ctx.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER),
            null, null, null
        )?.use { c ->
            while (c.moveToNext()) {
                val ad = c.getString(0).orEmpty()
                val numara = c.getString(1).orEmpty()
                if (ad.isNotBlank() && numara.isNotBlank()) kayitlar += ad to numara
            }
        }
        val adaylar = uyanlar(kisi, kayitlar.map { it.first })
        val adlar = adaylar.map { kayitlar[it].first }.distinct()
        if (adlar.isEmpty()) return null to "Rehberde \"$kisi\" adında kimse yok."
        if (adlar.size > 1) {
            return null to "Rehberde birden fazla kişi var: ${adlar.take(3).joinToString(", ")}. Hangisi?"
        }
        return kayitlar[adaylar.first()].second to null
    }

    private fun ses(ctx: Context, yon: String): String? {
        val am = ctx.getSystemService(AudioManager::class.java)
        val akis = AudioManager.STREAM_MUSIC
        when (yon) {
            "ac" -> repeat(3) { am.adjustStreamVolume(akis, AudioManager.ADJUST_RAISE, 0) }
            "kis" -> repeat(3) { am.adjustStreamVolume(akis, AudioManager.ADJUST_LOWER, 0) }
            "sessiz" -> am.adjustStreamVolume(akis, AudioManager.ADJUST_MUTE, 0)
            else -> return null
        }
        am.adjustStreamVolume(akis, AudioManager.ADJUST_SAME, AudioManager.FLAG_SHOW_UI)  // yeni seviyeyi göster
        return null
    }
}
