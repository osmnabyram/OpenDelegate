"""Süre sınırı yok + sade dil + ara bilgi testleri.

Çalıştır: python -m unittest tests.test_uzun_is
"""

import asyncio
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

import config
import gorevler


class SadeDil(unittest.TestCase):
    def test_bilgi_satiri_komut_ve_yol_gostermez(self):
        import main
        satir = main._kisa_ozet("terminal_calistir", {"komut": "git push origin main"},
                                simge="🟡")
        self.assertEqual(satir, "🟡 Kodu sunucuya gönderiyorum")
        self.assertNotIn("<code>", satir)
        satir2 = main._kisa_ozet("terminal_calistir", {"komut": "python -m unittest discover -s tests -q"},
                                 simge="🟡")
        self.assertEqual(satir2, "🟡 Testleri çalıştırıyorum")
        self.assertNotIn("unittest", satir2)
        dosya = main._kisa_ozet("dosya_yaz", {"yol": r"C:\Users\kullanici\Desktop\odev\odev.py", "icerik": "print(1)"},
                                simge="🟡")
        self.assertEqual(dosya, "🟡 Dosyayı kaydediyorum (odev.py)")  # tam yol yok, sadece dosya adı
        self.assertNotIn("dosya_yaz", dosya)
        self.assertIn("İnternette araştırıyorum (python liste sıralama)",
                      main._kisa_ozet("webde_ara", {"sorgu": "python liste sıralama"}))

    def test_talimat(self):
        import main
        p = main.SYSTEM_PROMPT
        self.assertIn("ham kod, terminal komutu, komut çıktısı", p)
        self.assertIn("Uzun işlerde sessiz kalma", p)


class UzunIsHaberi(unittest.IsolatedAsyncioTestCase):
    async def test_surerken_haber_verir_ve_sonucu_doner(self):
        import main
        giden = []

        async def gonder(bot, chat_id, metin):
            giden.append(metin)

        async def uzun_is():
            await asyncio.sleep(0.35)
            return (True, "bitti")

        with mock.patch.object(main, "_gonder", gonder), \
                mock.patch.object(main, "UZUN_IS_ILK_HABER_SN", 0.1), mock.patch.object(main, "UZUN_IS_HABER_ARALIK_SN", 0.1):
            sonuc = await main._surerken_haber(None, 1, uzun_is(), "Bilgisayarda bir işlem çalıştırıyorum")
        self.assertEqual(sonuc, (True, "bitti"))  # kesilmedi, sonuç geldi
        self.assertGreaterEqual(len(giden), 2)
        self.assertTrue(giden[0].startswith("Bilgisayarda bir işlem çalıştırıyorum: hâlâ sürüyor"))

    async def test_kisa_is_sessiz(self):
        import main
        with mock.patch.object(main, "_gonder", mock.AsyncMock()) as gonder:
            self.assertEqual(await main._surerken_haber(None, 1, asyncio.sleep(0, "ok"), "x"), "ok")
        gonder.assert_not_called()


class GorevSuresiz(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        gorevler._gorevler.clear()
        gorevler._iptal_istenen.clear()
        self.p = [mock.patch.object(config, "AJAN_SECRET", "x"), mock.patch.object(config, "GOREV_SONUC_ZAMAN_ASIMI", 0)]
        for p in self.p:
            p.start()
        gorevler.nabiz()

    def tearDown(self):
        for p in self.p:
            p.stop()

    async def test_suresiz_bekler_nabiz_varken(self):
        is_ = asyncio.ensure_future(gorevler.calistir("terminal_calistir", {"komut": "uzun"}, onayli=True))
        await asyncio.sleep(0.05)
        (g,) = gorevler.bekleyenleri_al()
        for _ in range(3):  # ajan "hâlâ çalışıyorum" diyor
            self.assertFalse(gorevler.devam(g["id"]))
            await asyncio.sleep(1.1)
        self.assertFalse(is_.done())  # süre sınırı yok: hâlâ bekliyor
        gorevler.sonuc_yaz(g["id"], True, "[çıkış kodu: 0]")
        self.assertEqual(await is_, (True, "[çıkış kodu: 0]"))

    async def test_dur_ajana_iptal_olarak_gider(self):
        gorevler.SAHIP.set(77)
        is_ = asyncio.ensure_future(gorevler.calistir("terminal_calistir", {"komut": "uzun"}, onayli=True))
        await asyncio.sleep(0.05)
        (g,) = gorevler.bekleyenleri_al()
        _, calisan = gorevler.iptal_et(77)
        self.assertEqual(len(calisan), 1)
        self.assertTrue(gorevler.devam(g["id"]))  # ajan bir sonraki nabızda öğrenir
        gorevler.sonuc_yaz(g["id"], True, "[iptal] kullanıcı durdurdu; komut kapatıldı.")
        await is_
        self.assertNotIn(g["id"], gorevler._iptal_istenen)  # temizlendi

    async def test_baglanti_koparsa_sonsuza_beklemez(self):
        is_ = asyncio.ensure_future(gorevler.calistir("terminal_calistir", {"komut": "uzun"}, onayli=True))
        await asyncio.sleep(0.05)
        gorevler.bekleyenleri_al()
        with mock.patch.object(gorevler, "son_nabiz_sn", return_value=gorevler.BAGLANTI_KOPUK_SN + 1):
            ok, metin = await asyncio.wait_for(is_, 5)
        self.assertFalse(ok)
        self.assertIn("bağlantı koptu", metin)


@unittest.skipUnless(sys.platform == "win32", "ajan Windows'ta çalışır")
class AjanTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ajan"))
        import ajan
        cls.ajan = ajan

    def test_varsayilan_suresiz(self):
        self.assertEqual(self.ajan.TERMINAL_ZAMAN_ASIMI, 0)

    def test_uzun_komut_kesilmez(self):
        self.ajan._IPTAL.clear()
        bas = time.monotonic()
        cikti = self.ajan.terminal_calistir("ping -n 4 127.0.0.1 >nul && echo bitti", onayli=True)
        self.assertGreater(time.monotonic() - bas, 2.5)
        self.assertIn("[çıkış kodu: 0]", cikti)
        self.assertIn("bitti", cikti)

    def test_arkada_kalan_surec_beklenmez(self):
        # 'start /b' ile kalan süreç çıktının ucunu miras alır; kabuk bitince dönülmeli (21.11: ajan asılı kaldı).
        self.ajan._IPTAL.clear()
        bas = time.monotonic()
        cikti = self.ajan.terminal_calistir('start "" /b ping -n 20 127.0.0.1 & echo hazir', onayli=True)
        self.assertLess(time.monotonic() - bas, 10)
        self.assertIn("hazir", cikti)

    def test_dur_gelince_komut_kapanir(self):
        self.ajan._IPTAL.clear()
        threading.Timer(1.5, self.ajan._IPTAL.set).start()
        bas = time.monotonic()
        cikti = self.ajan.terminal_calistir("ping -n 60 127.0.0.1", onayli=True)
        self.assertLess(time.monotonic() - bas, 15)  # 60 sn beklemedi
        self.assertIn("[iptal]", cikti)
        self.ajan._IPTAL.clear()


if __name__ == "__main__":
    unittest.main()
