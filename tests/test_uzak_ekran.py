"""uzak_ekran.py testleri: gizli adres, bilet/onay/oturum, eylem doğrulama, kare önbelleği, kilit."""

import asyncio
import json
import types
import unittest
from unittest import mock

import config
import gorevler
import kilit
import uzak_ekran


def istek(token=None, govde=None, sorgu=None, oturum=None, ip="1.2.3.4"):
    async def json_oku():
        return govde

    basliklar = {"x-forwarded-for": ip}
    if oturum:
        basliklar["x-oturum"] = oturum
    return types.SimpleNamespace(
        path_params={"token": token if token is not None else uzak_ekran.token()},
        query_params=sorgu or {}, json=json_oku, headers=basliklar, client=None)


def calistir(c):
    return asyncio.run(c)


class Hazir(unittest.TestCase):
    def setUp(self):
        self._tok = mock.patch.object(config, "ANA_SIR", "123:abc")
        self._tok.start()
        for d in (uzak_ekran._hatalar, uzak_ekran._baglanlar):
            d.clear()
        for d in (uzak_ekran._kare, uzak_ekran._oturumlar, uzak_ekran._biletler, uzak_ekran._bekleyen):
            d.clear()
        self.bildirimler = []

        async def bildir(metin, butonlar):
            self.bildirimler.append((metin, butonlar))

        uzak_ekran.bildirici_kur(bildir)
        kilit.kilitli = False
        self.sid = uzak_ekran._oturum_ac("1.2.3.4")

    def tearDown(self):
        uzak_ekran.bildirici_kur(None)
        self._tok.stop()


class Adres(Hazir):
    def test_token_ve_yol_uzun_rastgele(self):
        self.assertGreaterEqual(len(uzak_ekran.token()), 43)
        self.assertGreaterEqual(len(uzak_ekran.yol()), 17)
        self.assertNotIn("uzak", uzak_ekran.yol())

    def test_yanlis_token_404_cok_denemede_429(self):
        self.assertEqual(calistir(uzak_ekran.sayfa(istek("x"))).status_code, 404)
        for _ in range(uzak_ekran.HATA_LIMIT):
            calistir(uzak_ekran.sayfa(istek("x")))
        self.assertEqual(calistir(uzak_ekran.sayfa(istek("x"))).status_code, 429)

    def test_kilitliyken_403_ve_oturumlar_silinir(self):
        kilit.kilitli = True
        self.assertEqual(calistir(uzak_ekran.sayfa(istek())).status_code, 403)
        self.assertEqual(len(uzak_ekran._oturumlar), 0)

    def test_sayfa_guvenlik_basliklari_ve_font(self):
        r = calistir(uzak_ekran.sayfa(istek()))
        self.assertEqual(r.status_code, 200)
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertIn(b"Silkscreen", r.body)
        self.assertIn(b"data:image/png;base64,", r.body)  # OpenDelegate ikonu gömülü
        self.assertNotIn(b"{{IKON}}", r.body)
        self.assertNotIn(b"Vekil", r.body)


class Baglanti(Hazir):
    def test_oturumsuz_ekran_ve_eylem_401(self):
        self.assertEqual(calistir(uzak_ekran.ekran(istek())).status_code, 401)
        self.assertEqual(calistir(uzak_ekran.eylem(istek(govde={"tur": "tus", "tuslar": "esc"}))).status_code, 401)
        self.assertEqual(calistir(uzak_ekran.ekran(istek(oturum="uydurma"))).status_code, 401)

    def test_bilet_oturum_verir_haber_verir_ve_tekrar_kullanilir(self):
        b = uzak_ekran.bilet_uret()
        r = calistir(uzak_ekran.baglan(istek(govde={"b": b, "m": "SM-S918B"})))
        self.assertIn("oturum", json.loads(r.body))
        self.assertEqual(len(self.bildirimler), 1)
        self.assertIn("uzak:kes", self.bildirimler[0][1][0])
        self.assertIn("Samsung SM-S918B", self.bildirimler[0][0])
        self.assertIn("1.2.3.4", self.bildirimler[0][0])
        # sekmeyi kapatıp açan kullanıcı yine biletle girer (süre: günler)
        r2 = calistir(uzak_ekran.baglan(istek(govde={"b": b})))
        self.assertIn("oturum", json.loads(r2.body))
        uzak_ekran.oturumlari_kes()  # /uzakkapat biletleri de siler
        r3 = calistir(uzak_ekran.baglan(istek(govde={"b": b})))
        self.assertIn("bekle", json.loads(r3.body))

    def test_kesince_telegrama_cihazla_haber_gider(self):
        sid = uzak_ekran._oturum_ac("5.6.7.8", "Samsung SM-S918B · Chrome")
        calistir(uzak_ekran.kes(istek(oturum=sid)))
        metin, butonlar = self.bildirimler[-1]
        self.assertIn("kesildi", metin)
        self.assertIn("Samsung SM-S918B", metin)
        self.assertEqual(butonlar, [])

    def test_cihaz_adi(self):
        ua = ("Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
        r = types.SimpleNamespace(headers={"user-agent": ua})
        self.assertEqual(uzak_ekran._cihaz(r), "Samsung SM-S918B · Chrome")
        r2 = types.SimpleNamespace(headers={"user-agent": ua.replace("SM-S918B Build/UP1A", "K")})
        self.assertEqual(uzak_ekran._cihaz(r2, "SM-A546B"), "Samsung SM-A546B · Chrome")
        self.assertEqual(uzak_ekran._cihaz(r2), "Android telefon · Chrome")
        r3 = types.SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"})
        self.assertEqual(uzak_ekran._cihaz(r3, "<script>x"), "scriptx · Chrome")

    def test_biletsiz_onay_ister_onaylayinca_oturum_bir_kez_verilir(self):
        r = calistir(uzak_ekran.baglan(istek(govde={"b": ""})))
        onay_id = json.loads(r.body)["bekle"]
        self.assertEqual(self.bildirimler[-1][1], [("Onayla", f"uzak:onay:{onay_id}"), ("Reddet", f"uzak:red:{onay_id}")])
        d0 = json.loads(calistir(uzak_ekran.durum(istek(sorgu={"id": onay_id}))).body)
        self.assertEqual(d0["durum"], "bekliyor")
        self.assertIn("onaylandı", uzak_ekran.onay_ver(onay_id, True))
        d1 = json.loads(calistir(uzak_ekran.durum(istek(sorgu={"id": onay_id}))).body)
        self.assertIn("oturum", d1)
        d2 = json.loads(calistir(uzak_ekran.durum(istek(sorgu={"id": onay_id}))).body)
        self.assertNotIn("oturum", d2)  # ikinci kez verilmez

    def test_red_oturum_vermez(self):
        onay_id = json.loads(calistir(uzak_ekran.baglan(istek(govde={}))).body)["bekle"]
        uzak_ekran.onay_ver(onay_id, False)
        d = json.loads(calistir(uzak_ekran.durum(istek(sorgu={"id": onay_id}))).body)
        self.assertEqual(d["durum"], "red")
        self.assertIn("süresi dolmuş", uzak_ekran.onay_ver(onay_id, True))  # reddedilen sonradan onaylanamaz

    def test_telegram_gitmezse_kapali_kalir(self):
        uzak_ekran.bildirici_kur(None)
        r = calistir(uzak_ekran.baglan(istek(govde={})))
        self.assertEqual(r.status_code, 503)
        self.assertEqual(len(uzak_ekran._bekleyen), 0)

    def test_oturum_bosta_duser_ve_kes_kapatir(self):
        uzak_ekran._oturumlar[self.sid]["son"] -= uzak_ekran.OTURUM_BOSTA_SN + 1
        self.assertEqual(calistir(uzak_ekran.ekran(istek(oturum=self.sid))).status_code, 401)
        sid = uzak_ekran._oturum_ac("x")
        calistir(uzak_ekran.kes(istek(oturum=sid)))
        self.assertNotIn(sid, uzak_ekran._oturumlar)

    def test_en_cok_3_oturum_ve_hepsini_kes(self):
        for _ in range(5):
            uzak_ekran._oturum_ac("x")
        self.assertEqual(len(uzak_ekran._oturumlar), uzak_ekran.MAKS_OTURUM)
        self.assertEqual(uzak_ekran.oturumlari_kes(), uzak_ekran.MAKS_OTURUM)
        self.assertEqual(len(uzak_ekran._oturumlar), 0)


class Eylemler(Hazir):
    def test_tikla_alan_onbellekten_ve_sinir(self):
        alan = {"left": 0, "top": 0, "width": 100, "height": 100}
        e = uzak_ekran._eylem({"tur": "tikla", "x": 5, "y": 6, "tus": "sag", "cift": True}, alan)
        self.assertEqual((e["tur"], e["tus"], e["cift"], e["alan"]), ("tikla", "sag", True, alan))
        for kotu in ({"tur": "tikla", "x": 1001, "y": 5}, {"tur": "tikla", "x": "a", "y": 5}, {"tur": "tikla"}):
            with self.assertRaises(ValueError):
                uzak_ekran._eylem(kotu, None)

    def test_gecersiz(self):
        for govde in ({"tur": "yaz", "metin": ""}, {"tur": "tus"}, {"tur": "sil"}):
            with self.assertRaises(ValueError):
                uzak_ekran._eylem(govde, None)

    def test_eylem_ajana_gider_ve_kare_doner(self):
        ozet = json.dumps({"aktif": {"baslik": "Brave", "program": "brave.exe"}, "alan": {"left": 0}})
        sahte = mock.AsyncMock(return_value=(True, ozet, b"PNG"))
        with mock.patch.object(gorevler, "calistir_ekli", sahte):
            r = calistir(uzak_ekran.eylem(istek(govde={"tur": "tus", "tuslar": "enter", "e": "ana"}, oturum=self.sid)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.body, b"PNG")
        self.assertEqual(sahte.call_args.args[0], "bilgisayar_adim")
        self.assertEqual(sahte.call_args.args[1]["eylemler"], [{"tur": "tus", "tuslar": "enter"}])
        self.assertEqual(sahte.call_args.args[1]["bekle"], uzak_ekran.EYLEM_BEKLE)

    def test_vekil_mesgulse_409(self):
        async def dene():
            await gorevler.PC_KILIDI.acquire()
            try:
                with mock.patch.object(uzak_ekran, "KILIT_BEKLE_SN", 0.05):
                    return await uzak_ekran.eylem(istek(govde={"tur": "tus", "tuslar": "esc"}, oturum=self.sid))
            finally:
                gorevler.PC_KILIDI.release()

        self.assertEqual(calistir(dene()).status_code, 409)


class Kare(Hazir):
    def test_ayni_hash_204_ve_taze_kare_ajana_sormaz(self):
        sahte = mock.AsyncMock(return_value=(True, "{}", b"PNG1"))
        with mock.patch.object(gorevler, "calistir_ekli", sahte):
            r1 = calistir(uzak_ekran.ekran(istek(sorgu={"e": "ana"}, oturum=self.sid)))
            h = r1.headers["x-hash"]
            r2 = calistir(uzak_ekran.ekran(istek(sorgu={"e": "ana", "h": h}, oturum=self.sid)))
        self.assertEqual((r1.status_code, r2.status_code), (200, 204))
        self.assertEqual(sahte.await_count, 1)

    def test_ajan_cevrimdisi_503(self):
        sahte = mock.AsyncMock(return_value=(False, "HATA: PC kapalı", None))
        with mock.patch.object(gorevler, "calistir_ekli", sahte):
            r = calistir(uzak_ekran.ekran(istek(oturum=self.sid)))
        self.assertEqual(r.status_code, 503)


class Rotalar(Hazir):
    def test_rotalar_gizli_yolda(self):
        yollar = [r.path for r in uzak_ekran.rotalar()]
        self.assertEqual(len(yollar), 6)
        self.assertTrue(all(y.startswith(uzak_ekran.yol()) and "/uzak" not in y for y in yollar))


if __name__ == "__main__":
    unittest.main()


class WebSohbetEntegrasyonu(unittest.IsolatedAsyncioTestCase):
    """Müşteri ürünü: bağlantı ve onay düğmeleri web sohbetinden geçer (Telegram şart değil)."""

    async def asyncSetUp(self):
        import main
        import web_sohbet
        self.main, self.web = main, web_sohbet
        self._ana = mock.patch.object(config, "ANA_SIR", "gizli-tohum")
        self._url = mock.patch.object(config, "WEBHOOK_URL", "https://ornek.test")
        self._ana.start(), self._url.start()
        kilit.kilitli = False
        self.bot = web_sohbet.WebBot()
        self.update = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=config.TELEGRAM_CHAT_ID),
                                            effective_user=None)

    async def asyncTearDown(self):
        self._ana.stop(), self._url.stop()

    async def test_uzak_komutu_web_sohbetine_biletli_baglanti_yazar(self):
        await self.main.komut_uzak(self.update, types.SimpleNamespace(bot=self.bot, args=[]))
        metin = self.bot.olaylar[-1]["metin"]
        self.assertIn(uzak_ekran.token(), metin)
        self.assertIn("#b=", metin)
        self.assertNotIn("Vekil", metin)

    async def test_onay_dugmesi_web_sohbetinden_calisir(self):
        uzak_ekran._bekleyen.clear()
        uzak_ekran._bekleyen["abc"] = {"olus": __import__("time").monotonic(), "durum": "bekliyor", "oturum": None,
                                       "ip": "1.1.1.1", "cihaz": "Test"}
        mesaj = await self.bot.send_message(1, "istek", reply_markup=types.SimpleNamespace(
            inline_keyboard=[[types.SimpleNamespace(text="Onayla", callback_data="uzak:onay:abc")]]))
        with mock.patch.object(self.web, "web_bot", self.bot):
            await self.main.web_dugme_isle("uzak:onay:abc")
        self.assertEqual(uzak_ekran._bekleyen["abc"]["durum"], "onay")
        self.assertIn("onaylandı", self.bot.olaylar[-1]["metin"])
        uzak_ekran.oturumlari_kes()
        del mesaj
