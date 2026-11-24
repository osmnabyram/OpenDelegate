package com.vekilai.vekil

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Sadece adb'den deneme: konuşmadan bir tur başlatır (kilit ekranı, eylemler, panel uçtan uca denensin).
 *   adb shell am broadcast -a com.vekilai.vekil.DENEME -n com.vekilai.vekil/.DenemeAlici [--es wav deneme.wav]
 * wav verilirse mikrofon yerine uygulama klasöründeki o 16 kHz mono WAV gönderilir.
 * Manifest'te android.permission.DUMP ile korunur: o izin sadece kabukta ve sistemde var.
 */
class DenemeAlici : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        intent.getStringExtra("pin")?.let {  // adb'den PIN kaydı: --es pin XXXX
            if (it.length in 4..16 && it.all(Char::isDigit)) Config.pinKaydet(context, it)
            return
        }
        val servis = Intent(context, VekilService::class.java).setAction(VekilService.ACTION_DINLE)
        intent.getStringExtra("wav")?.let { servis.putExtra(VekilService.EXTRA_DENEME_WAV, it) }
        context.startService(servis)
    }
}
