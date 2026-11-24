"""Eklenti klasörü: geçerli eklenti yüklenir ve çalışır, bozuk/çakışan eklenti atlanır, `_` dosyaları yüklenmez."""

import asyncio
import tempfile
import unittest
from pathlib import Path

import eklenti
import tools

GECERLI = '''
ARAC = {"ad": "test_selam", "aciklama": "Selam verir", "parametreler": {"type": "object", "properties": {}}}
def calistir(a):
    return "selam " + str(a.get("kim", ""))
'''
ASENKRON = '''
ARAC = {"ad": "test_asenkron", "aciklama": "x", "risk": "orta"}
async def calistir(a):
    return (False, "olmadi")
'''
HATALI = '''
ARAC = {"ad": "test_patlayan", "aciklama": "x"}
def calistir(a):
    raise RuntimeError("bum")
'''
CAKISAN = 'ARAC = {"ad": "hava_durumu", "aciklama": "x"}\ndef calistir(a): return "x"\n'
SOZDIZIMI = "def bozuk(:\n"
YASAK_RISK = 'ARAC = {"ad": "test_riskli", "aciklama": "x", "risk": "yüksek"}\ndef calistir(a): return "x"\n'
ALTCIZGILI = GECERLI.replace("test_selam", "test_gizli")


class EklentiTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.klasor = Path(self.tmp.name)
        self.once = set(tools.TOOLLAR)

    def tearDown(self):
        for ad in set(tools.TOOLLAR) - self.once:
            tools.TOOLLAR.pop(ad)
            eklenti._islevler.pop(ad, None)
        self.tmp.cleanup()

    def yaz(self, ad, icerik):
        (self.klasor / ad).write_text(icerik, encoding="utf-8")

    def test_gecerli_yuklenir_ve_calisir(self):
        self.yaz("a.py", GECERLI)
        self.assertEqual(eklenti.yukle(self.klasor), ["test_selam"])
        arac = tools.TOOLLAR["test_selam"]
        self.assertEqual((arac.hedef, arac.risk), ("eklenti", "düşük"))
        self.assertIn("test_selam", [s["function"]["name"] for s in tools.openai_semalari()])
        self.assertEqual(asyncio.run(eklenti.calistir("test_selam", {"kim": "Ali"})), (True, "selam Ali"))

    def test_asenkron_ve_basarisiz_sonuc(self):
        self.yaz("b.py", ASENKRON)
        eklenti.yukle(self.klasor)
        self.assertEqual(tools.TOOLLAR["test_asenkron"].risk, "orta")
        self.assertEqual(asyncio.run(eklenti.calistir("test_asenkron", {})), (False, "olmadi"))

    def test_calisma_hatasi_vekili_dusurmez(self):
        self.yaz("c.py", HATALI)
        eklenti.yukle(self.klasor)
        basarili, metin = asyncio.run(eklenti.calistir("test_patlayan", {}))
        self.assertFalse(basarili)
        self.assertIn("bum", metin)

    def test_bozuk_cakisan_yasak_riskli_ve_altcizgili_atlanir(self):
        self.yaz("d.py", CAKISAN)
        self.yaz("e.py", SOZDIZIMI)
        self.yaz("f.py", YASAK_RISK)
        self.yaz("_g.py", ALTCIZGILI)
        self.yaz("h.py", GECERLI)
        with self.assertLogs("vekil.eklenti", level="WARNING") as log:
            self.assertEqual(eklenti.yukle(self.klasor), ["test_selam"])
        self.assertEqual(len(log.output), 3)
        self.assertNotIn("test_gizli", tools.TOOLLAR)
        self.assertNotEqual(tools.TOOLLAR["hava_durumu"].hedef, "eklenti")  # yerleşik araç ezilmedi

    def test_olmayan_klasor_ve_bilinmeyen_arac(self):
        self.assertEqual(eklenti.yukle(self.klasor / "yok"), [])
        self.assertFalse(asyncio.run(eklenti.calistir("yok_boyle_arac", {}))[0])

    def test_ornek_sablon_gecerli(self):
        ornek = Path(eklenti.KLASOR) / "_ornek.py"
        (self.klasor / "ornek.py").write_text(ornek.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(eklenti.yukle(self.klasor), ["saat_sor"])
        self.assertTrue(asyncio.run(eklenti.calistir("saat_sor", {}))[0])


if __name__ == "__main__":
    unittest.main()
