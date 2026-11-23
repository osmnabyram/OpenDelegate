"""Saatli hatırlatma/görev (zamanli), PC'de dosya arama (ajan.dosya_ara), OneDrive taşıma (onedrive.tasi).

Çalıştır: python -m unittest tests.test_ozellikler
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import onedrive
import zamanli
from zamanlayici import TR


class Saat:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Depo:
    def __init__(self):
        self.veri = {}

    async def oku(self, k):
        return json.loads(json.dumps(self.veri[k])) if k in self.veri else None

    async def yaz(self, k, v):
        self.veri[k] = json.loads(json.dumps(v))


def kur(saat, depo=None):
    depo = depo or Depo()
    tetiklenen = []

    async def calistir(k, gecikmeli):
        tetiklenen.append((k["metin"], k["tur"], gecikmeli))

    z = zamanli.Zamanli(calistir=calistir, oku=depo.oku, yaz=depo.yaz, simdi=saat)
    return z, depo, tetiklenen


async def bitir(z):
    for _ in range(20):
        await asyncio.sleep(0)
    if z._gorevler:
        await asyncio.gather(*list(z._gorevler))


# --------------------------------------------------------------------------
# 1) Saatli hatırlatma / zamanlanmış görev
# --------------------------------------------------------------------------

class ZamanCozme(unittest.TestCase):
    def setUp(self):
        self.z, *_ = kur(Saat(datetime(2026, 11, 16, 14, 0, tzinfo=TR)))

    def test_bicimler(self):
        self.assertEqual(self.z.zaman_coz("15:00"), datetime(2026, 11, 16, 15, 0, tzinfo=TR))
        self.assertEqual(self.z.zaman_coz("13:00"), datetime(2026, 11, 17, 13, 0, tzinfo=TR))  # geçti: yarın
        self.assertEqual(self.z.zaman_coz("yarın 9.30"), datetime(2026, 11, 17, 9, 30, tzinfo=TR))
        self.assertEqual(self.z.zaman_coz("2026-11-20 08:15"), datetime(2026, 11, 20, 8, 15, tzinfo=TR))
        self.assertEqual(self.z.zaman_coz("2026-11-20T08:15"), datetime(2026, 11, 20, 8, 15, tzinfo=TR))

    def test_gecmis_ve_bozuk(self):
        with self.assertRaises(ValueError):
            self.z.zaman_coz("2026-11-16 13:00")  # geçmiş
        with self.assertRaises(ValueError):
            self.z.zaman_coz("öğleden sonra")


class Zamanlama(unittest.IsolatedAsyncioTestCase):
    async def test_tam_saatinde_bir_kez(self):
        saat = Saat(datetime(2026, 11, 16, 14, 0, tzinfo=TR))
        z, depo, tetik = kur(saat)
        ok, m = await z.ayarla({"eylem": "ekle", "zaman": "15:00", "metin": "Ömer'i ara"})
        self.assertTrue(ok)
        self.assertIn("Pazartesi (16 Kasım) 15:00 · hatırlatma: Ömer'i ara", m)
        saat.t = datetime(2026, 11, 16, 14, 59, 50, tzinfo=TR)
        await z.tik()
        await bitir(z)
        self.assertEqual(tetik, [])
        saat.t = datetime(2026, 11, 16, 15, 0, 10, tzinfo=TR)
        await z.tik()
        await z.tik()
        await bitir(z)
        self.assertEqual(tetik, [("Ömer'i ara", "hatirlat", False)])  # tek sefer, gecikmesiz
        self.assertEqual(z.kayitlar, [])  # tek seferlik silindi
        self.assertEqual(depo.veri["zamanli"], {"kayitlar": []})

    async def test_telefonla_hatirlatma_kaydi(self):
        saat = Saat(datetime(2026, 11, 16, 14, 0, tzinfo=TR))
        z, depo, _ = kur(saat)
        ok, m = await z.ayarla({"eylem": "ekle", "zaman": "15:00", "metin": "ilaç", "ara": True})
        self.assertTrue(ok)
        self.assertIn("(telefonla arayarak)", m)
        self.assertTrue(z.kayitlar[0]["ara"])

    async def test_her_gun_tekrar_ve_gorev(self):
        saat = Saat(datetime(2026, 11, 16, 21, 0, tzinfo=TR))
        z, _, tetik = kur(saat)
        await z.ayarla({"eylem": "ekle", "zaman": "22:00", "metin": "Masaüstü/rapor klasörünü OneDrive'a yedekle",
                        "tur": "gorev", "tekrar": "gunluk"})
        for gun in (16, 17, 18):
            saat.t = datetime(2026, 11, gun, 22, 0, 5, tzinfo=TR)
            await z.tik()
            await bitir(z)
        self.assertEqual([t[1] for t in tetik], ["gorev"] * 3)
        self.assertEqual(z.kayitlar[0]["zaman"], datetime(2026, 11, 19, 22, 0, tzinfo=TR).isoformat())

    async def test_gecikme_kurallari(self):
        saat = Saat(datetime(2026, 11, 16, 9, 0, tzinfo=TR))
        z, _, tetik = kur(saat)
        await z.ayarla({"eylem": "ekle", "zaman": "10:00", "metin": "az gecikmeli"})
        await z.ayarla({"eylem": "ekle", "zaman": "09:30", "metin": "çok gecikmeli"})
        saat.t = datetime(2026, 11, 16, 15, 45, tzinfo=TR)  # Render uyudu, geç uyandı
        await z.tik()
        await bitir(z)
        self.assertEqual(tetik, [("az gecikmeli", "hatirlat", True)])  # 5 sa 45 dk: hâlâ yapılır, gecikmeli notu
        self.assertEqual(z.kayitlar, [])  # 6 saati geçen atlandı ama kayıt da temizlendi

    async def test_yeniden_baslamada_kalici_ve_sil(self):
        saat = Saat(datetime(2026, 11, 16, 9, 0, tzinfo=TR))
        z, depo, _ = kur(saat)
        await z.ayarla({"eylem": "ekle", "zaman": "18:00", "metin": "tenis çantası"})
        z2, _, _ = kur(saat, depo)
        await z2.yukle()
        self.assertIn("#1", (await z2.ayarla({"eylem": "listele"}))[1])
        self.assertEqual(z2.bugun(date(2026, 11, 16)), ["18:00 hatırlatma: tenis çantası"])
        self.assertTrue((await z2.ayarla({"eylem": "sil", "id": 1}))[0])
        self.assertFalse((await z2.ayarla({"eylem": "sil", "id": 9}))[0])
        self.assertEqual(z2.kayitlar, [])


# --------------------------------------------------------------------------
# 2) PC'de dosya arama (gerçek geçici klasör)
# --------------------------------------------------------------------------

@unittest.skipUnless(sys.platform == "win32", "ajan Windows'ta çalışır")
class DosyaAra(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ajan"))
        import ajan
        cls.ajan = ajan
        cls.gecici = tempfile.TemporaryDirectory()
        k = Path(cls.gecici.name)
        (k / "okul" / "odevler" / "hafta3").mkdir(parents=True)
        (k / "okul" / "odevler" / "hafta3" / "Odev3.py").write_text("def topla(a, b):\n    return a + b  # FINAL\n",
                                                                   encoding="utf-8")
        (k / "okul" / "notlar.txt").write_text("Bilgisayar Ağları vize konuları\n", encoding="utf-8")
        (k / "okul" / "rapor.docx").write_bytes(b"PK\x03\x04")
        (k / "proje" / "node_modules" / "paket").mkdir(parents=True)
        (k / "proje" / "node_modules" / "paket" / "odev_gizli.py").write_text("FINAL", encoding="utf-8")
        cls.kok = str(k)

    @classmethod
    def tearDownClass(cls):
        cls.gecici.cleanup()

    def test_ada_gore_alt_klasorlere_iner(self):
        c = self.ajan.dosya_ara(self.kok, ad="odev")
        self.assertIn("Odev3.py", c)  # 3 seviye aşağıda, büyük/küçük harf fark etmez
        self.assertIn("| 1 sonuç,", c)
        self.assertNotIn("odev_gizli", c)  # node_modules'a girmez

    def test_joker_desen(self):
        c = self.ajan.dosya_ara(self.kok, ad="*.docx")
        self.assertIn("rapor.docx", c)
        self.assertNotIn("Odev3.py", c)

    def test_icerige_gore_satirla(self):
        c = self.ajan.dosya_ara(self.kok, icerik="vize")
        self.assertIn("notlar.txt", c)
        self.assertIn("satır 1: Bilgisayar Ağları vize konuları", c)
        c = self.ajan.dosya_ara(self.kok, ad="*.py", icerik="final")
        self.assertIn("satır 2:", c)
        self.assertIn("Odev3.py", c)

    def test_bulunamazsa_ve_bos_istek(self):
        self.assertIn("| 0 sonuç,", self.ajan.dosya_ara(self.kok, ad="yokboyle"))
        with self.assertRaises(ValueError):
            self.ajan.dosya_ara(self.kok)

    def test_hassas_kok_reddedilir(self):
        with self.assertRaises(PermissionError):
            self.ajan.dosya_ara(os.path.expanduser(r"~\AppData\Local\BraveSoftware"), ad="x")


# --------------------------------------------------------------------------
# 3) OneDrive taşıma / yeniden adlandırma (rclone sahte)
# --------------------------------------------------------------------------

class OneDriveTasi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.var = {"Belgeler": True, "Belgeler/rapor.pdf": False, "Belgeler/arsiv": True,
                    "Belgeler/arsiv/eski.pdf": False}
        self.komutlar = []

        async def stat(yol):
            hit = next((k for k in self.var if k.casefold() == yol.casefold()), None)
            return None if hit is None else {"Name": hit.rsplit("/", 1)[-1], "IsDir": self.var[hit]}

        async def rclone(komut, *args, **kw):
            self.komutlar.append((komut, *args))
            return 0, b"", ""

        self.p = [mock.patch.object(onedrive, "_stat", stat), mock.patch.object(onedrive, "_rclone", rclone)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def _uzak(self, y):
        return onedrive._uzak(y)

    async def test_yeniden_adlandir(self):
        m = await onedrive.tasi("Belgeler/rapor.pdf", "Belgeler/rapor-final.pdf")
        self.assertIn("Dosya taşındı", m)
        self.assertEqual(self.komutlar, [("moveto", self._uzak("Belgeler/rapor.pdf"),
                                          self._uzak("Belgeler/rapor-final.pdf"))])

    async def test_klasorun_icine(self):
        await onedrive.tasi("Belgeler/rapor.pdf", "Belgeler/arsiv/")
        self.assertEqual(self.komutlar[-1][2], self._uzak("Belgeler/arsiv/rapor.pdf"))

    async def test_uzerine_yazmaz(self):
        with self.assertRaises(onedrive.OneDriveHatasi) as h:
            await onedrive.tasi("Belgeler/rapor.pdf", "Belgeler/arsiv/eski.pdf")
        self.assertIn("üzerine yazmam", str(h.exception))
        self.assertEqual(self.komutlar, [])

    async def test_guvenlik(self):
        for kaynak, hedef in (("Belgeler", "Belgeler/yeni"), ("Belgeler/arsiv", "Belgeler/arsiv/alt/"),
                              ("Belgeler/yok.pdf", "Belgeler/x.pdf"), ("Belgeler/rapor.pdf", "Windows/rapor.pdf")):
            with self.assertRaises(onedrive.OneDriveHatasi, msg=f"{kaynak} -> {hedef}"):
                await onedrive.tasi(kaynak, hedef)
        self.assertEqual(self.komutlar, [])

    async def test_sadece_harf_buyuklugu(self):
        await onedrive.tasi("Belgeler/rapor.pdf", "Belgeler/Rapor.pdf")
        self.assertEqual(len(self.komutlar), 1)


class Kayitlar(unittest.TestCase):
    def test_araclar_tanimli_ve_sade(self):
        import main
        import ordu
        import tools
        for ad in ("dosya_ara", "onedrive_tasi", "zamanla"):
            self.assertIn(ad, tools.TOOLLAR)
        self.assertIn("dosya_ara", ordu.ROLLER["kodcu"].toollar)
        self.assertEqual(main._kisa_ozet("dosya_ara", {"kok": "C:/", "ad": "odev"}), "🔎 Bilgisayarda dosya arıyorum (odev)")
        self.assertIn("Buluttaki dosyayı taşıyorum", main._kisa_ozet("onedrive_tasi",
                                                                    {"kaynak": "Belgeler/a.pdf", "hedef": "Belgeler/b.pdf"},
                                                                    simge="🟡"))
        self.assertIn("rclone moveto", "rclone moveto")  # izin listesinde
        self.assertIn("moveto", onedrive._IZINLI_KOMUTLAR)


if __name__ == "__main__":
    unittest.main()
