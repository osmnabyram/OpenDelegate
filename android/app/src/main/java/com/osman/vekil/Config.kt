package com.osman.vekil

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object Config {
    private const val PREFS = "vekil_config"
    private const val KEY_URL = "render_url"
    private const val KEY_TOKEN = "sesli_token"
    private const val KEY_TOKEN_SIFRELI = "sesli_token_enc"
    private const val TOKEN_ANAHTAR = "vekil_token"
    private const val KEY_PIN = "kilit_pin"
    private const val KEY_KAPALI = "kullanici_kapatti"
    private const val PIN_ANAHTAR = "vekil_pin"

    // Token URL yolunda gider: sadece https (açık metin ağda token sızdırır).
    fun renderUrl(ctx: Context): String =
        (prefs(ctx).getString(KEY_URL, "") ?: "").takeIf { it.startsWith("https://") } ?: ""

    // Token Keystore ile şifreli tutulur (PIN gibi). Eski düz kayıt ilk okunuşta şifrelenip silinir; Keystore
    // çalışmazsa düz kayıt bozulmaz, uygulama eskisi gibi çalışır.
    // Bellekte önbellek: her istekte Keystore çözmesi olmasın (hız).
    @Volatile private var tokenOnbellek: String? = null

    fun sesliToken(ctx: Context): String {
        tokenOnbellek?.let { return it }
        val p = prefs(ctx)
        sifreliOku(p.getString(KEY_TOKEN_SIFRELI, null))?.let { tokenOnbellek = it; return it }
        val duz = p.getString(KEY_TOKEN, "") ?: ""
        if (duz.isNotEmpty() && tokenSifrele(ctx, duz)) p.edit().remove(KEY_TOKEN).apply()
        if (duz.isNotEmpty()) tokenOnbellek = duz
        return duz
    }

    private fun tokenSifrele(ctx: Context, token: String): Boolean = try {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, anahtar(TOKEN_ANAHTAR)) }
        val veri = c.iv + c.doFinal(token.toByteArray())
        prefs(ctx).edit().putString(KEY_TOKEN_SIFRELI, Base64.encodeToString(veri, Base64.NO_WRAP)).apply()
        sifreliOku(prefs(ctx).getString(KEY_TOKEN_SIFRELI, null)) == token  // geri okunamıyorsa düz kaydı silme
    } catch (_: Exception) {
        false
    }

    private fun sifreliOku(kayit: String?): String? {
        if (kayit == null) return null
        return try {
            val veri = Base64.decode(kayit, Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
                .apply { init(Cipher.DECRYPT_MODE, anahtar(TOKEN_ANAHTAR), GCMParameterSpec(128, veri, 0, 12)) }
            String(c.doFinal(veri, 12, veri.size - 12))
        } catch (_: Exception) {
            null
        }
    }

    /** https olmayan adres kaydedilmez; false döner. */
    fun kaydet(ctx: Context, url: String, token: String): Boolean {
        val temiz = url.trim().trimEnd('/')
        if (!temiz.startsWith("https://")) return false
        prefs(ctx).edit()
            .putString(KEY_URL, temiz)
            .putString(KEY_TOKEN, token.trim())
            .remove(KEY_TOKEN_SIFRELI)
            .apply()
        tokenOnbellek = null
        sesliToken(ctx)  // hemen şifrele, düz kaydı sil
        return true
    }

    // Telefonun kilit PIN'i (Kullanıcı 22.11: kilitliyken Vekil açabilsin). Sadece cihazda, Android Keystore ile
    // şifreli; sunucuya, loga ya da koda ASLA gitmez.
    fun pinKaydet(ctx: Context, pin: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, pinAnahtari()) }
        val veri = c.iv + c.doFinal(pin.toByteArray())
        prefs(ctx).edit().putString(KEY_PIN, Base64.encodeToString(veri, Base64.NO_WRAP)).apply()
    }

    fun pin(ctx: Context): String? {
        val kayit = prefs(ctx).getString(KEY_PIN, null) ?: return null
        return try {
            val veri = Base64.decode(kayit, Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
                .apply { init(Cipher.DECRYPT_MODE, pinAnahtari(), GCMParameterSpec(128, veri, 0, 12)) }
            String(c.doFinal(veri, 12, veri.size - 12))
        } catch (_: Exception) {
            null  // anahtar kayboldu ya da bozuk: PIN yokmuş gibi, kullanıcı kendi açar
        }
    }

    private fun pinAnahtari(): SecretKey = anahtar(PIN_ANAHTAR)

    private fun anahtar(ad: String): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ad, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance("AES", "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ad, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    // Kullanıcı anahtarla kapattıysa uygulama açılışında ve telefon açılışında Vekil kendiliğinden kalkmaz.
    fun kapatildi(ctx: Context) = prefs(ctx).getBoolean(KEY_KAPALI, false)
    fun kapatildiYaz(ctx: Context, kapali: Boolean) = prefs(ctx).edit().putBoolean(KEY_KAPALI, kapali).apply()

    fun tamam(ctx: Context) = renderUrl(ctx).isNotEmpty() && sesliToken(ctx).isNotEmpty()

    private fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
