"""Telefon araması: Twilio ve model sahte; gerçek arama YOK. Kurallar, konuşma turu, kapanış, özet, kota, imza."""

import asyncio
import json
import unittest
from unittest import mock
from datetime import datetime
from types import SimpleNamespace

import arama
from zamanlayici import TR


class SahteHat:
    def __init__(self, hata=None, durumlar=None):
        self.cagrilar, self.hata, self.durumlar = [], hata, list(durumlar or [])

    async def ara(self, kime, url):
        if self.hata:
            raise self.hata
        self.cagrilar.append((kime, url))
        return f"CA{len(self.cagrilar)}"

    async def durum(self, sid):
        return self.durumlar.pop(0)


def cagri(ad, arg, i="c1"):
    return SimpleNamespace(id=i, function=SimpleNamespace(name=ad, arguments=json.dumps(arg)))


def mesaj(icerik="", cagrilar=None):
    return SimpleNamespace(content=icerik, tool_calls=cagrilar)


class Temel(unittest.IsolatedAsyncioTestCase):
    async def kur(self, saat=14, hat=None, sentez_bozuk=False, kilitli=False, izle=False):
        self.hat = hat or SahteHat()
        self.metinler, self.depo, self.cevaplar, self.arac_cagrilari, self.konusan = [], {}, [], [], []
        self.zaman = datetime(2026, 11, 15, saat, 0, tzinfo=TR)

        async def dusun(mesajlar, semalar):
            self.son_semalar = semalar
            return self.cevaplar.pop(0)

        async def sentez(m):
            if sentez_bozuk:
                raise OSError("ağ yok")
            return b"MP3" + m.encode()

        async def gonder(m):
            self.metinler.append(m)

        async def oku(k):
            return self.depo.get(k)

        async def yaz(k, v):
            self.depo[k] = json.loads(json.dumps(v))

        async def zamanla(arg):
            self.arac_cagrilari.append(arg)
            return True, "Tamam, zamanladım: #1 15:30 hatırlatma: ilaç"

        async def sistem():
            return "[Hafıza] kullanıcı tenis yapar."

        async def konustu(g):
            self.konusan.append(g.id)

        self.a = arama.Arama(hat=self.hat, taban_url="https://vekil.test", token="tok", auth_token="gizli",
                             kullanici="+905550000000", dusun=dusun, sistem=sistem, araclar={"zamanla": zamanla},
                             semalar=[{"type": "function", "function": {"name": "zamanla"}}], sentez=sentez,
                             gonder_metin=gonder, kilitli=lambda: kilitli, konustu_cb=konustu,
                             oku=oku, yaz=yaz, simdi=lambda: self.zaman, uyu=self._uyu, izle=izle)
        await self.a.yukle()

    async def _uyu(self, sn):
        pass

    def gid(self):
        return next(iter(self.a.gorusmeler))


class Kurallar(Temel):
    async def test_istek_arar_ve_url_token_icerir(self):
        await self.kur()
        ok, m = await self.a.ayarla({"eylem": "ara", "soyle": "Toplantın yarım saat sonra.", "neden": "toplantı"})
        self.assertTrue(ok, m)
        kime, url = self.hat.cagrilar[0]
        self.assertEqual(kime, "+905550000000")
        self.assertTrue(url.startswith("https://vekil.test/arama/tok/basla?g="))

    async def test_bitis_twilioya_sorularak_izlenir(self):
        await self.kur(hat=SahteHat(durumlar=[("ringing", 0), ("in-progress", 5), ("no-answer", 0)]), izle=True)
        ok, _ = await self.a.ara("tenis randevusu alınamadı", "Kanka", otomatik=True)
        self.assertTrue(ok)
        for t in list(self.a._gorevler):
            await t
        self.assertIn("açmadın", self.metinler[0])
        self.assertEqual(self.a.gorusmeler, {})

    async def test_konusamadiysak_teshis(self):
        await self.kur()

        async def notlar(sid):
            return ["11200: HTTP retrieval failure"]

        self.hat.notlar = notlar
        await self.a.ara("istek", "Kanka", otomatik=False)
        await self.a.bitti(self.gid(), {"CallStatus": "completed", "CallDuration": "8"})
        self.assertIn("hiç ulaşmadı", self.metinler[0])
        self.assertIn("11200", self.metinler[0])

    async def test_gece_de_arar(self):  # Kullanıcı 15.11: önemliyse her saatte
        await self.kur(saat=2)
        ok, m = await self.a.ara("acil: x", "Kanka acil", otomatik=True)
        self.assertTrue(ok, m)

    async def test_gunluk_sinir_yok(self):  # Kullanıcı 15.11: kendi sistemini kota yüzünden kullanamamasın
        await self.kur()
        for _ in range(25):
            ok, m = await self.a.ara("tenis", "Kanka", otomatik=True)
            self.assertTrue(ok, m)
            await self.a.bitti(self.gid(), {"CallStatus": "no-answer"})
        self.assertEqual(len(self.hat.cagrilar), 25)

    async def test_yarida_kopunca_teknik_iz(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.cevaplar = [mesaj("Buradayım.")]
        await self.a.cevap(g, "selam")
        self.a.gorusmeler[g].kayit.append(("Sen", "hava nasıl"))  # cevap gelmeden koptu
        await self.a.bitti(g, {"CallStatus": "completed", "CallDuration": "40"})
        self.assertIn("Teknik iz", self.metinler[0])
        self.assertIn("cevap hazır", self.metinler[0])

    async def test_sinir_ertesi_gun_sifirlanir(self):
        await self.kur()
        self.depo[arama.ANAHTAR] = {"gunluk": {"tarih": "2026-11-14", "otomatik": 3, "toplam": 9}}
        await self.a.yukle()
        ok, _ = await self.a.ara("tenis", "Kanka", otomatik=True)
        self.assertTrue(ok)

    async def test_ayni_anda_iki_arama_yok(self):
        await self.kur()
        await self.a.ara("a", "Kanka", otomatik=False)
        ok, m = await self.a.ara("b", "Kanka", otomatik=False)
        self.assertFalse(ok)
        self.assertIn("sürüyor", m)

    async def test_kilitliyken_aramaz(self):
        await self.kur(kilitli=True)
        ok, _ = await self.a.ara("a", "Kanka", otomatik=False)
        self.assertFalse(ok)
        self.assertEqual(self.hat.cagrilar, [])

    async def test_twilio_hatasi_anlasilir(self):
        await self.kur(hat=SahteHat(arama.AramaHatasi("numaran Twilio'da doğrulanmamış")))
        ok, m = await self.a.ara("a", "Kanka", otomatik=False)
        self.assertFalse(ok)
        self.assertIn("doğrulanmamış", m)
        self.assertEqual(self.a.gorusmeler, {})  # yarım görüşme kalmaz, sonraki arama engellenmez


class Konusma(Temel):
    async def test_basla_vekil_sesi_ve_turkce_dinleme(self):
        await self.kur()
        await self.a.ara("toplantı", "Kanka, Vekil ben. Toplantın var.", otomatik=False)
        x = await self.a.basla(self.gid())
        self.assertIn("<Play>https://vekil.test/arama/tok/ses/", x)
        self.assertIn('language="tr-TR"', x)
        self.assertIn('input="speech"', x)
        sid = x.split("/ses/")[1].split(".mp3")[0]
        self.assertEqual(await self.a.ses_al(sid), "MP3Kanka, Vekil ben, Toplantın var.".encode())  # tek cümle (dil kayması)
        self.assertIn("tenis yapar", self.a.gorusmeler[self.gid()].mesajlar[0]["content"])

    async def test_arac_cagrisi_sonra_cevap(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.cevaplar = [mesaj(cagrilar=[cagri("zamanla", {"eylem": "ekle", "zaman": "15:30", "metin": "ilaç"})]),
                         mesaj("Tamam, 15:30'da ilacını hatırlatırım.")]
        x = await self.a.cevap(g, "üç buçukta ilacımı hatırlat")
        self.assertEqual(self.arac_cagrilari[0]["zaman"], "15:30")
        self.assertIn("<Gather", x)
        self.assertEqual(self.konusan, [g])
        self.assertIn("telefonu_kapat", [s["function"]["name"] for s in self.son_semalar])

    async def test_telefonda_olmayan_arac_calismaz(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.cevaplar = [mesaj(cagrilar=[cagri("terminal_calistir", {"komut": "del x"})]),
                         mesaj("Bunu Telegram'dan hallederiz.")]
        await self.a.cevap(g, "masaüstündeki dosyayı sil")
        tool_mesaji = [m for m in self.a.gorusmeler[g].mesajlar if m["role"] == "tool"][0]
        self.assertIn("telefonda yok", tool_mesaji["content"])

    async def test_kapat(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.cevaplar = [mesaj("Görüşürüz kanka.", [cagri("telefonu_kapat", {})])]
        x = await self.a.cevap(g, "tamam kapat")
        self.assertIn("<Hangup/>", x)
        self.assertNotIn("<Gather", x)

    async def test_iki_kez_sessizlik_kapatir(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.assertIn("<Gather", await self.a.cevap(g, ""))
        self.assertIn("<Hangup/>", await self.a.cevap(g, "  "))
        self.assertEqual(self.konusan, [])

    async def test_kadin_sesi_yok_hep_vekil_sesi(self):  # Kullanıcı: sadece Vekil sesi; <Say> yedeği yok
        await self.kur(sentez_bozuk=True)
        await self.a.ara("istek", "Kanka & selam", otomatik=False)
        x = await self.a.basla(self.gid())
        self.assertNotIn("<Say", x)
        self.assertNotIn("<Play", x)  # üretilemeyen ses Twilio'ya hiç verilmez (verilirse arama kopar)
        self.assertIn("<Gather", x)  # sessizce dinlemeye devam

    async def test_gec_cevapta_bakiyorum_sesi(self):  # sessizlik yok + Twilio 15 sn sınırı aşılmaz
        await self.kur()
        yavas = asyncio.Event()

        async def dusun(mesajlar, semalar):
            await yavas.wait()
            return mesaj("Hava güneşli kanka.")

        self.a.dusun = dusun
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        with mock.patch.object(arama, "ILK_BEKLEME", 0.01), mock.patch.object(arama, "BEKLEME_ADIMI", 0.01):
            x = await self.a.cevap(g, "hava nasıl")
            self.assertIn("<Redirect", x)
            self.assertIn("/bekle?g=" + g, x)
            sid = x.split("/ses/")[1].split(".mp3")[0]
            self.assertEqual(await self.a.ses_al(sid), "MP3Bir saniye efendim, bakıyorum.".encode())
            x2 = await self.a.bekle(g)
            self.assertIn("<Redirect", x2)  # hâlâ bakıyor: bu tur kısa sessizlik (her 3 sn'de konuşmasın)
            self.assertIn("<Pause", x2)
            yavas.set()
        x3 = await self.a.bekle(g)  # normal bekleme süresiyle: cevap hazır olur
        self.assertIn("<Gather", x3)
        sid3 = x3.split("/ses/")[1].split(".mp3")[0]
        self.assertEqual(await self.a.ses_al(sid3), "MP3Hava güneşli kanka.".encode())

    async def test_cok_uzun_iste_konusma_surer(self):
        await self.kur()
        yavas = asyncio.Event()
        cevaplar = [mesaj("Bitti kanka."), mesaj("Başka yok.")]

        async def dusun(mesajlar, semalar):
            if len(cevaplar) == 2:
                await yavas.wait()
            return cevaplar.pop(0)

        self.a.dusun = dusun
        await self.a.ara("istek", "Kanka", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        with mock.patch.object(arama, "ILK_BEKLEME", 0.01), mock.patch.object(arama, "BEKLEME_ADIMI", 0.01), \
                mock.patch.object(arama, "UZUN_IS", -1):
            await self.a.cevap(g, "uzun bir iş yap")
            x = await self.a.bekle(g)
        self.assertIn("<Gather", x)  # "bitince Telegram'a yazarım", dinlemeye devam
        self.assertIsNotNone(self.a.gorusmeler[g].onceki)
        yavas.set()
        x2 = await self.a.cevap(g, "tamam")  # yeni tur önceki işi bekler, sonra cevaplar
        self.assertIn("<Gather", x2)
        roller = [m["role"] for m in self.a.gorusmeler[g].mesajlar]
        self.assertEqual(roller, ["system", "assistant", "user", "assistant", "user", "assistant"])

    async def test_acilista_tanitim_tekrari_yok(self):
        await self.kur()
        await self.a.ayarla({"eylem": "ara", "soyle": "Kanka ben Vekil, test için arıyorum."})
        self.assertEqual(self.a.gorusmeler[self.gid()].acilis, "Kanka ben Vekil, test için arıyorum.")

    async def test_bilinmeyen_gorusme_kibarca_kapanir(self):
        await self.kur()
        self.assertIn("<Hangup/>", await self.a.cevap("yok", "selam"))


class Sonuc(Temel):
    async def test_acmadi_mesaji(self):
        await self.kur()
        await self.a.ara("tenis randevusu alınamadı", "Kanka", otomatik=True)
        await self.a.bitti(self.gid(), {"CallStatus": "no-answer", "CallDuration": "0"})
        self.assertEqual(len(self.metinler), 1)
        self.assertIn("açmadın", self.metinler[0])
        self.assertIn("tenis randevusu alınamadı", self.metinler[0])
        self.assertEqual(self.a.gorusmeler, {})

    async def test_ozet_ve_dakika(self):
        await self.kur()
        await self.a.ara("istek", "Kanka, Vekil ben.", otomatik=False)
        g = self.gid()
        await self.a.basla(g)
        self.cevaplar = [mesaj(cagrilar=[cagri("zamanla", {"eylem": "ekle"})]), mesaj("Tamam.")]
        await self.a.cevap(g, "ilacımı hatırlat")
        await self.a.bitti(g, {"CallStatus": "completed", "CallDuration": "65"})
        ozet = self.metinler[0]
        self.assertIn("(2 dk)", ozet)
        self.assertIn("Sen: ilacımı hatırlat", ozet)
        self.assertIn("zamanladım", ozet)
        self.assertEqual(self.depo[arama.ANAHTAR]["harcanan_sn"], 120)  # başlayan dakika tam sayılır

    async def test_ara_durum_yok_sayilir(self):
        await self.kur()
        await self.a.ara("istek", "Kanka", otomatik=False)
        await self.a.bitti(self.gid(), {"CallStatus": "in-progress"})
        self.assertEqual(self.metinler, [])
        self.assertEqual(len(self.a.gorusmeler), 1)

    async def test_kota_uyarisi_bir_kez(self):
        await self.kur()
        self.a.durum["harcanan_sn"] = 62 * 60
        await self.a.kota_kontrol()
        await self.a.kota_kontrol()
        self.assertEqual(len(self.metinler), 1)
        self.assertIn("13 dk", self.metinler[0])

    async def test_sure_bitiyor_uyarisi(self):
        await self.kur()
        self.zaman = datetime(2026, 12, 13, 10, 0, tzinfo=TR)
        await self.a.kota_kontrol()
        self.assertIn("2 gün sonra", self.metinler[0])


class SureButcesi(unittest.TestCase):
    def test_sure_butcesi(self):  # Twilio ~5 sn'den uzun cevabı almıyor (15.11 teknik izleri)
        self.assertLessEqual(arama.ILK_BEKLEME + arama.DOLGU_HAZIR, arama.WEBHOOK_BUTCESI)
        self.assertLessEqual(arama.BEKLEME_ADIMI + arama.DOLGU_HAZIR, arama.WEBHOOK_BUTCESI)
        self.assertLessEqual(arama.HAZIR_BEKLEME, arama.WEBHOOK_BUTCESI)


class TekCumle(unittest.TestCase):
    def test_cumleler_virgulle_baglanir(self):
        self.assertEqual(arama.tek_cumle("Süper kanka. Ses net!  Bir şey lazım mı?"),
                         "Süper kanka, Ses net, Bir şey lazım mı?")
        self.assertEqual(arama.tek_cumle("Tamam kanka."), "Tamam kanka.")
        self.assertEqual(arama.tek_cumle("Saat 15:30'da. Hatırlatırım"), "Saat 15:30'da, Hatırlatırım")


class Imza(unittest.TestCase):
    def test_dogru_ve_kurcalanmis(self):
        url, form = "https://vekil.test/arama/tok/cevap?g=abc", {"SpeechResult": "selam", "CallSid": "CA1"}
        i = arama.imza(url, form, "gizli")
        self.assertTrue(arama.imza_dogru(url, form, i, "gizli"))
        self.assertFalse(arama.imza_dogru(url, {**form, "SpeechResult": "sil"}, i, "gizli"))
        self.assertFalse(arama.imza_dogru(url, form, i, "baska"))
        self.assertFalse(arama.imza_dogru(url, form, "", "gizli"))

    def test_443_portlu_imza_da_kabul(self):
        url, form = "https://vekil.test/arama/tok/basla?g=abc", {"CallSid": "CA1"}
        portlu = arama.imza("https://vekil.test:443/arama/tok/basla?g=abc", form, "gizli")
        self.assertTrue(arama.imza_dogru(url, form, portlu, "gizli"))
        self.assertFalse(arama.imza_dogru(url, form, arama.imza("https://vekil.test:8443/arama/tok/basla?g=abc",
                                                                  form, "gizli"), "gizli"))

    def test_twilio_belgesindeki_ornek(self):
        # Twilio'nun güvenlik belgesindeki örnek (auth token 12345).
        url = "https://mycompany.com/myapp.php?foo=1&bar=2"
        form = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234",
                "From": "+12349013030", "To": "+18005551212"}
        self.assertEqual(arama.imza(url, form, "12345"), "0/KCTR6DLpKmkAf8muzZqo1nDgQ=")


class HttpUclari(unittest.IsolatedAsyncioTestCase):
    async def test_imzasiz_istek_403_imzali_200(self):
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        t = Temel()
        await t.kur()
        a = t.a
        await a.ara("istek", "Kanka", otomatik=False)
        await asyncio.gather(*(t for t, _ in a.sesler.values()))  # açılış sesi bu döngüde üretildi; hazır olsun
        g = next(iter(a.gorusmeler))
        app = Starlette(routes=arama.rotalar(lambda: a))
        yol = f"/arama/tok/basla?g={g}"
        form = {"CallSid": "CA1", "CallStatus": "in-progress"}
        imza = arama.imza("https://vekil.test" + yol, form, "gizli")
        with TestClient(app, base_url="https://vekil.test") as c:
            baska = {**form, "CallSid": "CA999"}  # başka arama: imzası doğru olsa bile reddedilir
            self.assertEqual(c.post(yol, data=baska, headers={
                "X-Twilio-Signature": arama.imza("https://vekil.test" + yol, baska, "gizli")}).status_code, 403)
            self.assertEqual(c.post("/arama/yanlis/basla?g=" + g, data=form,
                                    headers={"X-Twilio-Signature": imza}).status_code, 403)
            self.assertEqual(c.post("/arama/tok/basla?g=yok", data=form,
                                    headers={"X-Twilio-Signature": imza}).status_code, 403)
            r0 = c.post(yol, data=form, headers={"X-Twilio-Signature": "tutmayan"})  # canlıdaki durum
            self.assertEqual(r0.status_code, 200)
            r = c.post(yol, data=form, headers={"X-Twilio-Signature": imza})
            self.assertEqual(r.status_code, 200)
            self.assertIn("<Gather", r.text)
            ses_url = r.text.split("<Play>")[1].split("</Play>")[0].replace("https://vekil.test", "")
            self.assertEqual(c.get(ses_url).status_code, 200)
            self.assertEqual(c.get("/arama/yanlis/ses/x.mp3").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TwilioUyarilari(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_alerts_okunur(self):
        import httpx

        gercek = httpx.AsyncClient

        def isle(req):
            if req.url.host == "monitor.twilio.com":
                return httpx.Response(200, json={"alerts": [
                    {"resource_sid": "CA9", "error_code": "11200", "alert_text": "Msg=HTTP+retrieval+failure&x=1"},
                    {"resource_sid": "CAbaska", "error_code": "1", "alert_text": "Msg=baska"}]})
            return httpx.Response(200, json={"notifications": []})

        with mock.patch("httpx.AsyncClient", lambda **kw: gercek(transport=httpx.MockTransport(isle))):
            notlar = await arama.TwilioHat("AC1", "t", "+1").notlar("CA9")
        self.assertEqual(notlar, ["11200: HTTP retrieval failure"])


class DonguOlcer(Temel):
    async def test_tikanma_ize_yazilir(self):
        import asyncio as _a
        import time as _t

        await self.kur()
        self.a.gorusmeler["x"] = arama.Gorusme(id="x", neden="n", acilis="a", otomatik=False)
        olcer = _a.ensure_future(self.a._dongu_olc())
        await _a.sleep(0.05)
        _t.sleep(0.8)  # sunucuyu tıkayan senkron iş
        await _a.sleep(0.4)
        olcer.cancel()
        self.assertTrue(any("TIKANDI" in m for _, m in self.a.olaylar))
