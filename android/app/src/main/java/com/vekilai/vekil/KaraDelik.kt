package com.vekilai.vekil

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * Ana ekrandaki "bilinç": kara delik. Ortada olay ufku (siyah), çevresinde ışığı bükülmüş kızıl halka ve
 * yörüngede dönen kızıl-siyah toz. Beklerken yavaşça döner ve nefes alır. Dokununca ve Vekil çalışırken
 * toz çok az hızlanır, kara delik biraz daha göze batar (dalga, titreme yok).
 * Sadece ekranda görünürken çizer (pil).
 */
class KaraDelik @JvmOverloads constructor(
    ctx: Context, attrs: AttributeSet? = null
) : View(ctx, attrs) {

    private class Parca(val yaricap: Float, var aci: Float, val hiz: Float, val boy: Float, val parlak: Float)

    private val dp = resources.displayMetrics.density
    private val rnd = Random(7)
    private val parcalar = List(150) {
        val r = 0.34f + rnd.nextFloat().pow(1.6f) * 0.66f  // içe yığılır: iç yörünge daha kalabalık
        Parca(r, rnd.nextFloat() * 2f * PI.toFloat(), 0.22f / sqrt(r * r * r), 0.8f + rnd.nextFloat() * 1.6f,
            0.35f + rnd.nextFloat() * 0.65f)
    }

    private val boya = Paint(Paint.ANTI_ALIAS_FLAG)
    private val cizgi = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeCap = Paint.Cap.ROUND }
    private var hale: RadialGradient? = null
    // Tüm görünüm Vekil'in o anki durumundan türer ve yumuşak geçişle değişir (pat diye atlama yok).
    private var enerji = 0f   // 0 sakin .. 1 dinliyor/yanıtlıyor
    private var uyku = 0f     // 1: servis kapalı, sönük ve çok yavaş
    private var tetikBitis = 0L

    /** Dokunuşa tepki: kısa süre (1,5 sn) biraz hızlanıp belirginleşir, sonra kendiliğinden söner. */
    fun tetikle() { tetikBitis = SystemClock.uptimeMillis() + 1500L }

    private fun hedefEnerji(simdi: Long): Float {
        val durumdan = when (VekilService.durum) {
            VekilService.Durum.DINLIYOR -> 1f
            VekilService.Durum.OYNATILIYOR -> 0.85f
            VekilService.Durum.ISLIYOR, VekilService.Durum.CALISIYOR -> 0.6f
            else -> 0f
        }
        return maxOf(durumdan, if (simdi < tetikBitis) 0.7f else 0f)
    }

    private fun hedefUyku(): Float = when (VekilService.durum) {
        VekilService.Durum.KAPALI, VekilService.Durum.HATA -> 1f
        else -> 0f
    }
    private var sonZaman = 0L
    private var faz = 0f

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        val r = minOf(w, h) / 2f
        hale = RadialGradient(w / 2f, h / 2f, r,
            intArrayOf(Color.argb(150, 100, 106, 114), Color.argb(60, 70, 75, 82), Color.argb(0, 40, 42, 46)),
            floatArrayOf(0.30f, 0.62f, 1f), Shader.TileMode.CLAMP)
    }

    override fun onAttachedToWindow() { super.onAttachedToWindow(); sonZaman = 0L; postInvalidateOnAnimation() }

    override fun onVisibilityAggregated(gorunur: Boolean) {
        super.onVisibilityAggregated(gorunur)
        if (gorunur) { sonZaman = 0L; postInvalidateOnAnimation() }
    }

    override fun onDraw(canvas: Canvas) {
        val simdi = SystemClock.uptimeMillis()
        val dt = if (sonZaman == 0L) 0.016f else ((simdi - sonZaman) / 1000f).coerceAtMost(0.05f)
        sonZaman = simdi
        // Yumuşak geçiş: yaklaşık 0,7 sn'lik süzme (üstel yaklaşma).
        val k = (dt * 1.5f).coerceAtMost(1f)
        enerji += (hedefEnerji(simdi) - enerji) * k
        uyku += (hedefUyku() - uyku) * k
        val yogun = enerji
        val hizCarpani = (1f + enerji * 0.9f) * (1f - 0.6f * uyku)   // dinlerken ~%90 hızlı, kapalıyken yavaş
        faz += dt * 1.1f

        val cx = width / 2f
        val cy = height / 2f
        val r = minOf(width, height) / 2f
        val nefes = 1f + 0.025f * sin(faz)
        val ufuk = r * 0.30f * nefes          // olay ufku yarıçapı
        val egim = 0.36f                      // disk yana yatık: dikey sıkışma

        // Dış hale
        boya.shader = hale
        boya.alpha = ((150 + 105 * yogun) * (1f - 0.55f * uyku)).toInt().coerceIn(0, 255)
        canvas.drawCircle(cx, cy, r, boya)
        boya.shader = null
        boya.alpha = 255

        for (p in parcalar) p.aci += p.hiz * 1.6f * hizCarpani * dt  // 1.6: genel dönüş hızı

        // Arka yarı (diskin ufkun ardından geçen kısmı)
        parcaCiz(canvas, cx, cy, r, egim, nefes, arka = true)

        // Işık halkası: ufkun çevresinde bükülmüş ışık (glow = üst üste ince halkalar)
        boya.style = Paint.Style.STROKE
        val halka = ufuk * 1.16f
        for ((kalin, alfa) in listOf(10f to 22, 6f to 45, 3f to 90, 1.4f to 235)) {
            boya.strokeWidth = kalin * dp
            boya.color = Color.argb((alfa * (0.8f + 0.2f * yogun) * (1f - 0.5f * uyku)).toInt().coerceIn(0, 255), (150 + 60 * yogun).toInt(), (156 + 60 * yogun).toInt(), (166 + 60 * yogun).toInt())
            canvas.drawCircle(cx, cy, halka, boya)
        }
        boya.style = Paint.Style.FILL

        // Olay ufku
        boya.color = Color.BLACK
        canvas.drawCircle(cx, cy, ufuk, boya)

        // Ön yarı (disk ufkun önünden geçer)
        parcaCiz(canvas, cx, cy, r, egim, nefes, arka = false)

        postInvalidateOnAnimation()
    }

    private fun parcaCiz(canvas: Canvas, cx: Float, cy: Float, r: Float, egim: Float, nefes: Float, arka: Boolean) {
        for (p in parcalar) {
            val a = p.aci
            val onde = sin(a) > 0f
            if (onde == arka) continue
            val d = p.yaricap * r * nefes
            val x = cx + cos(a) * d
            val y = cy + sin(a) * d * egim
            // iz: bir önceki konuma kısa çizgi
            val geri = a - p.hiz * 0.35f * (1f + enerji * 0.5f)
            val x2 = cx + cos(geri) * d
            val y2 = cy + sin(geri) * d * egim
            val sicak = (1f - p.yaricap).coerceIn(0f, 1f)           // içeri doğru daha sıcak
            val onPlan = if (onde) 1f else 0.55f
            val alfa = (255 * p.parlak * onPlan * (0.55f + 0.45f * enerji) * (1f - 0.5f * uyku)).toInt().coerceIn(0, 255)
            cizgi.color = Color.argb(alfa, (110 + 100 * sicak).toInt(), (116 + 100 * sicak).toInt(), (126 + 100 * sicak).toInt())
            cizgi.strokeWidth = p.boy * dp
            canvas.drawLine(x2, y2, x, y, cizgi)
        }
    }
}
