package com.opendelegate.app

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.widget.FrameLayout

/**
 * Ekran kapalı ya da kilitliyken paneli gösteren şeffaf ekran: ekranı yakar, kilit ekranının
 * üstünde açılır (Gemini gibi, kilidi açmadan). Paneli kendisi çizmez; [Panel] içine yerleşir.
 * Panel kapanınca bu ekran da kapanır; geri tuşu X gibidir.
 */
class KilitEkrani : Activity() {

    lateinit var kap: FrameLayout
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)  // panel açıkken ekran sönmesin

        kap = FrameLayout(this).apply {
            setBackgroundColor(getColor(R.color.perde))
            setOnClickListener { Panel.aktif?.disariDokunuldu() }
        }
        setContentView(kap)

        val panel = Panel.aktif
        if (panel == null) finish() else panel.ekranaYerles(this)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        Panel.aktif?.ekranaYerles(this) ?: finish()
    }

    @Deprecated("Android 13+ geri hareketi de buraya düşer")
    override fun onBackPressed() {
        val panel = Panel.aktif
        if (panel == null) finish() else panel.kullaniciKapatti()
    }

    override fun onDestroy() {
        Panel.aktif?.ekrandanAyrildi(this)
        super.onDestroy()
    }
}
