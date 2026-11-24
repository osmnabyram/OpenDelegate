"""zamanlayici.py + brifing.py testleri (ağ yok; sahte saat, sahte HTTP, sahte model).

Çalıştır: python -m unittest tests.test_brifing
"""

import asyncio
import json
import types
import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

import httpx

import brifing
import zamanlayici
from zamanlayici import TR


class Saat:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Depo:
    """ayarlar tablosunun bellekteki taklidi; okuma/yazma sayısını da tutar (Neon kotası)."""

    def __init__(self):
        self.veri, self.okuma, self.yazma = {}, 0, 0

    async def oku(self, k):
        self.okuma += 1
        return json.loads(json.dumps(self.veri[k])) if k in self.veri else None

    async def yaz(self, k, v):
        self.yazma += 1
        self.veri[k] = json.loads(json.dumps(v))


def z_kur(saat, depo, calistir, is_saati=time(9, 0)):
    z = zamanlayici.Zamanlayici(simdi=saat, oku=depo.oku, yaz=depo.yaz)
    z.ekle(zamanlayici.GunlukIs("brifing", saat=lambda: is_saati, calistir=calistir))
    return z


class ZamanlayiciTest(unittest.IsolatedAsyncioTestCase):
    async def test_saatinde_bir_kez_ertesi_gun_yine(self):
        saat, depo, sayac = Saat(datetime(2026, 11, 16, 8, 59, tzinfo=TR)), Depo(), []

        async def is_():
            sayac.append(saat.t)

        z = z_kur(saat, depo, is_)
        await z.tik()
        self.assertEqual(sayac, [])  # 08:59: henüz değil
        saat.t = datetime(2026, 11, 16, 9, 0, 10, tzinfo=TR)
        for _ in range(5):
            await z.tik()
        self.assertEqual(len(sayac), 1)  # aynı gün ikinci kez yok
        saat.t = datetime(2026, 11, 17, 9, 1, tzinfo=TR)
        await z.tik()
        self.assertEqual(len(sayac), 2)
        self.assertEqual((depo.okuma, depo.yazma), (1, 2))  # kota: açılışta 1 okuma, gönderim başına 1 yazma

    async def test_yeniden_baslamada_ayni_gun_tekrar_gitmez(self):
        saat, depo, sayac = Saat(datetime(2026, 11, 16, 9, 5, tzinfo=TR)), Depo(), []

        async def is_():
            sayac.append(1)

        await z_kur(saat, depo, is_).tik()
        saat.t += timedelta(hours=2)  # Render yeniden başladı
        await z_kur(saat, depo, is_).tik()
        self.assertEqual(len(sayac), 1)

    async def test_gec_uyaninca_telafi_ama_gece_degil(self):
        saat, depo, sayac = Saat(datetime(2026, 11, 16, 14, 30, tzinfo=TR)), Depo(), []

        async def is_():
            sayac.append(1)

        await z_kur(saat, depo, is_).tik()
        self.assertEqual(len(sayac), 1)  # 09:00'da uyuyordu, 14:30'da uyandı: gönderir
        saat2, depo2, sayac2 = Saat(datetime(2026, 11, 16, 23, 30, tzinfo=TR)), Depo(), []

        async def is2():
            sayac2.append(1)

        await z_kur(saat2, depo2, is2).tik()
        self.assertEqual(sayac2, [])  # 23:00 sonrası: o günün brifingi artık anlamsız

    async def test_hata_10dk_sonra_tekrar_en_fazla_3(self):
        saat, depo, deneme = Saat(datetime(2026, 11, 16, 9, 0, tzinfo=TR)), Depo(), []

        async def patlayan():
            deneme.append(saat.t)
            raise RuntimeError("telegram yok")

        z = z_kur(saat, depo, patlayan)
        await z.tik()
        saat.t += timedelta(minutes=5)
        await z.tik()
        self.assertEqual(len(deneme), 1)  # 10 dk dolmadan tekrar yok
        for _ in range(6):
            saat.t += timedelta(minutes=11)
            await z.tik()
        self.assertEqual(len(deneme), 3)  # günde en fazla 3
        self.assertNotIn(zamanlayici.DURUM_ANAHTARI, depo.veri)  # başarısız gün işaretlenmez


# --------------------------------------------------------------------------

# 16 Kasım 2026, 07-23 saatleri: sabah 7°C, öğleden sonra yağmur (kod 63), 20:00 10°C.
HAVA = {"hourly": {"time": [f"2026-11-16T{h:02d}:00" for h in range(7, 24)],
                   "temperature_2m": [7.2, 8.0, 8.5, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.4, 15.0, 14.0, 12.0,
                                      10.0, 9.0, 8.0],
                   "precipitation_probability": [10, 10, 20, 20, 30, 40, 55, 60, 70, 60, 50, 40, 30, 30, 20, 20, 10],
                   "weather_code": [1, 1, 2, 2, 3, 3, 61, 61, 63, 61, 3, 3, 2, 2, 1, 1, 0],
                   "wind_speed_10m": [14, 14, 12, 10, 8, 6, 5, 4, 3, 4, 6, 8, 10, 12, 14, 16, 18]},
        "daily": {"time": ["2026-11-16"], "temperature_2m_min": [7.2], "temperature_2m_max": [16.4],
                  "precipitation_probability_max": [70], "weather_code": [63]}}
# Sabah (07-08) sağanak yağmış, günün kalanı açık: brifing "bugün yağmurlu" DEMEMELİ.
HAVA_GECMIS_YAGMUR = {"hourly": {"time": [f"2026-11-16T{h:02d}:00" for h in range(7, 24)],
                                 "temperature_2m": [8.0] * 17,
                                 "precipitation_probability": [90, 90] + [5] * 15,
                                 "weather_code": [65, 65] + [1] * 15,
                                 "wind_speed_10m": [10.0] * 17}}
TAVILY = {"results": [
    {"title": "Chrome zero-day exploited in the wild", "url": "https://haber.example/chrome", "content": "Google patched"},
    {"title": "Big breach <script>", "url": "https://haber.example/breach", "content": "Millions of records"},
    {"title": "Prompt injection hits AI agents", "url": "https://haber.example/ai", "content": "LLM agents"},
    {"title": "Reklam", "url": "http://guvensiz.example", "content": "http olan atlanır"},
]}


YORUM = "Akşam yağmur var, tenise şemsiyeyle çık; 19:15 gibi hazırlan."


class SahteLLM:
    """Soruya göre cevap: 'günün notu' isteğine yorum, diğerine (siber) haber JSON'u."""

    def __init__(self, cevap, yorum=YORUM):
        self.cevap, self.yorum_cevap, self.istekler = cevap, yorum, []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.istekler.append(kw)
        yorum_mu = "günün notu" in kw["messages"][-1]["content"]
        icerik = self.yorum_cevap if yorum_mu else self.cevap
        if isinstance(icerik, Exception):
            raise icerik
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=icerik))])


LLM_CEVAP = json.dumps([
    {"i": 0, "baslik": "Chrome'da sömürülen sıfırıncı gün", "kisa": "Chrome acil güncelleme", "ozet": "Hemen güncelle."},
    {"i": 2, "baslik": "Yapay zekâ ajanlarına prompt injection", "kisa": "AI ajan açığı", "ozet": "Ajanlar risk altında."},
    {"i": 99, "baslik": "UYDURMA HABER", "kisa": "uydurma", "ozet": "listede yok"},
    {"i": 1, "baslik": "Büyük veri sızıntısı <b>", "kisa": "sızıntı", "ozet": "Milyonlarca kayıt."},
], ensure_ascii=False)


def kur(saat=None, plan=None, durum=None, hava=HAVA, konum=None, llm=None):
    istekler, gonderilen, depo = [], [], Depo()

    def isle(req: httpx.Request) -> httpx.Response:
        istekler.append(req)
        if req.url.host == "api.open-meteo.com":
            return httpx.Response(200, json=hava) if hava else httpx.Response(503)
        if req.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=konum or {"results": []})
        if req.url.host == "api.tavily.com":
            return httpx.Response(200, json=TAVILY)
        return httpx.Response(404)

    async def gonder(m):
        gonderilen.append(m)

    b = brifing.Brifing(
        gonder=gonder, plan_kaynagi=plan, durum_kaynagi=durum,
        istemci=lambda: httpx.AsyncClient(transport=httpx.MockTransport(isle)),
        llm=llm or SahteLLM(LLM_CEVAP), simdi=saat or Saat(datetime(2026, 11, 16, 9, 0, tzinfo=TR)),
        oku=depo.oku, yaz=depo.yaz,
        yapilacak_kaynagi=lambda g: ("", ["Bugün için not ettiğin iş yok."]),
    )
    return b, istekler, gonderilen, depo


def plan(gun):
    return "20:00 tenis", ["20:00-21:00 tenis: randevun alındı.", "Kort paketinde 2 hak kaldı."]


class Kategoriler(unittest.IsolatedAsyncioTestCase):
    async def test_varsayilan_ve_goster(self):
        b, *_ = kur()
        self.assertEqual(b.ayar["kategoriler"], ["hava", "yorum", "plan", "siber", "durum", "yapilacak"])
        self.assertEqual(b.saat(), time(9, 0))
        ok, m = await b.ayarla({"eylem": "goster"})
        self.assertIn("09:00", m)
        self.assertIn(brifing.config.SEHIR_AD, m)

    async def test_cikar_ekle_kalici(self):
        b, _, _, depo = kur()
        ok, m = await b.ayarla({"eylem": "cikar", "kategori": "hava"})
        self.assertTrue(ok)
        self.assertNotIn("hava", b.ayar["kategoriler"])
        self.assertIn("Kapalı: hava", m)
        await b.ayarla({"eylem": "ekle", "kategori": "hava"})
        self.assertEqual(b.ayar["kategoriler"], ["hava", "yorum", "plan", "siber", "durum", "yapilacak"])  # sıra sabit
        b2, *_ = kur()
        b2.oku = depo.oku
        await b.ayarla({"eylem": "cikar", "kategori": "siber"})
        await b2.yukle()  # yeniden başlama: ayar geri gelir
        self.assertNotIn("siber", b2.ayar["kategoriler"])

    async def test_olmayan_kategori_durust(self):
        b, *_ = kur()
        ok, m = await b.ayarla({"eylem": "ekle", "kategori": "doviz"})
        self.assertFalse(ok)
        self.assertIn("yok (henüz)", m)

    async def test_saat(self):
        b, *_ = kur()
        self.assertTrue((await b.ayarla({"eylem": "saat", "saat": "8.15"}))[0])
        self.assertEqual(b.saat(), time(8, 15))
        self.assertFalse((await b.ayarla({"eylem": "saat", "saat": "25:00"}))[0])
        self.assertFalse((await b.ayarla({"eylem": "saat", "saat": "sabah"}))[0])
        self.assertEqual(b.saat(), time(8, 15))


class Sehir(unittest.IsolatedAsyncioTestCase):
    async def test_sehir_degisince_hava_yeni_koordinattan(self):
        konum = {"results": [
            {"name": "Kadıköy", "admin1": "Afyonkarahisar", "country_code": "TR", "latitude": 38.1, "longitude": 30.1},
            {"name": "Kadıköy", "admin1": "İstanbul", "country_code": "TR", "latitude": 40.99, "longitude": 29.03},
        ]}
        b, istekler, _, _ = kur(konum=konum)
        ok, m = await b.ayarla({"eylem": "sehir", "sehir": "Kadıköy, İstanbul"})
        self.assertTrue(ok)
        self.assertEqual(b.ayar["sehir"]["ad"], "Kadıköy, İstanbul")  # Afyon'daki değil
        await b.hava()
        h = [r for r in istekler if r.url.host == "api.open-meteo.com"][-1]
        self.assertEqual((h.url.params["latitude"], h.url.params["longitude"]), ("40.99", "29.03"))

    async def test_bulunamayan_sehir(self):
        b, *_ = kur()
        with self.assertRaises(brifing.BrifingHatasi):
            await b.ayarla({"eylem": "sehir", "sehir": "Atlantis"})
        self.assertEqual(b.ayar["sehir"]["ad"], brifing.config.SEHIR_AD)  # eski ayar korunur


class Mesaj(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.anahtar = mock.patch.object(brifing.config, "TAVILY_API_KEY", "test-anahtari")
        self.anahtar.start()

    def tearDown(self):
        self.anahtar.stop()

    async def test_gecmis_yagmur_bugunu_kirletmez(self):
        """Sabah yağan yağmur öğleden sonra brifingde "bugün yağmurlu" olarak yazılmasın."""
        b, _, gonderilen, _ = kur(hava=HAVA_GECMIS_YAGMUR, plan=plan, durum=lambda: "ok")
        await b.gonder_simdi()
        m = gonderilen[0]
        self.assertIn("çoğunlukla açık", m)
        self.assertIn("Yağış ihtimali en çok %5", m)
        self.assertNotIn("Şemsiye al", m)
        self.assertNotIn("kuvvetli yağmurlu", m)

    async def test_tam_brifing(self):
        b, istekler, gonderilen, _ = kur(plan=plan, durum=lambda: "telefon köprüsü bağlı · PC kapalı")
        await b.gonder_simdi()
        self.assertEqual(len(gonderilen), 1)
        m = gonderilen[0]
        ilk = m.split("\n")[0]
        self.assertEqual(ilk, f"<b>Günaydın {brifing.config.KULLANICI_ADI}</b>")  # ilk satır birebir bu, başka hiçbir şey yok
        for ek in ("°C", "tenis", "Siber"):
            self.assertNotIn(ek, ilk)
        self.assertIn("16°C", m)  # bilgiler yine mesajın içinde
        self.assertIn("Chrome'da sömürülen sıfırıncı gün", m)
        self.assertIn("16 Kasım 2026, Pazartesi", m)
        self.assertIn("7-16°C, yağmurlu", m)
        self.assertIn("Şemsiye al", m)
        self.assertIn("<blockquote expandable>", m)
        self.assertNotIn("UYDURMA", m)  # listede olmayan haber numarası atlandı
        self.assertNotIn("<script>", m)
        self.assertIn("&lt;b&gt;", m)  # dış metin HTML olarak kaçışlandı
        self.assertIn("<b>⚙️ Vekil</b>: telefon köprüsü bağlı · PC kapalı", m)
        sira = [m.index(x) for x in ("Hava · ", "<b>💡 Günün notu</b>", "<b>📅 Bugün</b>",
                                     "<b>🛡 Siber güvenlik</b>", "<b>⚙️ Vekil</b>", "<b>✅ Yapılacaklar</b>")]
        self.assertEqual(sira, sorted(sira))  # Kullanıcının sırası: hava, not, siber, bugün, yapılacaklar, durum

    async def test_kategori_cikinca_bolum_ve_istek_yok(self):
        b, istekler, gonderilen, _ = kur(plan=plan, durum=lambda: "ok")
        await b.ayarla({"eylem": "cikar", "kategori": "hava"})
        await b.ayarla({"eylem": "cikar", "kategori": "siber"})
        await b.gonder_simdi()
        self.assertNotIn("Hava", gonderilen[0])
        self.assertEqual(istekler, [])  # hava/haber servisine hiç gidilmedi

    async def test_bolum_patlarsa_sessizce_atlanir(self):
        # 21 Kasım 2026: Kullanıcı brifingde "alınamadı" satırı istemiyor; bölüm bir kez daha denenir,
        # yine olmazsa mesajdan tamamen çıkar, diğer bölümler normal gelir.
        b, _, gonderilen, _ = kur(plan=plan, durum=lambda: "ok", hava=None)
        await b.gonder_simdi()
        self.assertNotIn("alınamadı", gonderilen[0])
        self.assertNotIn("🌤 Hava", gonderilen[0])
        self.assertIn("randevun alındı", gonderilen[0])

    async def test_hepsi_kapaliysa_aciklama(self):
        b, _, gonderilen, _ = kur()
        for k in ("yorum", "plan", "yapilacak", "hava", "siber", "durum"):
            await b.ayarla({"eylem": "cikar", "kategori": k})
        await b.gonder_simdi()
        self.assertIn("açık bölüm yok", gonderilen[0])


class SahteSaatleUctanUca(unittest.IsolatedAsyncioTestCase):
    async def test_09da_tek_brifing(self):
        saat = Saat(datetime(2026, 11, 16, 8, 0, tzinfo=TR))
        b, _, gonderilen, depo = kur(saat=saat, plan=plan, durum=lambda: "ok")
        z = zamanlayici.Zamanlayici(simdi=saat, oku=depo.oku, yaz=depo.yaz)
        z.ekle(zamanlayici.GunlukIs("brifing", saat=b.saat, calistir=b.gonder_simdi))
        for dakika in range(0, 240, 1):  # 08:00-12:00 arası her dakika tik
            saat.t = datetime(2026, 11, 16, 8, 0, tzinfo=TR) + timedelta(minutes=dakika)
            await z.tik()
        self.assertEqual(len(gonderilen), 1)
        await b.ayarla({"eylem": "saat", "saat": "11:00"})  # saat değişti ama bugün zaten gitti
        await z.tik()
        self.assertEqual(len(gonderilen), 1)


import yapilacak


def y_kur(saat=None):
    depo = Depo()
    y = yapilacak.Yapilacaklar(oku=depo.oku, yaz=depo.yaz, simdi=saat or Saat(datetime(2026, 11, 16, 1, 0, tzinfo=TR)))
    return y, depo


class Yapilacaklar(unittest.IsolatedAsyncioTestCase):
    async def test_ekle_listele_bitti_kalici(self):
        y, depo = y_kur()
        ok, m = await y.ayarla({"eylem": "ekle", "metin": "Acme raporunu gönder", "tarih": "bugün"})
        self.assertTrue(ok)
        self.assertIn("Pazartesi (16 Kasım) sabahki brifingde", m)
        await y.ayarla({"eylem": "ekle", "metin": "Ömer'i ara", "tarih": "yarın"})
        await y.ayarla({"eylem": "ekle", "metin": "Fransızca kelime çalış"})  # tarihsiz
        self.assertIn("#2 Ömer'i ara (Salı (17 Kasım))", (await y.ayarla({"eylem": "listele"}))[1])
        y2, _ = y_kur()
        y2.oku = depo.oku
        await y2.yukle()  # Render yeniden başladı: liste duruyor
        self.assertEqual(len(y2.isler), 3)
        ok, m = await y2.ayarla({"eylem": "bitti", "metin": "acme"})
        self.assertTrue(ok)
        self.assertIn("Sildim: Acme raporunu gönder", m)
        self.assertEqual([i["id"] for i in y2.isler], [2, 3])

    async def test_belirsiz_bitti_silmez(self):
        y, _ = y_kur()
        await y.ayarla({"eylem": "ekle", "metin": "rapor A"})
        await y.ayarla({"eylem": "ekle", "metin": "rapor B"})
        ok, m = await y.ayarla({"eylem": "bitti", "metin": "rapor"})
        self.assertFalse(ok)
        self.assertIn("2 tanesi eşleşti", m)
        self.assertEqual(len(y.isler), 2)
        self.assertTrue((await y.ayarla({"eylem": "bitti", "id": "#2"}))[0])
        self.assertEqual([i["metin"] for i in y.isler], ["rapor A"])

    async def test_brifing_bolumu(self):
        saat = Saat(datetime(2026, 11, 14, 1, 0, tzinfo=TR))
        y, _ = y_kur(saat)
        await y.ayarla({"eylem": "ekle", "metin": "dün kalan iş", "tarih": "2026-11-15"})
        await y.ayarla({"eylem": "ekle", "metin": "bugünkü iş", "tarih": "2026-11-16"})
        await y.ayarla({"eylem": "ekle", "metin": "yarınki iş", "tarih": "2026-11-17"})
        await y.ayarla({"eylem": "ekle", "metin": "haftaya iş", "tarih": "2026-11-23"})
        await y.ayarla({"eylem": "ekle", "metin": "tarihsiz iş"})
        kisa, satir = y.brifing_bolumu(date(2026, 11, 16))
        self.assertEqual(kisa, "3 iş")
        self.assertEqual(satir, ["dün kalan iş (gecikti: Pazar (15 Kasım))", "bugünkü iş", "tarihsiz iş",
                                 "Yarın: yarınki iş"])  # haftaya iş görünmez

    async def test_brifingde_gorunur(self):
        y, _ = y_kur()
        await y.ayarla({"eylem": "ekle", "metin": "Staj defterini <imzalat>", "tarih": "bugün"})
        b, _, gonderilen, _ = kur(plan=plan, durum=lambda: "ok")
        b.yapilacak_kaynagi = y.brifing_bolumu
        await b.ayarla({"eylem": "cikar", "kategori": "hava"})
        await b.ayarla({"eylem": "cikar", "kategori": "siber"})
        await b.gonder_simdi()
        m = gonderilen[0]
        self.assertNotIn("iş", m.split("\n")[0])  # ilk satırda özet yok, sadece selam
        self.assertIn("<b>✅ Yapılacaklar</b>\n• Staj defterini &lt;imzalat&gt;", m)
        self.assertLess(m.index("<b>📅 Bugün</b>"), m.index("<b>✅ Yapılacaklar</b>"))


class HafizadanSil(unittest.IsolatedAsyncioTestCase):
    async def test_sil(self):
        import main
        with mock.patch.object(main.hafiza, "bilgi_sil", mock.AsyncMock(return_value=1)) as sil:
            ok, m = await main._hafizadan_sil({"anahtar": "profil_12", "neden": "kilo değişti"})
        self.assertTrue(ok)
        sil.assert_awaited_once_with("profil_12")
        self.assertIn("kilo değişti", m)
        with mock.patch.object(main.hafiza, "bilgi_sil", mock.AsyncMock(return_value=0)):
            ok, m = await main._hafizadan_sil({"anahtar": "yok_boyle", "neden": "x"})
        self.assertFalse(ok)
        self.assertFalse((await main._hafizadan_sil({"anahtar": " ", "neden": "x"}))[0])

    def test_tool_kurallari(self):
        import tools
        self.assertEqual(tools.risk_degerlendir("hafizadan_sil", {"anahtar": "x"}), "orta")  # 🟡 bilgi satırı
        self.assertEqual(tools.risk_degerlendir("yapilacak", {"eylem": "ekle"}), "düşük")
        # kritik komut onaysız (🟡), geri dönüşsüz disk komutu onaylı (🔴)
        self.assertEqual(tools.risk_degerlendir("terminal_calistir", {"komut": "del rapor.txt"}), "orta")
        self.assertEqual(tools.risk_degerlendir("terminal_calistir", {"komut": "taskkill /im x.exe"}), "orta")
        self.assertEqual(tools.risk_degerlendir("terminal_calistir", {"komut": "diskpart"}), "yasak")
        self.assertEqual(tools.risk_degerlendir("terminal_calistir", {"komut": "format D: /q"}), "yasak")
        self.assertIn("GÜNCELLEMEK", tools.TOOLLAR["hafizaya_yaz"].aciklama)


# --------------------------------------------------------------------------
# Günün notu, zengin hava, seçici siber
# --------------------------------------------------------------------------

HAVA_SERT = {
    "daily": {"temperature_2m_max": [9.0], "temperature_2m_min": [3.0], "precipitation_probability_max": [90],
              "weather_code": [63], "wind_speed_10m_max": [48.0], "wind_gusts_10m_max": [72.0]},
    "hourly": {"time": [f"2026-11-16T{h:02d}:00" for h in range(24)],
               "temperature_2m": [5.0] * 24, "apparent_temperature": [0.4] * 24,
               "precipitation_probability": [10] * 15 + [80, 85, 90, 70] + [20] * 5,
               "wind_speed_10m": [40.0] * 24, "wind_gusts_10m": [70.0] * 24},
}


class GununNotuVeHava(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.anahtar = mock.patch.object(brifing.config, "TAVILY_API_KEY", "test-anahtari")
        self.anahtar.start()

    def tearDown(self):
        self.anahtar.stop()

    async def test_sert_hava_detaylari(self):
        b, *_ = kur(hava=HAVA_SERT)
        govde = (await b.hava()).govde
        self.assertNotIn("Hissedilen", govde)  # sade: hissedilen yazılmaz
        self.assertIn("yoğun olduğu saatler 15:00-19:00", govde)
        self.assertNotIn("üzgar", govde)  # sade: rüzgar yazılmaz
        self.assertIn("Şemsiye al, mont giy", govde)
        self.assertEqual(b._hava_verisi["yagmur_araligi"], "15:00-19:00")

    async def test_notu_basta_ve_veriyle(self):
        llm = SahteLLM(LLM_CEVAP)
        b, _, gonderilen, _ = kur(plan=plan, durum=lambda: "ok", hava=HAVA_SERT, llm=llm)
        await b.gonder_simdi()
        m = gonderilen[0]
        satirlar = m.split("\n\n")
        self.assertIn(f"<b>💡 Günün notu</b>\n{YORUM}", satirlar)  # düz metin
        self.assertTrue(satirlar[1].startswith("<b>"))
        self.assertIn("Hava · ", satirlar[1])  # selamın hemen altında hava
        self.assertNotIn("<i>", m)  # Kullanıcı eğik yazı istemiyor
        istek = next(k for k in llm.istekler if "günün notu" in k["messages"][-1]["content"])["messages"][-1]["content"]
        self.assertIn('"yagmur_araligi": "15:00-19:00"', istek)  # yorum gerçek veriden
        self.assertIn("20:00-21:00 tenis: randevun alındı", istek)
        self.assertIn("UYDURMA", istek)  # kural metni

    async def test_not_yazilamazsa_sessizce_yok(self):
        b, _, gonderilen, _ = kur(plan=plan, durum=lambda: "ok", llm=SahteLLM(LLM_CEVAP, yorum=RuntimeError("x")))
        await b.gonder_simdi()
        self.assertNotIn("Günün notu", gonderilen[0])
        self.assertNotIn(YORUM, gonderilen[0])
        self.assertIn("<b>📅 Bugün</b>", gonderilen[0])

    async def test_onemli_haber_yoksa_dolgu_yok(self):
        b, istekler, gonderilen, _ = kur(plan=plan, durum=lambda: "ok", llm=SahteLLM("[]"))
        await b.ayarla({"eylem": "cikar", "kategori": "yorum"})
        await b.gonder_simdi()
        self.assertIn("Bugün kayda değer büyük bir siber gelişme yok.", gonderilen[0])
        self.assertNotIn("Siber:", gonderilen[0].split("\n")[0])
        tavily = [json.loads(r.content) for r in istekler if r.url.host == "api.tavily.com"]
        self.assertEqual(len(tavily), 2)
        self.assertIn("bleepingcomputer.com", tavily[0]["include_domains"])

    async def test_bozuk_cevap_bolumu_atlar(self):
        # Model bozuk cevap verirse siber bölümü bir kez daha denenir, yine olmazsa sessizce atlanır
        # (Kullanıcı 21 Kasım 2026: brifingde "alınamadı" satırı istemiyor).
        b, _, gonderilen, _ = kur(plan=plan, durum=lambda: "ok", llm=SahteLLM("anlamadım"))
        await b.ayarla({"eylem": "cikar", "kategori": "yorum"})
        await b.gonder_simdi()
        self.assertNotIn("alınamadı", gonderilen[0])
        self.assertNotIn("🛡 Siber güvenlik", gonderilen[0])
        self.assertIn("<b>📅 Bugün</b>", gonderilen[0])


class HavaYedek(unittest.IsolatedAsyncioTestCase):
    METNO = {"properties": {"timeseries": [
        {"time": f"2026-11-16T{h:02d}:00:00Z",  # UTC: TR saati = +3
         "data": {"instant": {"details": {"air_temperature": 8.0 + h / 2, "wind_speed": 10.0}},
                  "next_1_hours": {"summary": {"symbol_code": "heavyrain" if 12 <= h <= 15 else "cloudy"},
                                   "details": {"precipitation_amount": 2.5 if 12 <= h <= 15 else 0.0}}}}
        for h in range(0, 21)]}}

    def _kur(self, open_meteo_durum, metno=None):
        istekler = []

        def isle(req):
            istekler.append(req)
            if req.url.host == "api.open-meteo.com":
                return httpx.Response(open_meteo_durum, json=HAVA)
            if req.url.host == "api.met.no":
                return httpx.Response(200, json=metno) if metno else httpx.Response(503)
            return httpx.Response(404)

        async def bos(*a, **k):
            return None

        b = brifing.Brifing(gonder=bos, oku=bos, yaz=bos, simdi=Saat(datetime(2026, 11, 16, 9, 0, tzinfo=TR)),
                            istemci=lambda: httpx.AsyncClient(transport=httpx.MockTransport(isle)))
        return b, istekler

    async def test_open_meteo_429_metno_devreye(self):
        b, istekler = self._kur(429, self.METNO)
        govde = (await b.hava()).govde
        self.assertIn("kuvvetli yağmurlu", govde)
        self.assertIn("yoğun saatler 15:00-19:00", govde)  # 12-15 UTC = 15-18 TR
        self.assertNotIn("üzgar", govde)
        self.assertNotIn("Kaynak", govde)  # sade: kaynak yazılmaz
        metno = next(r for r in istekler if r.url.host == "api.met.no")
        self.assertIn("VekilBot", metno.headers["user-agent"])  # MET Norway kimlik ister

    async def test_ikisi_de_olmazsa_sebep_gorunur(self):
        b, _ = self._kur(429)
        with self.assertRaises(brifing.BrifingHatasi) as h:
            await b.hava()
        self.assertEqual(str(h.exception), "Open-Meteo: HTTP 429; MET Norway: HTTP 503")

    async def test_hava_ikisi_de_olmazsa_bolum_sessizce_atlanir(self):
        # 21 Kasım 2026: iki kaynak da patlarsa brifinge "alınamadı" yazılmaz; hava bölümü hiç çıkmaz.
        b, _ = self._kur(429)
        b.ayar["kategoriler"] = ["hava"]
        metin = await b.olustur()
        self.assertNotIn("alınamadı", metin)
        self.assertNotIn("🌤 Hava", metin)
        self.assertIn(f"Günaydın {brifing.config.KULLANICI_ADI}", metin)  # mesaj yine de gider


class Emojiler(unittest.TestCase):
    def test_hava_emojisi_gune_gore(self):
        self.assertEqual(brifing._hava_emoji("gök gürültülü sağanak"), "⛈")
        self.assertEqual(brifing._hava_emoji("hafif yağmurlu"), "🌧")
        self.assertEqual(brifing._hava_emoji("parçalı bulutlu"), "⛅")
        self.assertEqual(brifing._hava_emoji("çoğunlukla açık"), "☀️")
        self.assertEqual(brifing._hava_emoji(""), "🌤")

    def test_el_sallama_yok_ilk_satir_emojisiz(self):
        import inspect
        self.assertNotIn("\U0001F44B", inspect.getsource(brifing))  # 👋 asla
        self.assertEqual(brifing.SELAM, f"Günaydın {brifing.config.KULLANICI_ADI}")


class SadeBrifing(unittest.IsolatedAsyncioTestCase):
    async def test_vekil_durumlari_buyuk_ve_kalin(self):
        b, _, gonderilen, _ = kur(durum=lambda: [("Telefon köprüsü", "bağlı"), ("PC", "kapalı"), ("Bekleyen iş", "yok")])
        b.ayar["kategoriler"] = ["durum"]
        await b.gonder_simdi()
        self.assertIn("<b>⚙️ Vekil</b>: Telefon köprüsü <b>BAĞLI</b> · PC <b>KAPALI</b> · Bekleyen iş <b>YOK</b>",
                      gonderilen[0])

    async def test_uzun_not_iki_cumleye_iner(self):
        uzun = ("Bugün yağmur var, şemsiyeni al. Akşam tenis var, 19:15'te hazırlan. Ayrıca rapor işini unutma. "
                "Bir de su içmeyi unutma ve erken yat çünkü yarın da yoğun bir gün seni bekliyor, dinlenmen lazım.")
        b, *_ = kur(plan=plan, llm=SahteLLM(LLM_CEVAP, yorum=uzun))
        b._hava_verisi = None
        not_ = await b.yorum({"plan": b.plan()})
        self.assertEqual(not_.govde, "<b>💡 Günün notu</b>\nBugün yağmur var, şemsiyeni al. "
                                     "Akşam tenis var, 19:15'te hazırlan.")

    async def test_not_istegi_kisa_ve_ruzgarsiz(self):
        llm = SahteLLM(LLM_CEVAP)
        b, *_ = kur(plan=plan, hava=HAVA_SERT, llm=llm)
        await b.hava()
        await b.yorum({"plan": b.plan()})
        istek = llm.istekler[-1]["messages"][-1]["content"]
        self.assertIn("EN FAZLA 2 kısa cümle", istek)
        self.assertNotIn('"ruzgar', istek)  # rüzgar verisi nota hiç gitmez
