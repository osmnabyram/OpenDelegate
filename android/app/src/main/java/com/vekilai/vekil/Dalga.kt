package com.vekilai.vekil

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.sin

/**
 * Paneldeki ses dalgası. DINLE: mikrofon seviyesine tepki verir.
 * DUSUN: soldan sağa akan sakin dalga. KONUS: nabız gibi atar. DUR: düz.
 */
class Dalga @JvmOverloads constructor(
    ctx: Context, attrs: AttributeSet? = null
) : View(ctx, attrs) {

    enum class Mod { DUR, DINLE, DUSUN, KONUS }

    var mod = Mod.DUR
        set(v) { field = v; postInvalidateOnAnimation() }

    private val dp = resources.displayMetrics.density
    private val cubuk = 7
    private val boy = FloatArray(cubuk) { 0.1f }
    private var ses = 0f
    private val boya = Paint(Paint.ANTI_ALIAS_FLAG)

    /** Mikrofon RMS değeri (0..~10000); logaritmik ölçek, konuşma sesi orta-üst banda düşer. */
    fun seviye(rms: Int) {
        val v = (ln(1.0 + rms) / ln(1.0 + 3500.0)).toFloat().coerceIn(0f, 1f)
        if (v > ses) ses = v
    }

    override fun onDraw(canvas: Canvas) {
        val t = SystemClock.uptimeMillis() / 1000f
        val genislik = 5.5f * dp
        val ara = (width - cubuk * genislik) / (cubuk + 1)
        val orta = height / 2f
        var hareket = false

        for (i in 0 until cubuk) {
            val merkezYakin = 1f - abs(i - (cubuk - 1) / 2f) / cubuk
            val hedef = when (mod) {
                Mod.DUR -> 0.1f
                Mod.DINLE -> 0.1f + 0.9f * ses * merkezYakin * (0.65f + 0.35f * sin(t * 9f + i * 1.7f))
                Mod.DUSUN -> 0.22f + 0.18f * sin(t * 4.5f - i * 0.8f)
                Mod.KONUS -> 0.2f + 0.55f * merkezYakin * abs(sin(t * 5.5f + i * 0.9f))
            }
            boy[i] += (hedef - boy[i]) * 0.3f
            if (abs(hedef - boy[i]) > 0.005f) hareket = true

            val h = (boy[i] * height).coerceAtLeast(genislik)
            val x = ara + i * (genislik + ara)
            boya.color = if (mod == Mod.DUR) 0xFF2A2C30.toInt() else 0xFF8A909A.toInt()
            boya.alpha = (140 + 115 * merkezYakin).toInt()
            canvas.drawRoundRect(x, orta - h / 2, x + genislik, orta + h / 2,
                genislik / 2, genislik / 2, boya)
        }
        ses *= 0.88f  // mikrofon güncellemeleri arasında yumuşakça düşsün

        if (isAttachedToWindow && (mod != Mod.DUR || hareket)) postInvalidateOnAnimation()
    }
}
