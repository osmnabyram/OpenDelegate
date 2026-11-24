"""Konu takibi: konuşmadan çıkan açık konuyu sorar (haftada 1, gündüz); susturma model tool'uyla."""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import takip
from zamanlayici import TR

class Saat:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def depo():
    d = {}

    async def oku(k):
        return d.get(k)

    async def yaz(k, v):
        d[k] = v
    return d, oku, yaz


class KonuTakibi(unittest.IsolatedAsyncioTestCase):
    async def kur(self, konular=None):
        self.mesajlar = []
        self.d, oku, yaz = depo()
        self.saat = Saat(datetime(2026, 11, 14, 14, 0, tzinfo=TR))
        self.konular = konular if konular is not None else [
            {"anahtar": "is:vize", "metin": "vize başvurusu evrakları", "nerede": "yapılacaklar listende",
             "baslangic": "2026-11-05"},
            {"anahtar": "is:kitap", "metin": "kitap iadesi", "nerede": "yapılacaklar listende",
             "baslangic": "2026-11-13"}]

        async def gonder(m):
            self.mesajlar.append(m)

        async def kaynak():
            return self.konular

        self.k = takip.KonuTakip(gonder=gonder, kaynak=kaynak, oku=oku, yaz=yaz, simdi=self.saat)
        await self.k.yukle()

    async def test_bosta_kalan_konu_sorulur_haftada_bir(self):
        await self.kur()
        await self.k.tik()
        self.assertEqual(len(self.mesajlar), 1)
        self.assertIn("vize başvurusu evrakları", self.mesajlar[0])
        self.assertIn("bir daha sormam", self.mesajlar[0])
        self.saat.t += timedelta(days=3)  # hafta dolmadan ikinci konu bayatlasa da sorulmaz
        await self.k.tik()
        self.assertEqual(len(self.mesajlar), 1)
        self.saat.t += timedelta(days=5)
        await self.k.tik()
        self.assertEqual(len(self.mesajlar), 2)
        self.assertIn("kitap iadesi", self.mesajlar[1])  # aynı konu 3 hafta tekrar sorulmaz

    async def test_konusmadan_cikan_soru_kullanilir(self):
        await self.kur([{"anahtar": "konu:vize", "metin": "vize randevusu", "baslangic": "2026-11-02",
                         "soru": "Efendim, geçen hafta vize randevusundan bahsetmiştin, ne oldu?"}])
        await self.k.tik()
        self.assertTrue(self.mesajlar[0].startswith("Efendim, geçen hafta vize randevusundan bahsetmiştin, ne oldu?"))
        self.assertIn("bir daha sormam", self.mesajlar[0])
        self.assertFalse(self.k.sorma_zamani())  # haftalık hak doldu

    async def test_gece_sormaz(self):
        await self.kur()
        self.saat.t = self.saat.t.replace(hour=23)
        await self.k.tik()
        self.assertEqual(self.mesajlar, [])

    async def test_konusulan_konu_sorulmaz(self):
        await self.kur([{"anahtar": "is:vize", "metin": "vize başvurusu evrakları", "baslangic": "2026-11-01"}])
        await self.k.tik()  # konular yüklenir (ve sorulur) -> sıfırdan dene
        self.mesajlar.clear()
        await self.kur([{"anahtar": "is:vize", "metin": "vize başvurusu evrakları", "baslangic": "2026-11-01"}])
        self.k._son_konular = self.konular
        self.assertIsNone(await self.k.mesaj("kanka vize başvurusu için randevu aldım"))
        await self.k.tik()
        self.assertEqual(self.mesajlar, [])

    async def test_sustur(self):
        await self.kur()
        await self.k.tik()
        self.assertIn("vize başvurusu evrakları", self.k.son_soru_satiri())  # model bağlamı görsün
        ok, cevap = await self.k.ayarla({"eylem": "sustur"})
        self.assertTrue(ok)
        self.assertIn("vize başvurusu evrakları", cevap)
        self.assertIn("is:vize", self.d["konu_takip"]["sessiz"])
        self.assertEqual(self.k.son_soru_satiri(), "")
        self.saat.t += timedelta(days=60)
        self.konular = self.konular[:1]
        await self.k.tik()
        self.assertEqual(len(self.mesajlar), 1)  # susturulan konu bir daha sorulmaz

    async def test_kelime_yakalama_yok(self):
        await self.kur()
        await self.k.tik()
        self.assertIsNone(await self.k.mesaj("rahat bırak kanka"))  # artık modele gider, kalıp yok
        self.assertEqual(self.d["konu_takip"]["sessiz"], [])

    async def test_hepsini_sustur_ve_ac(self):
        await self.kur()
        self.assertTrue((await self.k.ayarla({"eylem": "hepsini_sustur"}))[0])
        await self.k.tik()
        self.assertEqual(self.mesajlar, [])
        self.assertTrue((await self.k.ayarla({"eylem": "ac"}))[0])
        await self.k.tik()
        self.assertEqual(len(self.mesajlar), 1)


if __name__ == "__main__":
    unittest.main()
