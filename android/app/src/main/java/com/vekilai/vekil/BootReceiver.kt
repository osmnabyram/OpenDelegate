package com.vekilai.vekil

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/** Telefon açılınca Vekil'i geri başlatır. */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!Config.tamam(context) || Config.kapatildi(context)) return

        try {
            context.startForegroundService(Intent(context, VekilService::class.java))
        } catch (e: Exception) {
            // Android 14+ mikrofonlu servisi arka plandan başlatmayı reddedebilir;
            // o zaman kullanıcı uygulamayı bir kez açınca servis kalkar.
            Log.w("VekilBoot", "Acilista baslatilamadi: $e")
        }
    }
}
