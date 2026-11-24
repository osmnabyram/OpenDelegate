package com.vekilai.vekil

import android.content.Context
import android.graphics.Canvas
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.SweepGradient
import android.util.AttributeSet
import android.widget.FrameLayout

/**
 * Panelin kartı: koyu dolgu + kenarında dönen kırmızı ışıltı (Gemini'nin
 * renkli kenar ışığının Vekil tonları). Işıltı padding alanına taşar;
 * çocuklar padding'in içinde kalır. [guc] 0..1: dinlerken sese göre parlar.
 */
class Isilti @JvmOverloads constructor(
    ctx: Context, attrs: AttributeSet? = null
) : FrameLayout(ctx, attrs) {

    var guc = 0.35f
        set(v) { field = v.coerceIn(0f, 1f) }

    private val dp = resources.displayMetrics.density
    private val yaricap = 26 * dp
    private val kart = RectF()
    private val matris = Matrix()
    private var aci = 0f
    private var parlaklik = 0.35f

    private val renkler = intArrayOf(
        0xFFFF2A1A.toInt(), 0xFF4A0000.toInt(), 0xFFCC1111.toInt(),
        0xFFFF6A3D.toInt(), 0xFF5A0000.toInt(), 0xFFFF2A1A.toInt()
    )
    private var supurme: SweepGradient? = null

    private val dolgu = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF0B0B0B.toInt() }
    private val kenar = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1.6f * dp
    }
    // Bulanıklaştırma filtresi yazılım çizimine düşürür; onun yerine
    // giderek genişleyen ve sönen birkaç çizgiyle ışıltı (donanım hızlandırmalı).
    private val hale = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }

    init {
        setWillNotDraw(false)
        clipToPadding = false
        clipChildren = false
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        kart.set(paddingLeft.toFloat(), paddingTop.toFloat(),
            (w - paddingRight).toFloat(), (h - paddingBottom).toFloat())
        supurme = SweepGradient(w / 2f, h / 2f, renkler, null)
    }

    override fun onDraw(canvas: Canvas) {
        val sg = supurme ?: return
        matris.setRotate(aci, width / 2f, height / 2f)
        sg.setLocalMatrix(matris)

        parlaklik += (guc - parlaklik) * 0.15f
        hale.shader = sg
        for (i in 4 downTo 1) {
            hale.strokeWidth = i * 3.2f * dp
            hale.alpha = ((26 + 34 * parlaklik) * (5 - i) / 4).toInt()
            canvas.drawRoundRect(kart, yaricap, yaricap, hale)
        }
        canvas.drawRoundRect(kart, yaricap, yaricap, dolgu)
        kenar.shader = sg
        kenar.alpha = (150 + 105 * parlaklik).toInt()
        canvas.drawRoundRect(kart, yaricap, yaricap, kenar)

        aci = (aci + 0.9f + 2.5f * parlaklik) % 360f
        if (isAttachedToWindow) postInvalidateOnAnimation()
    }
}
