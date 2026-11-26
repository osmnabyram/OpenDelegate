"""Web Push: abonelik doğrulama/saklama, ne zaman bildirim gider (sekme kapalıyken), sınırlama, geçersiz abonelik temizliği."""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient

import config
import main
import web_push
import web_sohbet
from web_sohbet import DenemeSiniri, Oturumlar, WebBot

H = {"X-OD": "1"}
ABONE = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "keys": {"p256dh": "BPk" + "x" * 40, "auth": "y" * 16}}


class AboneTesti(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        web_push._aboneler.clear()
        web_push._son_gonderim = 0.0
        self.yaz = mock.patch("zamanlayici.ayar_yaz", mock.AsyncMock())
        self.yaz.start()

    def tearDown(self):
        self.yaz.stop()
        web_push._aboneler.clear()

    def test_gecerlilik(self):
        self.assertTrue(web_push.abone_gecerli(ABONE))
        self.assertFalse(web_push.abone_gecerli({**ABONE, "endpoint": "http://fcm.googleapis.com/x"}))  # https şart
        for kotu in ("https://ic-servis.local/x", "https://169.254.169.254/latest", "https://localhost/x",
                     "https://evilgoogleapis.com/x", "https://fcm.googleapis.com.kotu.site/x",
                     "https://kullanici:parola@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x"):
            self.assertFalse(web_push.abone_gecerli({**ABONE, "endpoint": kotu}), kotu)  # SSRF: sadece bilinen push servisleri
        for iyi in ("https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
                    "https://wns2-par02p.notify.windows.com/x"):
            self.assertTrue(web_push.abone_gecerli({**ABONE, "endpoint": iyi}), iyi)
        self.assertFalse(web_push.abone_gecerli({**ABONE, "endpoint": "https:///x"}))
        self.assertFalse(web_push.abone_gecerli({**ABONE, "endpoint": "https://a.test/" + "x" * 700}))
        self.assertFalse(web_push.abone_gecerli({"endpoint": ABONE["endpoint"], "keys": {"p256dh": "x"}}))
        self.assertFalse(web_push.abone_gecerli({"endpoint": ABONE["endpoint"]}))
        self.assertFalse(web_push.abone_gecerli("abone"))

    async def test_ekle_tekrar_ve_sinir(self):
        self.assertTrue(await web_push.abone_ekle({**ABONE, "fazla": "alan"}))
        self.assertEqual(web_push._aboneler[0].keys(), {"endpoint", "keys"})  # fazladan alan saklanmaz
        await web_push.abone_ekle(ABONE)
        self.assertEqual(len(web_push._aboneler), 1)  # aynı uç nokta tekrar eklenmez
        for i in range(8):
            await web_push.abone_ekle({**ABONE, "endpoint": f"https://fcm.googleapis.com/fcm/send/{i}"})
        self.assertEqual(len(web_push._aboneler), web_push.MAKS_ABONE)
        self.assertFalse(await web_push.abone_ekle({"endpoint": "http://x"}))

    async def test_sil(self):
        await web_push.abone_ekle(ABONE)
        await web_push.abone_sil(ABONE["endpoint"])
        self.assertEqual(web_push._aboneler, [])


class BildirimTesti(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        web_push._aboneler[:] = [ABONE]
        web_push._son_gonderim = 0.0
        self.yaz = mock.patch("zamanlayici.ayar_yaz", mock.AsyncMock())
        self.yaz.start()
        self.acik = mock.patch.object(web_push, "acik", return_value=True)
        self.acik.start()

    def tearDown(self):
        self.yaz.stop()
        self.acik.stop()
        web_push._aboneler.clear()

    async def test_bildirim_metin_tasimaz(self):
        yuk = []
        with mock.patch.object(web_push, "_gonder_tek", side_effect=lambda a: yuk.append(a) or 201):
            await web_push.bildir()
        self.assertEqual(yuk, [ABONE])
        self.assertEqual((web_push.BASLIK, web_push.GOVDE), ("OpenDelegate", "Yeni mesaj"))

    async def test_sinirlama_iki_bildirim_arasi(self):
        with mock.patch.object(web_push, "_gonder_tek", return_value=201) as g:
            await web_push.bildir()
            await web_push.bildir()
        self.assertEqual(g.call_count, 1)

    async def test_410_aboneyi_siler_ag_hatasi_silmez(self):
        with mock.patch.object(web_push, "_gonder_tek", return_value=0):
            await web_push.bildir()
        self.assertEqual(len(web_push._aboneler), 1)
        web_push._son_gonderim = 0.0
        with mock.patch.object(web_push, "_gonder_tek", return_value=410):
            await web_push.bildir()
        self.assertEqual(web_push._aboneler, [])

    async def test_abone_yoksa_veya_kapaliysa_hic_gonderilmez(self):
        web_push._aboneler.clear()
        with mock.patch.object(web_push, "_gonder_tek") as g:
            await web_push.bildir()
        g.assert_not_called()


class TetikTesti(unittest.IsolatedAsyncioTestCase):
    async def test_sadece_ekran_kapaliyken_ve_sadece_asistan_mesajinda(self):
        b = WebBot()
        cagri = []
        b.bildirim = lambda: cagri.append(1)
        await b.send_message(1, "ekran hiç açılmadı")
        self.assertEqual(len(cagri), 1)  # sekme kapalı: bildirim
        b.yoklandi()
        await b.send_message(1, "ekran açık")
        self.assertEqual(len(cagri), 1)  # açık: bildirim yok
        b._son_yoklama = time.time() - 60
        b.kullanici_yazdi("benim yazdığım")
        b.gecmis_yukle([])  # kullanıcı olayı ve düz olaylar bildirim açmaz
        self.assertEqual(len(cagri), 1)
        await b.send_photo(1, b"\x89PNG\r\n\x1a\n" + b"0" * 10)
        self.assertEqual(len(cagri), 2)  # medya da sayılır

    async def test_kancasiz_bot_hata_vermez(self):
        b = WebBot()
        await b.send_message(1, "x")

    def test_tetikle_dongu_yoksa_sessiz(self):
        web_push._aboneler[:] = [ABONE]
        try:
            web_push.tetikle()  # çalışan döngü yok: hata vermemeli
        finally:
            web_push._aboneler.clear()


class RotaTesti(unittest.TestCase):
    def setUp(self):
        self.yamalar = [mock.patch.object(config, "WEB_PAROLA", "test-web-parolasi-123"), mock.patch.object(config, "WEB_TOTP_SIR", ""),
                        mock.patch("zamanlayici.ayar_yaz", mock.AsyncMock())]
        for y in self.yamalar:
            y.start()
        web_sohbet.oturumlar = Oturumlar()
        web_sohbet.deneme_siniri = DenemeSiniri()
        web_push._aboneler.clear()
        self.istemci = TestClient(main.web_uygulamasi(None), base_url="https://od.test")

    def tearDown(self):
        for y in self.yamalar:
            y.stop()
        web_push._aboneler.clear()

    def giris(self):
        self.istemci.post("/sohbet/giris", json={"parola": "test-web-parolasi-123"}, headers=H)

    def test_anahtar_girissiz_kapali(self):
        self.assertEqual(self.istemci.get("/sohbet/push/anahtar").status_code, 401)

    def test_kutuphane_yoksa_kapali_bildirir(self):
        self.giris()
        with mock.patch.object(web_push, "acik", return_value=False):
            self.assertEqual(self.istemci.get("/sohbet/push/anahtar").json(), {"acik": False})
            self.assertEqual(self.istemci.post("/sohbet/push/abone", json=ABONE, headers=H).status_code, 400)

    def test_abone_ekle_ve_iptal(self):
        self.giris()
        with mock.patch.object(web_push, "acik", return_value=True):
            self.assertEqual(self.istemci.post("/sohbet/push/abone", json=ABONE).status_code, 403)  # X-OD yok
            self.assertEqual(self.istemci.post("/sohbet/push/abone", json={"endpoint": "http://x"}, headers=H).status_code, 400)
            self.assertEqual(self.istemci.post("/sohbet/push/abone", json=ABONE, headers=H).status_code, 200)
            self.assertEqual(len(web_push._aboneler), 1)
            self.assertEqual(self.istemci.post("/sohbet/push/iptal", json={"endpoint": ABONE["endpoint"]}, headers=H).status_code, 200)
            self.assertEqual(web_push._aboneler, [])

    def test_servis_calisani_manifest_ve_ikon_csp(self):
        sw = self.istemci.get("/sohbet/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn("javascript", sw.headers["content-type"])
        self.assertIn("showNotification", sw.text)
        self.assertNotIn("fetch(", sw.text)  # önbellek/ağ aracılığı yok
        m = self.istemci.get("/sohbet/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.json()["start_url"], "/sohbet")
        self.assertEqual(self.istemci.get("/sohbet/dosya/ikon-192.png").headers["content-type"], "image/png")
        csp = self.istemci.get("/sohbet").headers["content-security-policy"]
        self.assertIn("worker-src 'self'", csp)
        self.assertIn("manifest-src 'self'", csp)
        self.assertNotIn("unsafe", csp)


if __name__ == "__main__":
    unittest.main()
